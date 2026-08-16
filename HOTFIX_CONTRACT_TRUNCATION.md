# Contract truncation hotfix

Root cause observed in Railway on 2026-08-16: strict JSON contract responses were cut at the configured output-token ceiling (5,200 tokens, then 6,200 on retry), producing `JSONDecodeError: Unterminated string` before QA or DOCX rendering.

The runtime now gives contract research/draft/repair enough output budget to complete structured JSON, logs API incomplete status/reason, keeps contract prose concise, and retries only when the JSON is actually incomplete.
