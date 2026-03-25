# Discord Bridge Hardening Checklist

Use this checklist before exposing the bridge to any shared Discord server.

## Identity and Access

- Restrict command senders with `DISCORD_ALLOWED_USERS` to specific operator user IDs.
- Use a dedicated bot account, never a personal account token.
- In Discord Developer Portal, disable unnecessary privileged intents and grant only required scopes.
- Limit bot permissions per channel (read/send/thread/reaction only; avoid admin permissions).

## Session and Approval Controls

- Keep per-thread approval mode at `ask` for production channels.
- Use `cp approve always` only for tightly controlled private channels.
- Treat approval prompts as an explicit gate for outbound actions.
- Periodically prune stale session files in `channels/discord/.data/sessions.json`.

## Secrets and Configuration

- Store `DISCORD_BOT_TOKEN` in environment/secret manager, not in git.
- Keep `.env` out of source control; commit only `.env.example`.
- Rotate bot token immediately if logs or screenshots may have exposed it.
- Pin `ROUTES_FILE` and `DATA_DIR` to expected paths.

## Network and Runtime

- Keep webhook listener bound to loopback (`127.0.0.1`) unless a reverse proxy is required.
- If remote access is required, add TLS termination and IP allowlisting at the proxy.
- Run bridge/webhook under a non-admin OS account.
- Use a process supervisor (systemd/pm2/docker restart policy) and health checks.

## Input and Content Safety

- Treat all Discord message content and attachment URLs as untrusted input.
- Validate payload schema on webhook receiver before invoking downstream tools.
- Enforce size limits for message content and attachment metadata.
- Reject or redact obvious secrets before forwarding content downstream.

## Logging and Audit

- Log sender ID, channel/thread ID, route key, and approval decision for each action.
- Do not log tokens, cookies, or full sensitive prompts.
- Keep retention policy for logs and purge old files regularly.
- Create an incident playbook: token rotation, user removal, route disable switch.

## Dependency and Supply Chain

- Keep `discord.js` and runtime dependencies updated on a regular cadence.
- Run `npm audit` and review critical findings before deployment.
- Use lockfiles and reproducible installs (`npm ci` in CI).
- Review any new dependency before adding it to the bridge.

## Operational Guardrails

- Define approved repos/projects in `routes.json` and remove unused routes.
- Prefer separate webhook ports per project/environment.
- Add maintenance mode capability to reject new messages during incidents.
- Test deny-path behavior (`👎`) and webhook-failure behavior before go-live.
