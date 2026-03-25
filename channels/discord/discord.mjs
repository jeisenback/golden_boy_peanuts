#!/usr/bin/env node
import 'dotenv/config';
import { Client, GatewayIntentBits } from 'discord.js';
import http from 'http';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const TOKEN = process.env.DISCORD_BOT_TOKEN;
const ALLOWED = (process.env.DISCORD_ALLOWED_USERS || '').split(',').map(s => s.trim()).filter(Boolean);
const MAINTENANCE_ALLOW_USERS = (process.env.MAINTENANCE_ALLOW_USERS || '').split(',').map(s => s.trim()).filter(Boolean);
const DATA_DIR = path.resolve(process.cwd(), process.env.DATA_DIR || 'channels/discord/.data');
const SESSIONS_FILE = path.join(DATA_DIR, 'sessions.json');
const AUDIT_LOG_FILE = path.resolve(process.cwd(), process.env.AUDIT_LOG_FILE || path.join(DATA_DIR, 'audit.log.jsonl'));
const SESSION_TTL_HOURS = Number(process.env.SESSION_TTL_HOURS || 24);
const APPROVAL_TTL_MINUTES = Number(process.env.APPROVAL_TTL_MINUTES || 15);
const MAINTENANCE_MESSAGE = process.env.MAINTENANCE_MESSAGE || 'Maintenance mode enabled. New requests are temporarily paused.';
let maintenanceMode = /^(1|true|on|yes)$/i.test(process.env.MAINTENANCE_MODE || '');

const SESSION_TTL_MS = Math.max(1, SESSION_TTL_HOURS) * 60 * 60 * 1000;
const APPROVAL_TTL_MS = Math.max(1, APPROVAL_TTL_MINUTES) * 60 * 1000;
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));

if (!TOKEN) {
  console.error('DISCORD_BOT_TOKEN not set');
  process.exit(1);
}

const configuredRoutesFile = process.env.ROUTES_FILE || 'routes.json';
const routesCandidates = [
  path.resolve(process.cwd(), configuredRoutesFile),
  path.resolve(SCRIPT_DIR, configuredRoutesFile),
  path.resolve(SCRIPT_DIR, 'routes.json'),
  path.resolve(process.cwd(), 'channels/discord/routes.json')
];
const routesPath = routesCandidates.find(candidate => fs.existsSync(candidate)) || routesCandidates[0];
let routes = { default: { port: 8788 }, projects: {} };
try {
  routes = JSON.parse(fs.readFileSync(routesPath, 'utf8'));
} catch (e) {
  console.warn(`routes.json not found or invalid at ${routesPath}, using defaults`, e.message);
}

function ensureDataDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

function appendAudit(eventType, payload = {}) {
  ensureDataDir();
  try {
    const record = {
      ts: new Date().toISOString(),
      eventType,
      ...payload
    };
    fs.appendFileSync(AUDIT_LOG_FILE, `${JSON.stringify(record)}\n`);
  } catch (err) {
    console.warn('audit log write failed', err.message || err);
  }
}

function loadSessions() {
  ensureDataDir();
  try {
    const raw = fs.readFileSync(SESSIONS_FILE, 'utf8');
    const parsed = JSON.parse(raw);
    return typeof parsed === 'object' && parsed ? parsed : {};
  } catch (_err) {
    return {};
  }
}

function saveSessions(sessions) {
  ensureDataDir();
  fs.writeFileSync(SESSIONS_FILE, JSON.stringify(sessions, null, 2));
}

const sessions = loadSessions();
const pendingApprovals = new Map();

function isMaintenanceAdmin(userId) {
  const id = String(userId);
  if (MAINTENANCE_ALLOW_USERS.length > 0) return MAINTENANCE_ALLOW_USERS.includes(id);
  if (ALLOWED.length > 0) return ALLOWED.includes(id);
  return false;
}

function removeSession(threadId, reason) {
  const existing = sessions[threadId];
  if (!existing) return false;
  delete sessions[threadId];
  saveSessions(sessions);
  appendAudit('session.expired', {
    threadId,
    ownerUserId: existing.ownerUserId,
    reason
  });
  return true;
}

function sessionIsExpired(session) {
  const last = Date.parse(session.lastActiveAt || session.createdAt || 0);
  if (!last) return true;
  return (Date.now() - last) > SESSION_TTL_MS;
}

