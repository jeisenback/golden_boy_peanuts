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
      'You receive events from a local webhook channel as <channel source="webhook" path="..." ...>.\n\n' +
      'path="/feature": a feature request or task description. Treat it as a direct work item: ' +
      'read the relevant files, implement the change, run tests, and commit. ' +
      'Follow all CLAUDE.md rules (branch, commit format, local_check.sh gate). ' +
      'If the request is ambiguous or requires a hard-stop decision, say so before acting.\n\n' +
      'path="/ci": a CI pipeline event (test failure, check result). Investigate and fix if clear.\n\n' +
      'path="/market": a market or pipeline alert from the energy options agent. Decide if action is needed.\n\n' +
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

    try {
      await mcp.notification({
        method: 'notifications/claude/channel',
        params: { content: body.trim() || '(empty payload)', meta },
      })
      res.writeHead(200, { 'Content-Type': 'text/plain' })
      res.end('ok\n')
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'text/plain' })
      res.end(`error: ${err.message}\n`)
    }
  })
}).listen(PORT, '127.0.0.1', () => {
  // stderr so it doesn't interfere with stdio MCP transport
  process.stderr.write(`webhook-channel: listening on 127.0.0.1:${PORT}\n`)
})
