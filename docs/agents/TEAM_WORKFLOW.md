# KORGAN AI Team Workflow

## Goal

Use Codex as the implementation engine and Claude as independent, token-efficient review. Do not run three agents against the same code simultaneously. Sequential review is safer, cheaper in context, and avoids conflicting edits.

## One production branch

Work on a feature/production-hardening branch, never directly on `main`.

Recommended local setup after this configuration branch is merged:

```powershell
git checkout main
git pull
git checkout -b ai/korgan-production-hardening
```

## Cycle A — Codex implements one atomic task

Start Codex from the repository root:

```powershell
codex
```

Give it:

```text
Follow AGENTS.md. Pick the highest-priority unresolved P0 task. Work on exactly one atomic root cause. Implement it, add regression tests, run the relevant tests, update docs/agent-state/STATUS.md, then stop for independent review. Do not push or deploy.
```

The Codex handoff in `STATUS.md` is deliberately short so reviewers do not need to reconstruct the entire task from repository history.

## Cycle B — Claude Architect review

Start Claude Code in the same working tree only after Codex has stopped editing:

```powershell
claude
```

Give it:

```text
Follow CLAUDE.md and docs/agents/CLAUDE_ARCHITECT.md. Review only the current Codex change described in docs/agent-state/STATUS.md and the current diff. Write only material BLOCKER/P0/P1 findings to docs/agent-state/REVIEW.md. Do not edit production code. Stop when the scoped review is complete.
```

If verdict is `CHANGES_REQUIRED`, return to Codex and tell it to validate/fix the findings. If `PASS`, proceed to legal review when the change affects legal behaviour.

## Cycle C — Claude Legal Red Team

Use this review only for changes that can affect legal reasoning, evidence handling, research, consultation, calculations, document generation, validation, RU/KK meaning, or formal output.

Give Claude:

```text
Follow CLAUDE.md and docs/agents/CLAUDE_LEGAL_RED_TEAM.md. Review only the current Codex change described in docs/agent-state/STATUS.md and the current diff. Attack the highest-risk legal failure paths touched by this change. Use only the specific KORGAN legal-skill modules needed for those paths. Write only material BLOCKER/P0/P1 findings to docs/agent-state/REVIEW.md. Do not edit production code. Stop when the scoped review is complete.
```

For purely infrastructure or non-legal changes, skip this cycle unless there is a credible legal-output impact.

## Cycle D — Codex fixes validated findings

Give Codex:

```text
Read docs/agent-state/REVIEW.md. Validate every finding against the code; do not accept it blindly. Fix confirmed BLOCKER/P0/P1 findings with the smallest coherent changes, add regression tests, run relevant tests, update STATUS.md, then stop for re-review.
```

Repeat until relevant reviewers return PASS.

## Token-control rules

Claude review sessions should normally consume context only for:

- STATUS.md;
- the current diff;
- changed symbols and direct dependencies;
- focused tests;
- a specific legal skill/reference module only when legally necessary.

Avoid full-tree scans, recursive reading of `.claude/skills/korgan-legal-kz/reference/`, repeated README reading, duplicate implementation proposals, cosmetic review, and subagents for ordinary review.

A clean review should end quickly rather than continue searching for low-value issues.

## Two Claude subscriptions

Use the two Claude subscriptions as independent review capacity, not as a mechanism for duplicating the same review. One account can perform architecture/production review and the other legal red-team review. The workflow does not require them to run simultaneously.

Authentication/account switching is intentionally not automated by this repository configuration; use the supported Claude Code sign-in/session method available on the machine.

## Acceptance gate

Do not merge a production-hardening change while a relevant review has unresolved BLOCKER or P0 findings. P1 may be deferred only when the remaining risk is explicit and acceptable for the intended release stage.