function touchSession(session, { persist = false } = {}) {
  session.lastActiveAt = new Date().toISOString();
  if (persist) saveSessions(sessions);
}

function pruneExpiredSessions() {
  let changed = false;
  for (const [threadId, session] of Object.entries(sessions)) {
    if (sessionIsExpired(session)) {
      delete sessions[threadId];
      appendAudit('session.expired', {
        threadId,
        ownerUserId: session.ownerUserId,
        reason: 'ttl'
      });
      changed = true;
    }
  }
  if (changed) saveSessions(sessions);
}

function cleanupExpiredApprovals() {
  const now = Date.now();
  for (const [promptId, pending] of pendingApprovals.entries()) {
    if (pending.expiresAt > now) continue;
    pendingApprovals.delete(promptId);
    appendAudit('approval.expired', {
      promptMessageId: promptId,
      requesterUserId: pending.requesterUserId,
      project: pending.projectKey,
      threadId: pending.payload?.session?.threadId || null
    });
    client.channels.fetch(pending.channelId)
      .then(channel => channel?.messages?.fetch?.(promptId))
      .then(prompt => prompt?.edit?.('Approval expired. Message was not sent to webhook.'))
      .catch(() => {});
  }
}

pruneExpiredSessions();
setInterval(() => {
  pruneExpiredSessions();
  cleanupExpiredApprovals();
}, 60 * 1000);

// Deduplication: track recently processed message IDs to prevent duplicate handling
const recentMessages = new Set();
const MESSAGE_DEDUP_TTL_MS = 2000; // 2 second window
function markMessageProcessed(messageId) {
  recentMessages.add(messageId);
  setTimeout(() => recentMessages.delete(messageId), MESSAGE_DEDUP_TTL_MS);
}
function isMessageAlreadyProcessed(messageId) {
  return recentMessages.has(messageId);
}

// Response tracking: store pending responses keyed by requestId until the webhook responds
const pendingResponses = new Map();
const RESPONSE_SERVER_PORT = Number(process.env.RESPONSE_SERVER_PORT || 8789);
const PENDING_RESPONSE_TTL_MS = Number(process.env.PENDING_RESPONSE_TTL_MS || (10 * 60 * 1000));
let responseServer = null;

function generateRequestId() {
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
}

function rememberPendingResponse(requestId, payload) {
  pendingResponses.set(requestId, {
    channelId: payload?.channelId || null,
    threadId: payload?.session?.threadId || null,
    authorUserId: payload?.author?.id || null,
    createdAt: Date.now()
  });

  setTimeout(() => {
    const pending = pendingResponses.get(requestId);
    if (!pending) return;
    pendingResponses.delete(requestId);
    appendAudit('response.expired', {
      requestId,
      channelId: pending.channelId,
      threadId: pending.threadId,
      authorUserId: pending.authorUserId
    });

    const targetChannelId = pending.threadId || pending.channelId;
    if (!targetChannelId) return;

    client.channels.fetch(targetChannelId)
      .then(channel => channel?.send?.('Response timed out. The responder did not return a reply.'))
      .catch(() => {});
  }, PENDING_RESPONSE_TTL_MS);
}

function startResponseServer() {
  responseServer = http.createServer(async (req, res) => {
    if (req.method === 'POST' && req.url === '/response') {
      try {
        const chunks = [];
        for await (const chunk of req) {
          chunks.push(chunk);
        }
        const raw = Buffer.concat(chunks).toString('utf8') || '{}';
        const body = JSON.parse(raw);
        const requestId = body.requestId;
        const responseText = String(body.response || body.content || '').trim();

        if (!requestId || !responseText) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: false, error: 'Missing requestId or response text' }));
          return;
        }

        const pending = pendingResponses.get(requestId);
        if (!pending) {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: false, error: 'Request not found or expired' }));
          return;
        }

        pendingResponses.delete(requestId);

        const targetChannelId = pending.threadId || pending.channelId;
        if (!targetChannelId) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: false, error: 'No destination channel found' }));
          return;
        }

        const channel = await client.channels.fetch(targetChannelId);
        await channel.send(`Response: ${responseText}`);

        appendAudit('response.received', {
          requestId,
          channelId: pending.channelId,
          threadId: pending.threadId,
          response: responseText
        });

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
      } catch (err) {
        console.error('response handler error', err);
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: String(err) }));
      }
    } else {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: 'not found' }));
    }
  });

  responseServer.listen(RESPONSE_SERVER_PORT, '127.0.0.1', () => {
    console.log(`discord-channel: response server listening on http://127.0.0.1:${RESPONSE_SERVER_PORT}`);
  });
}

