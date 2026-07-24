# dlq-pilot

Triage and replay RabbitMQ dead-letter queues from a dashboard that groups failures by **cause**, not just by queue — because 500 dead letters are usually 3 bugs, not 500 problems.

![dlq-pilot dashboard](assets/dashboard.png)

## Why this exists

When a consumer breaks, dead letters pile up fast. RabbitMQ's management UI shows you *counts*; existing open-source tooling ([amqp-replay](https://github.com/FGRibreau/amqp-replay)) replays blindly from the CLI; the tools that actually help you *understand* failures (RabbitGUI, QueueForge) are commercial. dlq-pilot is the missing open-source middle: fingerprint the failure causes, inspect the evidence, fix your consumer, then replay one cause at a time — rate-limited, dry-run first, with an audit trail.

## Tech stack

- **Backend**: Python / FastAPI, aio-pika (AMQP), httpx (RabbitMQ management API), SQLite (audit log)
- **Frontend**: React 18 + TypeScript + Vite, hand-rolled CSS (no UI framework)
- **Demo/chaos harness**: Docker Compose — RabbitMQ 3.13 + a chaos producer + deliberately broken consumers

## Architecture

```
                    ┌────────────────────────────────────────────┐
                    │  FastAPI                                   │
  React dashboard ──┤  /api/queues /groups /messages /replay     │
                    │      │                                     │
                    │  fingerprint engine ── audit log (SQLite)  │
                    │      │                                     │
                    │  BrokerAdapter (protocol)                  │
                    └──────┬──────────────────────┬──────────────┘
                           │                      │
                    DemoAdapter            RabbitMQAdapter
                 (in-process, seeded)   (mgmt API + AMQP basic.get)
```

- **Fingerprint engine** — collapses dead letters into failure groups keyed on `(x-death reason, origin queue, normalized error signature)`. Normalization strips ids/uuids/hex so `"order 8231 missing 'amount'"` and `"order 9107 missing 'amount'"` land in the same group.
- **Broker adapters** — the dashboard only talks to a small `BrokerAdapter` protocol. `DemoAdapter` is an in-process broker seeded with realistic failures so the app runs with **zero infrastructure**; `RabbitMQAdapter` discovers DLQs via the management API and peeks/replays over AMQP.
- **Replay service** — adapter-agnostic: fingerprint-scoped selection, per-second rate limiting, dry-run by default, and every run (dry or real) lands in the SQLite audit log. Replay is honest about at-least-once semantics: messages that hit a still-broken consumer come straight back, and the UI shows the bounce count.

## Key features

- **Failure grouping**: thousands of dead letters collapse into a handful of named causes, sorted by impact
- **Surgical replay**: replay one failure group (not the whole queue), capped and rate-limited, after a dry run
- **Message inspector**: payload, headers, and the full `x-death` chain per message
- **Audit log**: who replayed what, when, and how much of it bounced back
- **Demo mode**: run the entire dashboard with no RabbitMQ, no Docker — `uvicorn` and go

## Quickstart (demo mode, zero setup)

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows paths; use bin/ on unix
uvicorn app.main:app --port 8000
# open http://localhost:8000  (frontend is pre-built and served by FastAPI)
```

To hack on the frontend: `cd frontend && npm install && npm run dev` (Vite proxies `/api` to :8000).

## Real broker mode

```bash
cd demo && docker compose up -d          # RabbitMQ + chaos producer + broken consumers
RABBITMQ_URL=amqp://guest:guest@localhost:5672/ uvicorn app.main:app --port 8000
```

The chaos harness produces orders (half missing a required field), payments (a "gateway" that times out 60% of the time), and notifications that TTL-expire — so the DLQs fill up with realistically messy failures within a minute.

Config (env vars): `RABBITMQ_URL`, `RABBITMQ_MGMT_URL`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD`, `DLQ_PATTERN` (regex for what counts as a DLQ, default `(\.dlq$|\.dlx$|dead)`), `DEMO_RESEED_HOURS` (demo mode only — hours between automatic re-seeds of the sample dead letters so a shared/public sandbox never drains to empty; default `6`, `0` disables).

**Caveats worth knowing** (this is a triage tool, not magic): peeking over AMQP is `basic.get` + requeue, which briefly holds messages and resets delivery order; replay identity-matches by message id with payload fallback, so setups without message ids fall back to payload equality. There is no auth in v1 — run it next to the broker, not on the internet.

## Testing

```bash
cd backend && .venv/Scripts/python -m pytest
```

14 tests cover the fingerprint engine (normalization, header/payload signature extraction, group separation) and the full API flow in demo mode (grouping, filtering, dry-run invariance, replay draining with bounce-back accounting, validation, audit, and the demo re-seed). The RabbitMQ adapter is exercised by the Docker chaos harness rather than unit tests.

## Why I built this

I've spent years around message queues and incident response (payments infra at Razorpay, distributed config systems before that), and DLQ triage was always the same manual grind: page through opaque messages, guess at the cause, replay and pray. This is the tool I wanted on call — built to be runnable by anyone in under a minute, in demo mode, with zero infrastructure.
