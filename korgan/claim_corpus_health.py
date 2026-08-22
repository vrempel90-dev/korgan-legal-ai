from __future__ import annotations

import re
from datetime import date
from typing import Any

from korgan.legal.corpus import (
    ACT_CONSUMER,
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    ACT_GPK,
    ACT_LABOR,
    ACT_TAX_DUTY,
)
from korgan.legal.pipeline import local_corpus_enabled, open_corpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

LEGAL_GROUNDING_PREFIX = "LEGAL_GROUNDING: "
MAX_CORPUS_AGE_DAYS = 7

_ARTICLE_RE = re.compile(r"(?:статья|статьи|ст\.)\s*(\d+(?:-\d+)?)", re.IGNORECASE)
_SOURCE_RE = re.compile(r"источник:\s*(https?://[^\]\s]+)", re.IGNORECASE)
_ECONOMIC_COURT_RE = re.compile(r"экономическ\w*\s+суд", re.IGNORECASE)
_SOURCE_ACT_IDS: tuple[tuple[str, str], ...] = (
    ("K940001000_", ACT_GK_GENERAL),
    ("K990000409_", ACT_GK_SPECIAL),
    ("K1500000377", ACT_GPK),
    ("K2500000214", ACT_TAX_DUTY),
    ("Z100000274_", ACT_CONSUMER),
    ("K1500000414", ACT_LABOR),
)


def _source_act_id(source_url: str) -> str | None:
    lowered = (source_url or "").lower()
    for token, act_id in _SOURCE_ACT_IDS:
        if token.lower() in lowered:
            return act_id
    return None


def _parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _snapshot_issue(corpus: Any, act_id: str, *, today: date) -> str | None:
    row = corpus.connection.execute(
        "SELECT edition_date, loaded_at FROM acts WHERE act_id = ?",
        (act_id,),
    ).fetchone()
    if row is None:
        return f"акт {act_id} отсутствует в локальном корпусе Adilet"

    edition = _parse_iso(str(row["edition_date"] or ""))
    loaded = _parse_iso(str(row["loaded_at"] or ""))
    if edition is None or loaded is None:
        return f"акт {act_id} не содержит валидные edition_date/loaded_at"
    if (today - loaded).days < 0 or (today - edition).days < 0:
        return f"акт {act_id} имеет дату корпуса из будущего"
    if (today - loaded).days > MAX_CORPUS_AGE_DAYS:
        return f"акт {act_id} не обновлялся более {MAX_CORPUS_AGE_DAYS} дней"
    if (today - edition).days > MAX_CORPUS_AGE_DAYS:
        return f"редакция акта {act_id} не сверялась более {MAX_CORPUS_AGE_DAYS} дней"
    return None


def _provision_issue(
    corpus: Any,
    act_id: str,
    article_no: str,
    *,
    today: date,
) -> str | None:
    rows = corpus.connection.execute(
        "SELECT edition_date FROM provisions WHERE act_id = ? AND article_no = ?",
        (act_id, article_no),
    ).fetchall()
    if not rows:
        return f"статья {article_no} отсутствует в актуальном снимке акта {act_id}"
    for row in rows:
        edition = _parse_iso(str(row["edition_date"] or ""))
        if edition is None:
            return f"статья {article_no} акта {act_id} не содержит валидную edition_date"
        age = (today - edition).days
        if age < 0:
            return f"статья {article_no} акта {act_id} имеет дату редакции из будущего"
        if age > MAX_CORPUS_AGE_DAYS:
            return f"статья {article_no} акта {act_id} не сверялась более {MAX_CORPUS_AGE_DAYS} дней"
    return None


def _required_provisions(research: LegalResearch, draft: ClaimDraft) -> set[tuple[str, str]]:
    required: set[tuple[str, str]] = set()
    for raw in research.verified_claims:
        line = str(raw or "")
        source_match = _SOURCE_RE.search(line)
        article_match = _ARTICLE_RE.search(line)
        if source_match is None or article_match is None:
            continue
        act_id = _source_act_id(source_match.group(1))
        if act_id:
            required.add((act_id, article_match.group(1)))

    if _ECONOMIC_COURT_RE.search(draft.court or ""):
        required.add((ACT_GPK, "27"))
    return required


def enforce_claim_corpus_health(
    research: LegalResearch,
    draft: ClaimDraft,
    *,
    today: date | None = None,
) -> None:
    """Fail closed when a filing relies on an absent, damaged, incomplete or stale Adilet snapshot."""
    if not local_corpus_enabled():
        # The filing-accuracy gate already handles this case and supplies the
        # user-facing grounding note. Do not duplicate it here.
        return

    corpus = open_corpus()
    if corpus is None:
        # Likewise, open_corpus() already treats missing/unreadable/empty DBs as
        # unavailable. claim_filing_accuracy clears filing-facing legal bases.
        return

    check_date = today or date.today()
    issues: list[str] = []
    try:
        required = _required_provisions(research, draft)
        for act_id in sorted({act_id for act_id, _ in required}):
            issue = _snapshot_issue(corpus, act_id, today=check_date)
            if issue:
                issues.append(issue)
        for act_id, article_no in sorted(required):
            issue = _provision_issue(corpus, act_id, article_no, today=check_date)
            if issue:
                issues.append(issue)
    except Exception as exc:
        issues.append(f"локальный корпус Adilet не прошёл проверку целостности: {type(exc).__name__}")
    finally:
        corpus.close()

    if not issues:
        return

    draft.status = VerificationStatus.NEEDS_VERIFICATION
    draft.legal_basis = []
    for issue in list(dict.fromkeys(issues))[:8]:
        note = LEGAL_GROUNDING_PREFIX + issue
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)
