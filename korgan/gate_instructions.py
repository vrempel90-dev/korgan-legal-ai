"""Classify a reply before parsing it, and act on instructions about defects.

When the release gate blocks a document it tells the user what is wrong and what
is permissible — «допустимо указать только номер статьи и пометить
NEEDS_VERIFICATION». The user then says exactly that back: «пометь статью 616
ГК РК как NEEDS_VERIFICATION и продолжи». That is an instruction about a defect
the bot itself raised, not case data, and running it through the field parser
produced «не получилось распознать ни одно из запрошенных полей» — a message
that reads as *you wrote nothing*, when the user wrote a clear command.

Hence the ordering rule this module exists to enforce: classify the message
first, choose a parser second. A reply on this step can be case data, an
instruction about a listed defect, or something else entirely, and each needs a
different answer — including "I did not understand, say more" instead of a
template about missing fields.

`apply_citation_waiver` performs the instruction the gate itself suggested: the
document stops asserting what the provision says, keeps the article number, and
carries a visible verification marker. That is a downgrade of the claim being
made, never a bypass of the check — the audit re-runs afterwards and the
document goes out marked, or not at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from korgan.citation_audit import ProvisionReference, extract_references
from korgan.text_integrity import unbalanced_quotes

_QUOTE_RE = re.compile(r"[«\"]([^«»\"]{25,})[»\"]")

_ACCEPT_MARKERS = (
    r"needs[\s_]*verification",
    r"помет(?:ь|ить|им|ьте)",
    r"оставь|оставить|оставьте",
    r"согласен|согласна|согласны",
    r"без\s+подтвержден",
    r"как\s+непроверенн",
)
_CONTINUE_MARKERS = (
    r"продолж(?:ай|и|ить|айте)",
    r"сформируй|сформировать|сформируйте",
    r"готовь|подготовь|выдай|выпусти",
    r"давай\s+дальше",
    r"всё\s+равно|все\s+равно",
)
_DROP_MARKERS = (
    r"убер(?:и|ите|ать)",
    r"удал(?:и|ите|ить)",
    r"исключ(?:и|ите|ить)",
    r"не\s+ссылайся|без\s+(?:этой\s+)?стать",
)
_QUESTION_MARKERS = (r"\?", r"^почему", r"^что\s", r"^как\s", r"^зачем")

# Instructions are prose. A message that is mostly «Поле: значение» is data.
_FIELD_LINE_RE = re.compile(r"^\s*[А-ЯЁA-Z][^:\n]{3,60}:\s*\S")


class ReplyIntent(StrEnum):
    FIELD_DATA = "FIELD_DATA"
    ACCEPT_NEEDS_VERIFICATION = "ACCEPT_NEEDS_VERIFICATION"
    DROP_PROVISION = "DROP_PROVISION"
    QUESTION = "QUESTION"
    UNCLEAR = "UNCLEAR"


@dataclass(slots=True)
class ReplyClassification:
    intent: ReplyIntent
    targets: list[ProvisionReference] = field(default_factory=list)
    unknown_targets: list[ProvisionReference] = field(default_factory=list)
    applies_to_all: bool = False

    @property
    def is_instruction(self) -> bool:
        return self.intent in {ReplyIntent.ACCEPT_NEEDS_VERIFICATION, ReplyIntent.DROP_PROVISION}


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE | re.MULTILINE) for pattern in patterns)


def _looks_like_field_data(text: str) -> bool:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return False
    labelled = sum(1 for line in lines if _FIELD_LINE_RE.match(line))
    return labelled >= max(1, len(lines) // 2)


def classify_reply(
    text: str,
    *,
    gate_issues: list[str] | None = None,
    pending_fields: list[str] | None = None,
) -> ReplyClassification:
    """Decide what kind of message this is before any parser touches it."""
    raw = (text or "").strip()
    if not raw:
        return ReplyClassification(ReplyIntent.UNCLEAR)

    issue_refs: list[ProvisionReference] = []
    for issue in gate_issues or []:
        for reference in extract_references(issue):
            if reference not in issue_refs:
                issue_refs.append(reference)

    mentioned = extract_references(raw)
    known = [ref for ref in mentioned if any(ref.matches(other) for other in issue_refs)]
    unknown = [ref for ref in mentioned if ref not in known]

    accepts = _matches_any(raw, _ACCEPT_MARKERS)
    continues = _matches_any(raw, _CONTINUE_MARKERS)
    drops = _matches_any(raw, _DROP_MARKERS)

    if drops and (known or unknown):
        return ReplyClassification(ReplyIntent.DROP_PROVISION, known, unknown)

    if accepts or continues:
        # «продолжай» with no article named means "apply this to everything you
        # listed" — the gate offered the downgrade, the user is taking it.
        applies_to_all = bool(continues and not mentioned)
        targets = known or (issue_refs if applies_to_all else [])
        if targets or applies_to_all:
            return ReplyClassification(
                ReplyIntent.ACCEPT_NEEDS_VERIFICATION, targets, unknown, applies_to_all
            )
        if unknown:
            return ReplyClassification(ReplyIntent.ACCEPT_NEEDS_VERIFICATION, [], unknown)

    if _looks_like_field_data(raw):
        return ReplyClassification(ReplyIntent.FIELD_DATA)

    if _matches_any(raw, _QUESTION_MARKERS):
        return ReplyClassification(ReplyIntent.QUESTION)

    if pending_fields:
        # On the field-collection step an unremarkable message is most likely an
        # answer; the field parser will say so precisely if it is not.
        return ReplyClassification(ReplyIntent.FIELD_DATA)

    return ReplyClassification(ReplyIntent.UNCLEAR)


def _strip_quotation(paragraph: str) -> str:
    """Remove a verbatim quotation the document is no longer entitled to make."""
    cleaned = _QUOTE_RE.sub("содержание нормы не воспроизводится до сверки", paragraph)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _mark_paragraph(paragraph: str, reference: ProvisionReference) -> str:
    body = _strip_quotation(paragraph).rstrip(" .")
    return (
        f"[ТРЕБУЕТ ПРОВЕРКИ: {body}. Действующая редакция и содержание "
        f"{reference.label()} подлежат сверке по официальному источнику до подачи документа; "
        "в настоящем документе содержание нормы не утверждается.]"
    )


def apply_citation_waiver(
    lines: list[str],
    targets: list[ProvisionReference],
) -> tuple[list[str], list[ProvisionReference]]:
    """Downgrade the named provisions to NEEDS_VERIFICATION inside ``lines``.

    Returns the rewritten lines and the references that were actually touched.
    """
    applied: list[ProvisionReference] = []
    rewritten: list[str] = []

    for line in lines:
        present = [
            target
            for target in targets
            if any(target.matches(found) for found in extract_references(line))
        ]
        if not present or "[ТРЕБУЕТ ПРОВЕРКИ" in line.upper():
            rewritten.append(line)
            continue

        marked = _mark_paragraph(line, present[0])
        if unbalanced_quotes(marked):
            # Never ship a paragraph the rewrite broke; keep the original and
            # report the target as untouched so the gate still blocks it.
            rewritten.append(line)
            continue

        rewritten.append(marked)
        for target in present:
            if target not in applied:
                applied.append(target)

    return rewritten, applied
