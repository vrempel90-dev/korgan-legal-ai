# Railway production release

Current production source branch: `feature/openai-docs-claims`.

Required source HEAD before this trigger: `3ed5f2f9b481367020da28fb13ade59cf601b74b`.

Includes:
- material-law grounding for principal legal demands;
- compact paid-lawyer WhatsApp CTA after generated KORGAN documents;
- reviewable claim-project release hotfix so filing details such as exact court, state duty verification, or omitted unsupported secondary remedies do not by themselves prevent Word delivery;
- strict blocking retained for missing VERIFIED material law, unsafe citations, empty executable requests, and genuinely corrupted legal text;
- startup corpus gate: on a fresh Railway container, verified Adilet corpus must be ready before Telegram polling begins.

This marker commit exists only to force Railway to build the actual current branch HEAD after an older queued deployment became active.
