# Webhook Receiver

Minimal local receiver for Discord bridge events.

## Start

```bash
cd channels/webhook
npm start
```

Optional port:

```bash
PORT=8791 npm start
```

## Endpoints

- `GET /health` -> service health JSON
- `POST /feature` -> accepts Discord bridge payload and logs it as JSON line