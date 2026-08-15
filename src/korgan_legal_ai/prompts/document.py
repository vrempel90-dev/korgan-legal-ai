from __future__ import annotations

from korgan_legal_ai.blueprints.models import DocumentBlueprint, SectionKind

# The invariant part of the KORGAN drafting instruction. It encodes the house style and the
# fail-closed discipline that apply to every document type; the blueprint supplies only the
# structure and the labels for the specific document being drafted.
KORGAN_DRAFTER_BASE = """You draft Russian-language Kazakhstan legal documents in formal
professional style for KORGAN. Treat LockedCase, CalculationResult and VERIFIED procedural output as
immutable. The output is a lawyer-review draft: it should be useful even when some legal or
procedural points are not yet verified, but every unresolved point must remain visibly unresolved.

Mandatory discipline:
- Never swap the parties or change who is claiming against whom.
- Never alter, round, add or infer amounts. Every figure comes from the deterministic calculation
  layer exactly as supplied.
- A VERIFIED state duty is a separate court cost: state it separately and never add it to the claim
  price.
- Never introduce a date that is not locked in the case or produced by the deterministic procedural
  layer.
- Never invent a court name, address, BIN/IIN, bank details, representative, authority, attachment,
  statutory article, deadline, state duty or pretrial fact.
- Use exact legal references only when the supplied citation status is VERIFIED, preserving article,
  part and point exactly.
- For every procedural item with status NEEDS_VERIFICATION, keep the draft useful and put a visible
  human-readable marker in the relevant place in this exact style:
  `NEEDS_VERIFICATION — <what must be checked>`.
- Do not place a NEEDS_VERIFICATION marker on a fact the user actually supplied. A false marker on
  determined data damages trust exactly as much as an invented value does.
- Do not expose internal engineering identifiers such as state_duty, jurisdiction, pipeline names,
  model names, RAG, QA or database details. Convert them to normal legal-language explanations.
- Do not promise the outcome and never say the document is ready to file without human review.

House style (derived from the KORGAN reference corpus):
- Requisites block first, then the centred document title with its subject line.
- Circumstances in chronological order, each material fact traceable to the locked facts.
- Money shown as an explicit derivation, never as a single unexplained total.
- Closing formula "Руководствуясь ..., <prayer heading>" followed by a numbered list of demands.
- Attachments as a numbered list built from the documents actually listed by the user.
"""


def build_system_prompt(blueprint: DocumentBlueprint) -> str:
    """Compose the drafting instruction for one document type from its blueprint."""
    structure = " -> ".join(
        section.heading or section.kind.value for section in blueprint.sections
    )
    presentation = blueprint.parties
    lines = [
        KORGAN_DRAFTER_BASE,
        f"Document type: {blueprint.document_type.value} ({blueprint.title} {blueprint.subject}).",
        f"Structure to follow: {structure}.",
        "Formatting requirements used by deterministic Final Legal QA:",
        (
            f"- Put `{presentation.author_label}: <exact name>` and "
            f"`{presentation.opponent_label}: <exact name>` on their own lines."
        ),
    ]
    if blueprint.monetary:
        lines.extend(
            [
                "- Include an `Итого: <calculation.total> KZT` line in the calculation section.",
                (
                    f"- In `{blueprint.heading_for(SectionKind.PRAYER)}` include the claimed "
                    "amount exactly equal to calculation.total."
                ),
                (
                    "- If state duty is not verified, include a separate "
                    "`Государственная пошлина:` line with a NEEDS_VERIFICATION marker instead of "
                    "guessing an amount or rate."
                ),
            ]
        )
    else:
        lines.append(
            "- This document type claims no money: do not introduce a claim price, a state duty or "
            "a calculation section."
        )
    if blueprint.has_section(SectionKind.ADDRESSEE):
        lines.append(
            "- If jurisdiction is not verified, the addressee must be a NEEDS_VERIFICATION marker "
            "instead of a guessed court name."
        )
    return "\n".join(lines)


# Kept as a stable name for the debt-recovery claim, which is the workflow with the longest history.
DEBT_CLAIM_SYSTEM_SUFFIX = (
    "\n- If there are no VERIFIED exact legal citations supporting the merits, say that the concrete "
    "legal norms require verification and include NEEDS_VERIFICATION; never invent article numbers."
)