const client_init = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildMessageReactions,
    GatewayIntentBits.DirectMessages,
    GatewayIntentBits.DirectMessageReactions,
    GatewayIntentBits.MessageContent
  ],
  partials: ['CHANNEL', 'MESSAGE', 'REACTION']
});
const client = client_init;

function sessionForMessage(msg) {
  if (msg.channel?.isThread?.()) {
    const session = sessions[msg.channel.id] || null;
    if (!session) return null;
    if (sessionIsExpired(session)) {
      removeSession(msg.channel.id, 'ttl');
      return null;
    }
    return session;
  }
  return null;
}

function normalizeProjectKey(projectKey) {
  if (!projectKey || projectKey === 'default') return 'default';
  const key = String(projectKey).toLowerCase();
  return routes.projects && routes.projects[key] ? key : 'default';
}

function projectConfig(projectKey) {
  const normalized = normalizeProjectKey(projectKey);
  const cfg = normalized === 'default' ? routes.default : (routes.projects[normalized] || {});
  return {
    key: normalized,
    port: cfg.port || routes.default.port || 8788
  };
}

function isUserAllowed(userId) {
  if (ALLOWED.length === 0) return true;
  return ALLOWED.includes(String(userId));
}

function findProjectForMessage(msg) {
  const session = sessionForMessage(msg);
  if (session) {
    return normalizeProjectKey(session.project);
  }

  // 1) If message in a guild channel, match by channel id or name
  if (msg.channel && msg.channel.type !== 1) { // Type 1 == DM in discord.js v14
    const chanId = msg.channel.id;
    const chanName = msg.channel.name || '';
    for (const [proj, cfg] of Object.entries(routes.projects || {})) {
      if ((cfg.channelIds || []).includes(chanId)) return proj;
      if ((cfg.channelNames || []).includes(chanName)) return proj;
    }
  }

  // 2) If DM, allow prefix 'project: <name>' or '<name>: ' at start
  const content = (msg.content || '').trim();
  const prefixMatch = content.match(/^([a-zA-Z0-9_-]+)\s*:\s*(.*)$/s);
  if (prefixMatch) {
    const key = prefixMatch[1].toLowerCase();
    if (routes.projects && routes.projects[key]) return key;
  }

  // 3) fallback to default
  return 'default';
}

async function postToWebhook(port, payload, requestId) {
  const url = `http://127.0.0.1:${port}/feature`;
  const callbackUrl = `http://127.0.0.1:${RESPONSE_SERVER_PORT}/response`;
  
  const enrichedPayload = {
    ...payload,
    requestId,
    callbackUrl
  };
  
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(enrichedPayload),
      // short timeout not available in fetch default; rely on local connectivity
    });
    return { ok: res.ok, status: res.status };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

client.on('clientReady', () => {
  console.log(`discord-channel: logged in as ${client.user.tag}`);
  console.log(
    `discord-channel: maintenance=${maintenanceMode ? 'on' : 'off'} sessionTtl=${SESSION_TTL_HOURS}h approvalTtl=${APPROVAL_TTL_MINUTES}m`
  );
});

