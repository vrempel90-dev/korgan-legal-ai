# KORGAN Mini App v5 parity

This release is isolated to the dedicated Mini App branch and Railway services.

- AI legal core: current `feature/openai-docs-claims` runtime, reused without modifying the agent service.
- Documents: claim, contract, response to claim, pretrial claim, response to pretrial claim.
- Consultations and uploads: same current production legal service chain and strict source/quality layers.
- Document payments: automatic AI receipt verification, configured recipient, current-order timestamp validation, anti-replay, fail-closed storage, immediate paid generation, retry without another payment after a post-payment generation failure.
- Manual Mini App admin payment confirmation: disabled in API v5.
- Telegram AI-agent deployment: not part of this release.
