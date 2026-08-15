# Telegram runtime

Telegram is a transport adapter around the existing `LegalEngine`. Legal rules, RAG verification,
calculations and Final Legal QA stay in the core and are not duplicated in Telegram handlers.

## Runtime mode

The first production runtime uses Telegram Bot API long polling (`getUpdates`).

- startup calls `deleteWebhook(drop_pending_updates=false)` because webhooks and `getUpdates` are
  mutually exclusive;
- updates are confirmed with `offset = last_update_id + 1`;
- only `message` and `callback_query` updates are requested;
- the bot processes legal matters only in private chats;
- commands are registered through `setMyCommands`.

## Privacy boundary

The Telegram session store is intentionally in-memory for this phase. It stores language,
consent state and an unfinished case buffer. The case buffer is cleared on successful completion,
`/cancel`, refusal of consent or session expiry. It is not written to the legal corpus database.

This is not a durable production session store. Before horizontal scaling or persistent sessions,
introduce a separately reviewed encrypted session repository. Do not reuse the canonical legal
corpus tables for user case data.

## Environment

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_PRIVACY_VERSION=2026-08-15
TELEGRAM_POLL_TIMEOUT_SECONDS=30
TELEGRAM_REQUEST_TIMEOUT_SECONDS=45
TELEGRAM_SESSION_TTL_SECONDS=86400
TELEGRAM_MAX_SESSIONS=5000
TELEGRAM_MAX_CASE_CHARS=16000
```

`TELEGRAM_BOT_TOKEN` is secret and must be provided only through environment/secrets.

## Start

```bash
korgan-telegram
```

The process is suitable for a single Railway worker instance. Do not run two long-polling
instances with the same bot token. Horizontal scaling should move the transport to a webhook or a
single update-ingress service before adding replicas.