async function handleCommand(message) {
  const raw = (message.content || '').trim();
  if (!raw.toLowerCase().startsWith('cp ')) return false;

  const parts = raw.split(/\s+/);
  const cmd = (parts[1] || '').toLowerCase();

  if (cmd === 'new') {
    if (!message.channel || message.channel.type === 1) {
      await message.reply('`cp new` works in a server text channel.');
      return true;
    }
    if (message.channel.isThread?.()) {
      await message.reply('You are already in a thread session.');
      return true;
    }

    const threadName = parts.slice(2).join(' ') || `cp-${message.author.username}`;
    const thread = await message.startThread({
      name: threadName.slice(0, 90),
      autoArchiveDuration: 1440,
      reason: `Copilot session by ${message.author.username}`
    });

    sessions[thread.id] = {
      threadId: thread.id,
      ownerUserId: String(message.author.id),
      project: 'default',
      approve: 'ask',
      createdAt: new Date().toISOString(),
      lastActiveAt: new Date().toISOString()
    };
    saveSessions(sessions);
    appendAudit('session.created', {
      threadId: thread.id,
      ownerUserId: String(message.author.id)
    });

    await thread.send(
      'Session created. Use `cp repo <project>` and `cp approve ask|always`.'
    );
    await message.reply(`Session thread created: <#${thread.id}>`);
    return true;
  }

  const session = sessionForMessage(message);
  if (!session) {
    await message.reply('Use `cp new <name>` in a channel first, then run session commands inside that thread.');
    return true;
  }

  if (cmd === 'repo') {
    const wanted = (parts[2] || '').toLowerCase();
    if (!wanted) {
      await message.reply(`Current repo route: \`${session.project || 'default'}\`.`);
      return true;
    }

    const key = normalizeProjectKey(wanted);
    if (wanted !== 'default' && key === 'default') {
      await message.reply(`Unknown project \`${wanted}\`. Falling back to \`default\`.`);
    }
    session.project = key;
    touchSession(session);
    saveSessions(sessions);
    await message.reply(`Session repo route set to \`${key}\`.`);
    return true;
  }

  if (cmd === 'approve') {
    const mode = (parts[2] || '').toLowerCase();
    if (!mode) {
      await message.reply(`Current approval mode: \`${session.approve || 'ask'}\`.`);
      return true;
    }
    if (!['ask', 'always'].includes(mode)) {
      await message.reply('Usage: `cp approve ask` or `cp approve always`.');
      return true;
    }
    session.approve = mode;
    touchSession(session);
    saveSessions(sessions);
    await message.reply(`Session approval mode set to \`${mode}\`.`);
    return true;
  }

  if (cmd === 'maintenance') {
    if (!isMaintenanceAdmin(message.author.id)) {
      await message.reply('Maintenance toggle is restricted. Set `MAINTENANCE_ALLOW_USERS` or `DISCORD_ALLOWED_USERS`.');
      return true;
    }

    const mode = (parts[2] || '').toLowerCase();
    if (!mode || mode === 'status') {
      await message.reply(`Maintenance mode is currently \`${maintenanceMode ? 'on' : 'off'}\`.`);
      return true;
    }
    if (!['on', 'off'].includes(mode)) {
      await message.reply('Usage: `cp maintenance status|on|off`.');
      return true;
    }

    maintenanceMode = mode === 'on';
    appendAudit('maintenance.toggled', {
      byUserId: String(message.author.id),
      mode: maintenanceMode ? 'on' : 'off'
    });
    await message.reply(`Maintenance mode is now \`${maintenanceMode ? 'on' : 'off'}\`.`);
    return true;
  }

  if (cmd === 'session') {
    const cfg = projectConfig(session.project);
    await message.reply(
      `Session: repo=\`${cfg.key}\`, port=\`${cfg.port}\`, approve=\`${session.approve || 'ask'}\``
    );
    return true;
  }

  await message.reply('Unknown command. Try `cp repo`, `cp approve`, or `cp session`.');
  return true;
}

async function queueMessageWithApproval(message, payload, projectKey, port) {
  const prompt = await message.reply(
    `Approve send to \`${projectKey}\` (port ${port})? React 👍 to approve or 👎 to deny within ${APPROVAL_TTL_MINUTES}m.`
  );
  pendingApprovals.set(prompt.id, {
    promptMessageId: prompt.id,
    channelId: prompt.channel.id,
    requesterUserId: String(message.author.id),
    payload,
    projectKey,
    port,
    requestedAt: Date.now(),
    expiresAt: Date.now() + APPROVAL_TTL_MS
  });

  appendAudit('approval.requested', {
    promptMessageId: prompt.id,
    requesterUserId: String(message.author.id),
    project: projectKey,
    threadId: payload?.session?.threadId || null
  });

  await prompt.react('👍');
  await prompt.react('👎');
}

