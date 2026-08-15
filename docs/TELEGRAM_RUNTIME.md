# Telegram runtime

Telegram is a transport adapter around the existing `LegalEngine`. Legal rules, RAG verification,
calculations, house-style review and Final Legal QA stay in the core and are not duplicated in
Telegram handlers.

## Runtime mode

The production runtime uses Telegram Bot API long polling (`getUpdates`).

- startup calls `deleteWebhook(drop_pending_updates=false)` because webhooks and `getUpdates` are
  mutually exclusive;
- updates are confirmed with `offset = last_update_id + 1`;
- only `message` and `callback_query` updates are requested;
- the bot processes legal matters only in private chats;
- commands are registered through `setMyCommands`.

## Claim entry paths

The main menu offers two paths into the same legal pipeline:

1. **Describe the case** — the user's text is sent to the existing `LegalEngine`.
2. **Upload documents** — PDF, DOCX, JPG and PNG evidence is converted into source text first, then
   the resulting evidence context is sent to the same `LegalEngine`.

Telegram never resolves law or calculations itself. Both paths still execute Fact Lock -> router ->
Legal RAG/procedural checks -> deterministic calculations -> drafting -> house-style review -> Final
Legal QA.

## Document evidence boundary

Uploaded binary files are processed in memory and are not written into `telegram_sessions`.
Only extracted text enters the encrypted unfinished-case buffer.

- DOCX paragraphs and tables are read locally with `python-docx`;
- PDFs with a usable text layer are read locally with `pypdf`;
- images and scan-only PDFs use a transcription-only OpenAI vision/file request;
- OpenAI Responses requests use `store=false`;
- original Telegram filenames are not inserted into model/case context; each document receives an
  opaque source id (`doc-1`, `doc-2`, ...);
- Fact Lock links facts derived from a document to an `Evidence` object and its `supports_fact_ids`;
- uncertain OCR fragments are explicitly marked and cannot silently become locked facts;
- all material values from visual-only transcription (party identity, identifiers, amounts, dates,
  percentages, document numbers, authority facts) require confirmation unless the identical value
  is independently present in deterministic document text or an explicit user note.

This last rule is deliberately stricter than normal OCR: a scan can help the agent find what to ask
about, but a confident visual transcription error must not silently become a legal fact.

Default limits are controlled by `TELEGRAM_MAX_DOCUMENT_BYTES`,
`TELEGRAM_MAX_DOCUMENT_TEXT_CHARS`, `TELEGRAM_MAX_DOCUMENTS_PER_CASE` and the combined
`TELEGRAM_MAX_CASE_CHARS`.

## Word delivery

After the same Final Legal QA permits release, Telegram sends the draft text and a `.docx` version.
Word export is presentation-only: it preserves the exact released text and any
`NEEDS_VERIFICATION` markers and does not add legal rules, recalculate amounts or repair facts.
Document author/last-modified metadata is blanked.

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
- production startup fails closed if PostgreSQL, OpenAI or `TELEGRAM_SESSION_MASTER_KEY` is missing.

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

The document-capable runtime uses privacy version `2026-08-15-v3` because the policy now explicitly
describes document extraction and scan/image transcription.

### Logging

`configure_logging()` holds `httpx`/`httpcore`/`openai` loggers at `WARNING`. Those libraries log
full request URLs at `INFO`, and the Telegram API URL embeds the bot token. Application logs record
exception *types* and privacy-safe pipeline locations only, never case text or exception payloads.

## Environment

```text
DATABASE_URL=
OPENAI_API_KEY=
KORGAN_MODEL_DOCUMENT=gpt-5-mini
TELEGRAM_BOT_TOKEN=
TELEGRAM_SESSION_MASTER_KEY=
TELEGRAM_PRIVACY_VERSION=2026-08-15-v3
TELEGRAM_POLL_TIMEOUT_SECONDS=30
TELEGRAM_REQUEST_TIMEOUT_SECONDS=45
TELEGRAM_SESSION_TTL_SECONDS=86400
TELEGRAM_MAX_SESSIONS=5000
TELEGRAM_MAX_CASE_CHARS=60000
TELEGRAM_MAX_DOCUMENT_BYTES=10000000
TELEGRAM_MAX_DOCUMENT_TEXT_CHARS=50000
TELEGRAM_MAX_DOCUMENTS_PER_CASE=8
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

The document flow adds two encrypted dialogue states (`awaiting_documents` and
`awaiting_document_clarification`) through migration `20260815_0009`.

## Start

```bash
korgan-telegram
```

The process is intended for one long-polling worker instance per bot token. Do not run two workers
with the same bot token. Horizontal scaling should move Telegram update ingress to a webhook or a
single dedicated ingress service before adding replicas.
