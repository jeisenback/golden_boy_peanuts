#!/usr/bin/env node
import { spawn } from 'child_process';
import fs from 'fs';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));

function loadEnvFile(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;

      const separator = trimmed.indexOf('=');
      if (separator === -1) continue;

      const key = trimmed.slice(0, separator).trim();
      if (!key || process.env[key] !== undefined) continue;

      let value = trimmed.slice(separator + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      process.env[key] = value;
    }
  } catch (err) {
    if (err?.code !== 'ENOENT') {
      console.warn(`webhook-channel: failed to load .env from ${filePath}: ${String(err)}`);
    }
  }
}

loadEnvFile(path.resolve(SCRIPT_DIR, '.env'));

const port = Number(process.env.PORT || 8788);
const AUTO_REPLY = /^(1|true|on|yes)$/i.test(process.env.WEBHOOK_AUTO_REPLY || 'true');
const UPSTREAM_URL = (process.env.COPILOT_UPSTREAM_URL || '').trim();
const UPSTREAM_AUTH_TOKEN = (process.env.COPILOT_UPSTREAM_TOKEN || '').trim();
const UPSTREAM_TIMEOUT_MS = Number(process.env.COPILOT_UPSTREAM_TIMEOUT_MS || 30000);
const RESPONSE_MODEL_ID = (process.env.DISCORD_RESPONDER_MODEL || 'claude-sonnet-4-6').trim();
const RESPONSE_SYSTEM_PROMPT = (
  process.env.DISCORD_RESPONDER_SYSTEM_PROMPT ||
  'You are GitHub Copilot inside a Discord bridge. Answer directly, briefly, and helpfully.'
).trim();
const REPO_ROOT = path.resolve(SCRIPT_DIR, '..', '..');
const RESPONDER_SCRIPT = path.resolve(SCRIPT_DIR, 'copilot_responder.py');

function pythonCandidates() {
  const envPython = (process.env.DISCORD_RESPONDER_PYTHON || '').trim();
  const venvWindows = path.resolve(REPO_ROOT, '.venv', 'Scripts', 'python.exe');
  const venvUnix = path.resolve(REPO_ROOT, '.venv', 'bin', 'python');
  return [envPython, venvWindows, venvUnix, 'python'].filter(Boolean);
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload)
  });
  res.end(payload);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw) {
    return {};
  }
  return JSON.parse(raw);
}

async function postJson(url, body, { authToken = '' } = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  const headers = { 'Content-Type': 'application/json' };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: controller.signal
  });
  clearTimeout(timeout);
  return { ok: res.ok, status: res.status };
}

async function requestUpstreamResponse(body) {
  if (!UPSTREAM_URL) {
    throw new Error('COPILOT_UPSTREAM_URL is not configured');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  const headers = { 'Content-Type': 'application/json' };
  if (UPSTREAM_AUTH_TOKEN) {
    headers.Authorization = `Bearer ${UPSTREAM_AUTH_TOKEN}`;
  }

  const upstreamRes = await fetch(UPSTREAM_URL, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      requestId: body.requestId,
      project: body.project || 'default',
      content: body.content || '',
      author: body.author || null,
      channelId: body.channelId || null,
      channelName: body.channelName || null,
      attachments: body.attachments || []
    }),
    signal: controller.signal
  });
  clearTimeout(timeout);

  const payload = await upstreamRes.json().catch(() => ({}));
  const text = String(payload.response || payload.content || payload.message || '').trim();

  if (!upstreamRes.ok) {
    throw new Error(`upstream status ${upstreamRes.status}`);
  }
  if (!text) {
    throw new Error('upstream returned no response text');
  }
  return text;
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    json(res, 200, { ok: true, service: 'webhook-channel', port });
    return;
  }

  if (req.method === 'POST' && req.url === '/copilot') {
    try {
      const body = await readBody(req);
      const response = await runCopilotResponder(body);
      json(res, 200, {
        ok: true,
        response
      });
    } catch (err) {
      json(res, 400, { ok: false, error: String(err) });
    }
    return;
  }

  if (req.method === 'POST' && req.url === '/feature') {
    try {
      const body = await readBody(req);
      const stamp = new Date().toISOString();
      const line = JSON.stringify({
        ts: stamp,
        project: body.project || 'default',
        author: body.author || null,
        channelId: body.channelId || null,
        channelName: body.channelName || null,
        content: body.content || '',
        attachments: body.attachments || [],
        requestId: body.requestId || null,
        callbackUrl: body.callbackUrl || null
      });
      process.stdout.write(`${line}\n`);

      if (AUTO_REPLY && body.callbackUrl && body.requestId) {
        let replyText = '';
        try {
          replyText = await requestUpstreamResponse(body);
          await postJson(body.callbackUrl, {
            requestId: body.requestId,
            response: replyText
          });
        } catch (err) {
          process.stderr.write(`callback failed: ${String(err)}\n`);

          // Send a visible error message back to Discord to avoid silent failures.
          try {
            await postJson(body.callbackUrl, {
              requestId: body.requestId,
              response: `Error contacting responder: ${String(err)}`
            });
          } catch (_callbackErr) {
            // Ignore callback retry failure.
          }
        }
      }

      json(res, 200, { ok: true, receivedAt: stamp });
    } catch (err) {
      json(res, 400, { ok: false, error: String(err) });
    }
    return;
  }

  json(res, 404, { ok: false, error: 'not found' });
});

server.listen(port, '127.0.0.1', () => {
  console.log(`webhook-channel listening on http://127.0.0.1:${port}`);
});

function runCopilotResponder(body) {
  return new Promise((resolve, reject) => {
    const candidates = pythonCandidates();

    const attempt = (index) => {
      if (index >= candidates.length) {
        reject(new Error('No working Python executable found for copilot responder'));
        return;
      }

      const child = spawn(candidates[index], [RESPONDER_SCRIPT], {
        cwd: REPO_ROOT,
        env: process.env,
        stdio: ['pipe', 'pipe', 'pipe']
      });

      let stdout = '';
      let stderr = '';
      const timer = setTimeout(() => {
        child.kill();
        reject(new Error('Copilot responder timed out'));
      }, UPSTREAM_TIMEOUT_MS);

      child.stdout.on('data', chunk => {
        stdout += chunk.toString();
      });

      child.stderr.on('data', chunk => {
        stderr += chunk.toString();
      });

      child.on('error', () => {
        clearTimeout(timer);
        attempt(index + 1);
      });

      child.on('close', code => {
        clearTimeout(timer);

        if (code !== 0) {
          if (index < candidates.length - 1 && /not recognized|ENOENT/i.test(stderr || stdout)) {
            attempt(index + 1);
            return;
          }
          reject(new Error((stderr || stdout || `Responder exited ${code}`).trim()));
          return;
        }

        try {
          const parsed = JSON.parse(stdout || '{}');
          if (!parsed.ok) {
            reject(new Error(parsed.error || 'Responder returned failure'));
            return;
          }
          resolve(String(parsed.response || '').trim());
        } catch (err) {
          reject(new Error(`Invalid responder output: ${String(err)}`));
        }
      });

      child.stdin.write(JSON.stringify({
        ...body,
        model_id: RESPONSE_MODEL_ID,
        system_prompt: RESPONSE_SYSTEM_PROMPT
      }));
      child.stdin.end();
    };

    attempt(0);
  });
}