async function forwardPayloadAndNotify(channel, payload, projectKey, port) {
  const requestId = generateRequestId();
  rememberPendingResponse(requestId, payload);

  const res = await postToWebhook(port, payload, requestId);
  if (res.ok) {
    appendAudit('forward.success', {
      project: projectKey,
      port,
      requestId,
      threadId: payload?.session?.threadId || null,
      authorUserId: payload?.author?.id
    });
    return;
  }

  pendingResponses.delete(requestId);
  appendAudit('forward.failed', {
    project: projectKey,
    port,
    requestId,
    threadId: payload?.session?.threadId || null,
    authorUserId: payload?.author?.id,
    error: res.error || res.status
  });
  await channel.send(`Failed to queue to project ${projectKey}: ${res.error || res.status}`);
}

client.on('messageCreate', async (message) => {
  try {
    // Skip if this message is already being processed (deduplication)
    if (isMessageAlreadyProcessed(message.id)) {
      return;
    }
    markMessageProcessed(message.id);

    pruneExpiredSessions();
    cleanupExpiredApprovals();

    // ignore bot messages
    if (message.author?.bot) return;

    // allow only from allowed users if configured
    if (!isUserAllowed(message.author.id)) return;

    if (maintenanceMode && !isMaintenanceAdmin(message.author.id)) {
      appendAudit('maintenance.blocked_message', {
        userId: String(message.author.id),
        channelId: message.channel?.id,
        channelName: message.channel?.name || null
      });
      await message.reply(MAINTENANCE_MESSAGE);
      return;
    }

    if (await handleCommand(message)) return;

    const projectKey = findProjectForMessage(message);
    const cfg = projectConfig(projectKey);
    const session = sessionForMessage(message);

    const payload = {
      author: { id: message.author.id, username: message.author.username },
      project: cfg.key,
      channelId: message.channel?.id,
      channelName: message.channel?.name || null,
      content: message.content,
      attachments: message.attachments?.map(a => ({ url: a.url, name: a.name })) || [],
      session: session
        ? {
            threadId: session.threadId,
            approve: session.approve || 'ask',
            ownerUserId: session.ownerUserId
          }
        : null
    };

    if (session) {
      touchSession(session, { persist: true });
    }

    if (session && (session.approve || 'ask') === 'ask') {
      await queueMessageWithApproval(message, payload, cfg.key, cfg.port);
    } else {
      await forwardPayloadAndNotify(message.channel, payload, cfg.key, cfg.port);
    }
  } catch (err) {
    console.error('message handler error', err);
  }
});

client.on('messageReactionAdd', async (reaction, user) => {
  try {
    if (user?.bot) return;

    let r = reaction;
    if (r.partial) {
      r = await r.fetch();
    }
    const promptId = r.message.id;
    const pending = pendingApprovals.get(promptId);
    if (!pending) return;
    if (!isUserAllowed(user.id)) return;
    if (String(user.id) !== pending.requesterUserId) return;

    if (pending.expiresAt <= Date.now()) {
      pendingApprovals.delete(promptId);
      appendAudit('approval.expired', {
        promptMessageId: promptId,
        requesterUserId: pending.requesterUserId,
        project: pending.projectKey,
        threadId: pending.payload?.session?.threadId || null
      });
      await r.message.edit('Approval expired. Message was not sent to webhook.');
      return;
    }

    if (maintenanceMode && !isMaintenanceAdmin(user.id)) {
      await r.message.edit(MAINTENANCE_MESSAGE);
      return;
    }

    const emoji = r.emoji?.name;
    if (emoji !== '👍' && emoji !== '👎') return;

    pendingApprovals.delete(promptId);

    if (emoji === '👎') {
      appendAudit('approval.denied', {
        promptMessageId: promptId,
        requesterUserId: pending.requesterUserId,
        project: pending.projectKey,
        threadId: pending.payload?.session?.threadId || null
      });
      await r.message.edit('Denied. Message was not sent to webhook.');
      return;
    }

    appendAudit('approval.approved', {
      promptMessageId: promptId,
      requesterUserId: pending.requesterUserId,
      project: pending.projectKey,
      threadId: pending.payload?.session?.threadId || null
    });

    await r.message.edit('Approved. Awaiting response...');
    await forwardPayloadAndNotify(r.message.channel, pending.payload, pending.projectKey, pending.port);
  } catch (err) {
    console.error('reaction handler error', err);
  }
});

startResponseServer();

client.login(TOKEN).catch(err => {
  console.error('login FAILED:', err.message || err);
  process.exit(1);
});
