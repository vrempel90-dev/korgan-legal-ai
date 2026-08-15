# Architecture

The runtime pipeline is intentionally sequential for the first release:

1. **Fact & Role Lock** — extracts only user-supplied facts and freezes party roles.
2. **Task Router** — selects one document type and one legal category.
3. **Legal Research & Citation Gateway** — the only path by which an exact legal reference may become `VERIFIED`.
4. **Procedural Check** — jurisdiction, pre-trial procedure, limitation/deadlines, state duty, authority and attachments.
5. **Evidence Map** — links material facts to user-provided evidence and reports gaps.
6. **Calculation Layer** — deterministic arithmetic for money and later time periods.
7. **Drafting Engine** — specialized document workflow; currently debt-recovery claim.
8. **Final Legal QA** — fail-closed policy gate before output.
9. **Output Contract** — document, verification gaps, readiness status and summary.

## RAG direction

The research package is designed for four separate corpora: legislation, approved templates, judicial practice and lawyer corrections. The first commit provides interfaces and fail-closed behavior only; a later corpus implementation should use article/paragraph-level chunks, legal-version metadata and hybrid semantic + keyword retrieval.

Live web search must be restricted to official Kazakhstan sources and acts only as fallback. A live search result must not become canonical automatically.

## LLM boundary

All OpenAI calls are isolated behind `LLMProvider`. Structured extraction uses Pydantic schemas. Tests inject fake providers and therefore need no network access or API key.
