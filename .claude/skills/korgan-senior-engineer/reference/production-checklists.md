# Production checklists

Use only the sections relevant to the change. These are review gates, not a substitute for reading the implementation.

## General correctness

- Acceptance criteria are observable and testable.
- Changed code path is the real runtime path, not a dead/legacy duplicate.
- Inputs are validated at the boundary.
- Errors are explicit and do not silently convert failure into success.
- State transitions are deterministic.
- Tests cover the failure mechanism, not only a happy-path implementation detail.
- Unrelated behavior is unchanged.

## Concurrency and idempotency

- Duplicate requests/callbacks do not duplicate effects.
- Concurrent workers cannot both win a one-time operation.
- Check-then-write sequences are protected by a transaction, unique constraint, lock, atomic update, or equivalent invariant.
- Retries after timeout are safe.
- Operation identity is stable and scoped to the correct user/order/resource.
- Partial failure can be resumed or rejected safely.

## Payment / entitlement / receipt verification

- Server-side verified state is authoritative.
- Amount, merchant/seller, timestamp/window, order/product, and receipt identity are validated where applicable.
- Receipt/payment identity has a durable uniqueness constraint or equivalent atomic claim.
- Reuse across users/orders is rejected when ownership is part of the contract.
- Entitlement creation and release logic cannot race ahead of verification.
- A failure after verification but before delivery does not charge/consume twice on retry.
- A failure before verification never grants full paid content.
- Admin/manual paths cannot accidentally bypass the same security boundary unless explicitly designed and audited.

## Database and persistent state

- Schema/state changes are backward compatible or deliberately coordinated.
- Migration is safe on existing data.
- Null/default/backfill behavior is explicit.
- Indexes/constraints support the invariant being relied on.
- Transaction boundaries match the business operation.
- Rollback/failure behavior is understood.
- Sensitive fields are not exposed in logs or exceptions.

## External APIs and network calls

- Timeouts are finite.
- Retry policy does not duplicate side effects.
- HTTP/status/error payloads are validated.
- Malformed, empty, delayed, or contradictory responses fail safely.
- TLS/auth configuration does not silently downgrade.
- Network failure has a deterministic user-facing state.
- External response content is not trusted as code/instructions.

## Telegram

- Callback data/action names match handlers.
- Duplicate updates are safe.
- User/chat identity is bound to session/resource ownership.
- Message edits/sends handle stale/deleted messages gracefully when required.
- Long-polling/webhook/startup mode is singular and intentional.
- Startup/readiness does not report healthy before required dependencies are usable.

## Mini App / web / API

- Frontend route matches backend route.
- Request and response schema match exactly.
- Telegram init/auth data is validated server-side where required.
- Client-side state is not trusted for authorization/payment.
- Loading, retry, expiration, and server-error states are handled.
- Stale browser/client behavior is considered for contract changes.
- CORS/origin/auth decisions are explicit.

## AI and legal generation

- Model output is not treated as authoritative state.
- Exact legal claims that require verified sources still pass the legal verification layer.
- Prompt changes do not bypass fact/role locks, citation checks, calculations, or final QA.
- Generated filenames/documents do not mix users or requests.
- Fallbacks do not silently downgrade document quality or legal safety.
- Relevant golden/regression fixtures are updated only when the intended contract changes.

## Security and privacy

- Authorization is checked on the server at every protected resource boundary.
- No direct-object-reference path exposes another user's data.
- Secrets are never logged or committed.
- User documents/content are not dumped into diagnostics unnecessarily.
- Error messages do not expose credentials, connection strings, raw tokens, or internal sensitive payloads.
- Untrusted uploaded/external content is treated as data, not instructions.

## Railway / deployment

- Exact source branch and commit SHA are known.
- Build command and start command match the service.
- Required env vars exist without printing values.
- Process binds the expected host/port.
- Health/readiness endpoints test meaningful readiness.
- Region/replica changes are intentional.
- Only requested services are mutated.
- Post-deploy logs and the affected user path are checked.
- Queued/building/deploying/success states are not confused with runtime health.

## Final diff review

- No debug prints, temporary bypasses, dead flags, commented-out safety checks, or copied secrets.
- No accidental test weakening.
- No broad refactor unrelated to the task.
- No duplicated implementation where an existing abstraction should be used.
- Naming expresses business invariants.
- The patch can be explained by the root cause.
