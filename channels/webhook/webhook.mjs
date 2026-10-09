#!/usr/bin/env node
/**
 * Webhook channel for the Energy Options Opportunity Agent.
 *
 * Forwards HTTP POST payloads into the Claude Code session as <channel> events.
 * Useful for CI alerts, market monitoring events, and pipeline notifications.
 *
 * Usage (dev):
 *   claude --dangerously-load-development-channels server:webhook
 *
 * Test:
 *   curl -X POST localhost:8788 -d "build failed on main: https://ci/run/1234"
 *   curl -X POST localhost:8788/market -H "X-Severity: high" -d "USO IV spike: 0.45"
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { createServer } from 'http'

const PORT = Number(process.env.WEBHOOK_PORT ?? 8788)

const mcp = new Server(
  { name: 'webhook', version: '0.0.1' },
  {
    capabilities: {
      experimental: { 'claude/channel': {} },
    },
    instructions:
      'You are the Energy Options Opportunity Agent development assistant. ' +
      'This is a Python/PostgreSQL project: 4-agent pipeline (Ingestion → Event Detection → Feature Generation → Strategy Evaluation) ' +
      'tracking WTI, Brent, USO, XLE, XOM, CVX. Sprint 9 is active (Phase 3 Alternative Data). ' +
      'All CLAUDE.md hard stops apply: no new packages, no merges, no langchain imports, local_check.sh must exit 0 before any commit.\n\n' +
      'Events arrive as <channel source="webhook" path="..." ...>.\n\n' +
      'path="/feature": implement the described task. Read HEARTBEAT.md first to confirm the issue is in-sprint. ' +
      'Follow the full ADLC loop: read files → implement → run `bash scripts/local_check.sh` → commit with format `<type>(<scope>): <desc> (#N)`. ' +
      'If the request hits a hard-stop or is out-of-sprint, say so before acting.\n\n' +
      'path="/ci": CI failure or test output. Diagnose root cause, fix, verify with local_check.sh.\n\n' +
      'path="/market": pipeline or market alert (stale data, fetch failure, IV spike). Assess if action is needed.\n\n' +
      'path="/": generic — use judgment.',
  },
)

await mcp.connect(new StdioServerTransport())

// HTTP server — localhost only; nothing outside this machine can POST
createServer((req, res) => {
  let body = ''
  req.on('data', chunk => { body += chunk })
  req.on('end', async () => {
    const meta = {
      path: req.url ?? '/',
      method: req.method ?? 'POST',
    }

    // Promote common headers to meta so Claude sees them as tag attributes
    const severity = req.headers['x-severity']
    if (typeof severity === 'string') meta.severity = severity

    const source = req.headers['x-source']
    if (typeof source === 'string') meta.event_source = source

    const payload = { content: body.trim() || '(empty payload)', meta }
    process.stderr.write(`webhook: sending notification ${JSON.stringify(payload)}\n`)
    try {
      await mcp.notification({
        method: 'notifications/claude/channel',
        params: payload,
      })
      process.stderr.write('webhook: notification sent ok\n')
      res.writeHead(200, { 'Content-Type': 'text/plain' })
      res.end('ok\n')
    } catch (err) {
      process.stderr.write(`webhook: notification FAILED: ${err.message}\n`)
      res.writeHead(500, { 'Content-Type': 'text/plain' })
      res.end(`error: ${err.message}\n`)
    }
  })
}).listen(PORT, '127.0.0.1', () => {
  // stderr so it doesn't interfere with stdio MCP transport
  process.stderr.write(`webhook-channel: listening on 127.0.0.1:${PORT}\n`)
})
