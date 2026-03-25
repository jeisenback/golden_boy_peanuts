# Discord Bridge

Routes Discord messages to local project webhook ports.

## What it does

- Listens for Discord messages in guild channels and DMs.
- Resolves a target project using channel mapping or `project: message` prefix.
- Supports thread-based sessions with per-session repo routing and approval mode.
- Sends message payloads to `http://127.0.0.1:<port>/feature`.

## Setup

1. Copy `.env.example` to `.env` and set `DISCORD_BOT_TOKEN`.
2. Install dependencies:

```bash
cd channels/discord
npm install
```

3. Start the bridge:

```bash
npm start
```

## Routes

Edit `routes.json`:

```json
{
  "default": { "port": 8788 },
  "projects": {
    "acme": { "port": 8791, "channelNames": ["acme-dev"] }
  }
}
```

If a DM starts with `acme:`, it routes to `acme`.

## Session commands

Run these in Discord:

- `cp new <name>`: create a thread session from a channel message.
- `cp repo <project>`: set session route to a `routes.json` project key (`default` fallback).
- `cp approve ask|always`: require per-message approval via reactions (`ask`) or auto-forward (`always`).
- `cp session`: show current session settings.
- `cp maintenance status|on|off`: check/toggle maintenance mode (restricted to maintenance admins).

When approval mode is `ask`, each message posts an approval prompt. The same sender must react:

- `👍` approve and forward to webhook
- `👎` deny

Approval prompts expire automatically (default: 15 minutes).

Thread sessions expire automatically after inactivity (default: 24 hours).

## Environment options

- `SESSION_TTL_HOURS` (default `24`): idle thread-session expiry.
- `APPROVAL_TTL_MINUTES` (default `15`): approval prompt expiry.
- `MAINTENANCE_MODE` (default `false`): pause non-admin requests.
- `MAINTENANCE_ALLOW_USERS`: comma-separated Discord IDs allowed to toggle/override maintenance mode.
- `MAINTENANCE_MESSAGE`: response text when requests are blocked by maintenance mode.
- `AUDIT_LOG_FILE` (default `channels/discord/.data/audit.log.jsonl`): newline-delimited JSON audit log.

## Audit log

The bridge writes JSONL audit records for key events including:

- session create/expire
- approval requested/approved/denied/expired
- webhook forward success/failure
- maintenance mode toggles and blocked messages

## Payload

POST body to `/feature` looks like:

```json
{
  "author": { "id": "...", "username": "..." },
  "project": "acme",
  "channelId": "...",
  "channelName": "acme-dev",
  "content": "message text",
  "attachments": [],
  "session": {
    "threadId": "...",
    "approve": "ask",
    "ownerUserId": "..."
  }
}
```