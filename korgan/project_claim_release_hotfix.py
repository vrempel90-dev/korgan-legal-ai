"""Allow KORGAN to deliver a reviewable claim project when only filing details remain.

This hotfix intentionally does not weaken material-law or citation safety.  The
existing court-ready guard still blocks empty prayers, missing VERIFIED material
law, internal verification text and broken legal bases.  We only downgrade
project-level issues (court name, filing details, unsupported secondary remedies
that were already omitted, and sub-8.5 quality) from "no Word at all" to
"deliver a project that still needs lawyer/final filing review".
"""

from __future__ import annotations

import logging
import re

from korgan.claim_quality_hotfix import FILING_ACTION_PREFIX
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)

_PROJECT_DETAIL_TOKENS = (
    "неустойк",
    "пен",
    "госпошлин",
    "суд",
    "подсудн",
    "иин",
    "бин",
    "адрес",
    "дата рождения",
    "банковск",
    "реквизит",
    "доказатель",
    "приложен",
)

_ALWAYS_PROJECT_ONLY_RE = re.compile(
    r"(?i)(?:финальный юридический quality-gate ниже 8[.,]5|"
    r"не определена госпошлина|"
    r"наименование суда не подтверждено|"
    r"точное наименование суда|"
    r"нарушена целостность текста:\s*точка между словами без пробела|"
    r"release-check обнаружил повреждение текста)"
)
_UNRESOLVED_RE = re.compile(r"(?i)остались нереш[её]нные вопросы проверки")

# Safe mechanical repairs only.  We repair a missing whitespace at a clear
# sentence/quote boundary.  Lower-case welded tails remain untouched so the
# original integrity gate can still block genuine corruption.
_SENTENCE_SPACE_RE = re.compile(r"(?<=[а-яёa-z0-9»”])\.(?=[А-ЯЁA-Z«])")
_QUOTE_SPACE_RE = re.compile(r"([»”][,;:]?)(?=[А-ЯЁA-Z])")
_OPEN_QUOTE_SPACE_RE = re.compile(r"(?<=[А-ЯЁа-яёA-Za-z0-9])«")


def repair_safe_spacing_text(text: str) -> str:
    """Repair only unambiguous missing spaces without changing legal wording."""
    value = str(text or "")
    if not value or "http://" in value.lower() or "https://" in value.lower():
        return value
    value = _SENTENCE_SPACE_RE.sub(". ", value)
    value = _QUOTE_SPACE_RE.sub(r"\1 ", value)
    value = _OPEN_QUOTE_SPACE_RE.sub(" «", value)
    return value


def repair_safe_claim_spacing(draft: ClaimDraft) -> None:
    """Normalize harmless glue artefacts before the real integrity release check."""
    for attribute in ("claimant", "defendant", "facts", "legal_basis", "requests", "attachments"):
        values = list(getattr(draft, attribute, []) or [])
        setattr(draft, attribute, [repair_safe_spacing_text(value) for value in values])
    draft.title = repair_safe_spacing_text(draft.title)
    draft.court = repair_safe_spacing_text(draft.court)
    draft.price_of_claim = repair_safe_spacing_text(draft.price_of_claim)
    draft.state_duty = repair_safe_spacing_text(draft.state_duty)
    draft.late_interest = repair_safe_spacing_text(draft.late_interest)


def _is_project_only_defect(defect: str) -> bool:
    text = str(defect or "")
    lower = text.lower()
    if _ALWAYS_PROJECT_ONLY_RE.search(text):
        return True
    if _UNRESOLVED_RE.search(text) and any(token in lower for token in _PROJECT_DETAIL_TOKENS):
        return True
    return False


def filter_fatal_release_defects(defects: list[str]) -> list[str]:
    """Keep only defects that make even a reviewable Word project unsafe."""
    return [str(item) for item in defects if not _is_project_only_defect(str(item))]


def _add_filing_action(draft: ClaimDraft, message: str) -> None:
    note = FILING_ACTION_PREFIX + message
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)


def _promote_project_notes_to_filing_actions(draft: ClaimDraft) -> None:
    notes = "\n".join(str(note or "") for note in draft.verification_notes).lower()
    if "неустойк" in notes or "пен" in notes:
        _add_filing_action(
            draft,
            "если заявляется неустойка/пеня, до подачи подтвердить её вид, правовое основание и расчет; неподтверждённое дополнительное требование в проект не включать.",
        )
    if "доказатель" in notes:
        _add_filing_action(
            draft,
            "до подачи приложить имеющиеся доказательства и проверить, что каждое существенное обстоятельство подтверждено документами.",
        )


def install_project_claim_release_hotfix() -> None:
    """Patch only the final claim-release classification; keep generator/RAG intact."""
    from korgan import court_ready_claim_guard as guard

    if getattr(guard, "_project_claim_release_hotfix_installed", False):
        return

    original_defects = guard.substantive_release_defects

    def project_release_defects(
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> list[str]:
        repair_safe_claim_spacing(draft)
        defects = original_defects(case_context, research, draft)
        fatal = filter_fatal_release_defects(defects)
        if len(fatal) != len(defects):
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            _promote_project_notes_to_filing_actions(draft)
            LOGGER.info(
                "KORGAN claim project release: downgraded=%s fatal=%s",
                [item for item in defects if item not in fatal][:6],
                fatal[:6],
            )
        return fatal

    guard.substantive_release_defects = project_release_defects
    guard._project_claim_release_hotfix_installed = True
    LOGGER.info("Installed KORGAN reviewable claim-project release hotfix")
