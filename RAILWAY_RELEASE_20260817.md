# Railway production release

Current production source branch: `feature/openai-docs-claims`.

Required source HEAD before this trigger: `ba8b1147b0436e8339077e6b30d1ec6e5389348a`.

Includes:
- material-law grounding for principal legal demands;
- compact paid-lawyer WhatsApp CTA after generated KORGAN documents;
- reviewable claim-project release hotfix so filing details such as exact court, state duty verification, or omitted unsupported secondary remedies do not by themselves prevent Word delivery;
- strict blocking retained for missing VERIFIED material law, unsafe citations, empty executable requests, and genuinely corrupted legal text;
- startup corpus gate: on a fresh Railway container, verified Adilet corpus must be ready before Telegram polling begins;
- hard claim-to-DOCX route lock: selecting `doc:claim` always enters `universal_claim_waiting`, so the next user facts go to the professional claim DOCX generator and cannot be consumed by consultation.

This marker commit exists only to force Railway to build the actual current branch HEAD.
