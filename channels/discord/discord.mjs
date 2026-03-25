#!/usr/bin/env node
/**
 * Discord channel for the Energy Options Opportunity Agent.
 *
 * Two-way: Claude receives DMs and guild messages, replies via discord_reply tool.
 *
 * Required env vars (add to .env):
 *   DISCORD_BOT_TOKEN      — bot token from Discord Developer Portal
 *   DISCORD_ALLOWED_USERS  — comma-separated Discord user IDs allowed to reach Claude
 *
 * Setup:
 *   1. https://discord.com/developers/applications → New Application → Bot
 *   2. Bot settings → enable "Message Content Intent"
 *   3. OAuth2 → URL Generator → scopes: bot → permissions: Send Messages, Read Message History
 *   4. Add DISCORD_BOT_TOKEN and your Discord user ID to .env
 *
 * Usage:
 *   claude --dangerously-load-development-channels server:discord
 *
 * Test (from Discord):
 *   DM your bot: "what's the status of issue #151?"
 *   DM your bot: "implement fetch_reddit_sentiment"
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { Client, GatewayIntentBits, Partials } from 'discord.js'

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const BOT_TOKEN = process.env.DISCORD_BOT_TOKEN
const ALLOWED_USERS = new Set(
  (process.env.DISCORD_ALLOWED_USERS ?? '').split(',').map(s => s.trim()).filter(Boolean)
)

if (!BOT_TOKEN) {
  process.stderr.write('discord-channel: DISCORD_BOT_TOKEN not set — add it to .env\n')
  process.exit(1)
}

// ---------------------------------------------------------------------------
// MCP server — two-way channel
// ---------------------------------------------------------------------------

const mcp = new Server(
  { name: 'discord', version: '0.0.1' },
  {
    capabilities: {
      experimental: { 'claude/channel': {} },
      tools: {},
    },
    instructions:
      'You are the Energy Options Opportunity Agent development assistant, reachable via Discord. ' +
      'This is a Python/PostgreSQL project: 4-agent pipeline (Ingestion → Event Detection → Feature Generation → Strategy Evaluation) ' +
      'tracking WTI, Brent, USO, XLE, XOM, CVX options. Sprint 9 is active (Phase 3 Alternative Data Ingestion). ' +
      'CLAUDE.md hard stops apply: no new packages, no merges to develop/main, no langchain, local_check.sh exit 0 before commit.\n\n' +
      'Messages arrive as <channel source="discord" channel_id="..." user_id="..." username="...">. ' +
      'You MUST call discord_reply(channel_id, text) as the LAST step of every response — no exceptions. ' +
      'Keep replies concise (2000 char limit); summarise long answers.\n\n' +
      'For feature requests: confirm the issue is in-sprint (check HEARTBEAT.md), implement, run local_check.sh, commit, then discord_reply with a summary.\n\n' +
      'For sprint/status questions: read HEARTBEAT.md or gh issue list and discord_reply with a clear summary.\n\n' +
      'For ambiguous requests: discord_reply asking for clarification before doing any work.\n\n' +
      'For hard-stop decisions (new package, schema change, out-of-sprint work): discord_reply explaining what needs human approval.',
  },
)

// ---------------------------------------------------------------------------
// Reply tool
// ---------------------------------------------------------------------------

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'discord_reply',
      description: 'Send a message to a Discord channel or DM thread',
      inputSchema: {
        type: 'object',
        properties: {
          channel_id: {
            type: 'string',
            description: 'The Discord channel ID to reply in (from the channel_id attribute)',
          },
          text: {
            type: 'string',
            description: 'Message text. Discord limit is 2000 chars; longer replies are split automatically.',
          },
        },
        required: ['channel_id', 'text'],
      },
    },
  ],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  if (req.params.name !== 'discord_reply') {
    throw new Error(`unknown tool: ${req.params.name}`)
  }

  const { channel_id, text } = req.params.arguments
  process.stderr.write(`discord-channel: discord_reply called channel_id=${channel_id} len=${text.length}\n`)

  // For DM channels, channels.fetch may return null if not cached — fall back to user DM
  let ch = await discord.channels.fetch(channel_id).catch(err => {
    process.stderr.write(`discord-channel: failed to fetch channel ${channel_id}: ${err.message}\n`)
    return null
  })
  if (!ch) {
    // Try finding the channel via the cached DM channels
    ch = discord.channels.cache.get(channel_id) ?? null
  }

  if (!ch?.isTextBased()) {
    process.stderr.write(`discord-channel: could not resolve channel ${channel_id}\n`)
    throw new Error(`could not resolve channel ${channel_id}`)
  }

  // Split into 2000-char chunks so long responses aren't silently truncated
  const chunks = []
  for (let i = 0; i < text.length; i += 2000) chunks.push(text.slice(i, i + 2000))
  for (const chunk of chunks) await ch.send(chunk)

  process.stderr.write(`discord-channel: sent ${chunks.length} message(s)\n`)
  return { content: [{ type: 'text', text: `sent (${chunks.length} message(s))` }] }
})

// ---------------------------------------------------------------------------
// Connect to Claude Code over stdio
// ---------------------------------------------------------------------------

await mcp.connect(new StdioServerTransport())

// ---------------------------------------------------------------------------
// Discord client
// ---------------------------------------------------------------------------

const discord = new Client({
  intents: [
    GatewayIntentBits.DirectMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
  ],
  partials: [Partials.Channel, Partials.Message], // required for DMs
})

discord.once('ready', () => {
  process.stderr.write(`discord-channel: logged in as ${discord.user.tag}\n`)
})

discord.on('error', err => {
  process.stderr.write(`discord-channel: client error: ${err.message}\n`)
})

discord.on('messageCreate', async msg => {
  // Ignore the bot's own messages
  if (msg.author.bot) return

  // Gate on sender identity, not channel — prevents group chat injection
  if (ALLOWED_USERS.size > 0 && !ALLOWED_USERS.has(msg.author.id)) {
    process.stderr.write(`discord-channel: blocked message from unlisted user ${msg.author.id}\n`)
    return
  }

  await mcp.notification({
    method: 'notifications/claude/channel',
    params: {
      content: msg.content,
      meta: {
        channel_id: msg.channel.id,
        user_id: msg.author.id,
        // discord usernames are letters/digits/_ — safe as-is for a meta value
        username: msg.author.username,
      },
    },
  })
})

process.stderr.write(`discord-channel: token set=${!!BOT_TOKEN}, allowed_users=${[...ALLOWED_USERS].join(',') || '(none — all blocked)'}\n`)

discord.login(BOT_TOKEN).catch(err => {
  process.stderr.write(`discord-channel: login FAILED: ${err.message}\n`)
  process.exit(1)
})
