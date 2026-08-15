# Telegram runtime

Telegram is a transport adapter around the existing `LegalEngine`. Legal rules, RAG verification,
calculations and Final Legal QA stay in the core and are not duplicated in Telegram handlers.

## Runtime mode

The production runtime uses Telegram Bot API long polling (`getUpdates`).

- startup calls `deleteWebhook(drop_pending_updates=false)` because webhooks and `getUpdates` are
  mutually exclusive;
- updates are confirmed with `offset = last_update_id + 1`;
- only `message` and `callback_query` updates are requested;
- the bot processes legal matters only in private chats;
- commands are registered through `setMyCommands`.

## Secure session storage

Production Telegram sessions are stored in PostgreSQL in the separate `telegram_sessions` table.
The canonical legal corpus tables are never reused for client case data.

- the raw Telegram user ID is not stored; the primary key is an HMAC-SHA256 pseudonym;
- the unfinished case buffer is encrypted with AES-256-GCM;
- the AES key and HMAC key are independently derived from one random root secret with HKDF-SHA256;
- the subject pseudonym is bound as AES-GCM associated data;
- a fresh random nonce is generated for every write; ciphertext is never updated in place;
- case ciphertext is removed after successful completion, `/cancel`, or a safe terminal failure;
- refusal of consent deletes the whole session row;
- expired sessions are deleted according to `TELEGRAM_SESSION_TTL_SECONDS`, and `TELEGRAM_MAX_SESSIONS`
  bounds the table when new subjects arrive faster than expiry removes them;
- reading state never creates a row, so a contact who never acted leaves no stored record;
- production startup fails closed if PostgreSQL or `TELEGRAM_SESSION_MASTER_KEY` is missing.

The in-memory store remains available only as an explicit development/test backend. The runtime has
no default backend at all: the store is always passed in, so a misconfigured deployment cannot
quietly downgrade to process memory.

### Unreadable stored state

Ciphertext that fails AES-GCM verification — tampering, corruption, or a rotated
`TELEGRAM_SESSION_MASTER_KEY` — is never repaired or partially trusted. The affected row is deleted,
the user restarts from the consent screen, and the legal engine is not invoked. Because an
unhandled update would otherwise be redelivered by Telegram forever and stall every other user, the
polling loop confirms the offset even when handling an update fails.

Rotating `TELEGRAM_SESSION_MASTER_KEY` rotates the HMAC branch as well, so existing rows become
unreadable *and* unaddressable under the new pseudonyms. They are inert, but they linger until TTL
expiry, so rotation must be followed by an explicit purge:

```sql
TRUNCATE telegram_sessions;
```

### Consent

Changing the data-handling policy requires changing `TELEGRAM_PRIVACY_VERSION`, which forces users
to accept the current policy before a legal request can be processed. Consent to a superseded
version does not keep holding data: the unfinished case buffer is erased when the stored consent no
longer matches the running privacy version.

### Logging

`configure_logging()` holds `httpx`/`httpcore`/`openai` loggers at `WARNING`. Those libraries log
full request URLs at `INFO`, and the Telegram API URL embeds the bot token. Application logs record
exception *types* only, never case text or exception payloads.

## Environment

```text
DATABASE_URL=
OPENAI_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_SESSION_MASTER_KEY=
TELEGRAM_PRIVACY_VERSION=2026-08-15-v2
TELEGRAM_POLL_TIMEOUT_SECONDS=30
TELEGRAM_REQUEST_TIMEOUT_SECONDS=45
TELEGRAM_SESSION_TTL_SECONDS=86400
TELEGRAM_MAX_SESSIONS=5000
TELEGRAM_MAX_CASE_CHARS=16000
```

`TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, and `TELEGRAM_SESSION_MASTER_KEY` are secrets and must be
provided only through the deployment secret/environment store.

Generate the session root key as 32 random bytes and store its Base64 representation in
`TELEGRAM_SESSION_MASTER_KEY`. Never commit the real value to the repository.

## Database migration

Before starting the Telegram worker, apply migrations:

```bash
alembic upgrade head
```

## Start

```bash
korgan-telegram
```

The process is intended for one long-polling worker instance per bot token. Do not run two workers
with the same bot token. Horizontal scaling should move Telegram update ingress to a webhook or a
single dedicated ingress service before adding replicas.
