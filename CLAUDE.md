# KORGAN — Claude Code project rules

KORGAN is a production legal service. Treat changes as production engineering, not as throwaway prototyping.

## Mandatory engineering skill

For every task that involves code, debugging, architecture, refactoring, tests, payment, database/state, Telegram runtime, Mini App/API, integrations, CI, Railway, deployment, reliability, performance, or security, use the project skill:

`/korgan-senior-engineer`

The skill contains the required investigate → root-cause → implement → verify → review workflow. Do not bypass its stop conditions or verification gates.

For Kazakhstan legal reasoning, legal drafting, legal-source verification, document QA, or legal workflow changes, also use:

`/korgan-legal-kz`

These skills are complementary: `korgan-senior-engineer` governs engineering quality; `korgan-legal-kz` governs legal quality.

## Evidence over claims

- Do not say a bug is fixed until the relevant behavior is reproduced or verified after the change.
- Do not say tests pass unless the test command actually completed successfully in the current worktree/commit.
- Do not say a deployment is healthy unless the deployed revision and runtime health were actually checked.
- If a check cannot be run, state exactly what remains unverified.

## Safety and repository discipline

- Never expose secrets, tokens, credentials, private keys, connection strings, or user data.
- Never force-push unless the user explicitly requires it and the operation is safe.
- Never discard unrelated user changes.
- Never hide failing tests by deleting, weakening, skipping, or rewriting tests unless the specification itself requires a test change.
- Prefer the smallest coherent fix that removes the root cause and preserves existing contracts.
- Production/deployment mutations require explicit user intent.
