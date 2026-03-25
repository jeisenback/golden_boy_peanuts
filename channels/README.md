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

## Read-only Repo Tools
- `tool prs`: list open pull requests with `gh pr list`
- `tool status`: show `git status --short --branch`
- `tool branches`: show current and local branches
- `tool read <path>`: read a file inside the repo
- `tool search <pattern>`: search repo text with `rg`
- Natural open-PR phrasing is also supported, for example `Any open PRs?`

This is a safe read-only repo tool layer in the webhook responder. It is not the full VS Code Copilot toolset.

## Curated Workflow Commands
- `tool workflow`: list curated workflow commands
- `tool pr <number>`: show details for a specific pull request
- `tool issue <number>`: show details for a specific issue
- `tool ci`: show recent GitHub Actions workflow runs
- `tool ci failed`: show recent failing workflow runs
- `tool digest`: show compact open-PR, CI, and change summary
- `tool ship prep`: show pre-ship report (status + diff + CI)
- `tool log`: show recent commits (`git log --oneline -10`)
- `tool diff`: show unstaged diff summary (`git diff --stat`)
- `tool test <target>`: run pytest for a specific target

Examples:
- `tool pr 188`
- `tool issue 170`
- `tool test tests/core/test_discord_copilot_responder.py`

## Guarded Write Commands
- `tool write help`: show available guarded write actions
- `tool branch create <name>`: prepare branch creation
- `tool pr comment <number> <text>`: prepare PR comment
- `tool issue label add <number> <label1,label2>`: prepare issue label update

Write commands do not execute immediately. The bot returns a short-lived confirmation token.
To execute, send `tool confirm <token>` from the same user and channel within 10 minutes.

### Write Policy Controls
- `DISCORD_WRITE_ALLOWED_USERS` (comma-separated Discord user IDs)
- `DISCORD_WRITE_ALLOWED_PROJECTS` (comma-separated project keys)
- Optional policy file: `channels/webhook/.data/policy.json`

When these controls are set, write actions are denied unless policy permits them.
