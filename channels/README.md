# Discord Channel Bridge

This repository is wired for the Discord-to-webhook bridge pattern.

## Topology
- Discord bot process receives messages and forwards to local webhook endpoint.
- Webhook process invokes copilot_responder.py and posts callback responses.
- In shared mode, one central Discord router can serve many repos.

## This Repo Ports
- Webhook port: (see channels/webhook/.env)
- Discord response server port: (see channels/discord/.env)

## Required Environment
- channels/discord/.env
  - DISCORD_BOT_TOKEN
  - DISCORD_ALLOWED_USERS (optional)
  - RESPONSE_SERVER_PORT
- channels/webhook/.env
  - PORT
  - ANTHROPIC_API_KEY
  - DISCORD_RESPONDER_PYTHON

## Install
1. In channels/discord: npm install
2. In channels/webhook: npm install

## Run
1. Start webhook: cd C:/tools/golden_boy_peanuts/channels/webhook && npm start
2. Start local Discord bot (optional if central router is used): cd C:/tools/golden_boy_peanuts/channels/discord && npm start

## Recommended Multi-Repo Mode
- Use central router in C:\tools\discord_router.
- Run one webhook per repo.
- Route by channel name or channel ID via router routes.json.

## Notes
- One Discord bot token can serve all channels and repos.
- You do not need one bot per channel.
- Keep secrets in .env files; do not commit them.
