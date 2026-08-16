from __future__ import annotations

import logging
import re
from typing import Any

from korgan import document_quality as _dq
from korgan import senior_claim_preflight as _sp
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

LOGGER = logging.getLogger(__name__)

FILING_ACTION_PREFIX = "FILING_ACTION: "

_ORIGINAL_ASSESS = _dq.assess_document_quality
_ORIGINAL_PREFLIGHT = _sp.deterministic_claim_preflight

_ARTICLE_TOKEN_RE = re.compile(r"(?i)(?:статья|статьи|ст\.)\s*\d+(?:-\d+)?")
_AMOUNT_RE = re.compile(r"(?<!\d)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|тг\b|₸)", re.IGNORECASE)
_MORAL_REQUEST_RE = re.compile(r"моральн\w*\s+вред", re.IGNORECASE)
_MORAL_FACT_RE = re.compile(
    r"нервн\w*|стресс\w*|переживан\w*|моральн\w*\s+страдан\w*|"
    r"нравственн\w*\s+страдан\w*|физическ\w*\s+страдан\w*|"
    r"ухудшен\w*\s+(?:здоров|самочувств)|бессонниц\w*|неудобств\w*",
    re.IGNORECASE,
)

_COURT_PREFLIGHT_FRAGMENT = "Точное наименование суда не подтверждено материалами пользователя или source-bound записью VERIFIED_COURT."
_COURT_QUALITY_MARKERS = (
    "не определено конкретное наименование суда",
    "наименование суда не подтверждено материалами дела или официальным source-bound исследованием",
)
_COURT_NOTE_RE = re.compile(
    r"(?i)(?:точн\w*\s+наименован\w*\s+суд|суд\w*\s+.*(?:уточнен|провер|верифиц|verified_court))"
)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _verified_statement_and_article(line: str) -> tuple[str, str] | None:
    marker = "[основание:"
    pos = (line or "").find(marker)
    if pos < 0:
        return None
    statement = line[:pos].strip().rstrip(".;")
    remainder = line[pos + len(marker):]
    article = remainder.split(";", 1)[0].strip()
    if not statement or not article or not _ARTICLE_TOKEN_RE.search(article):
        return None
    if "официальный перечень судов" in article.lower():
        return None
    return statement, article


def _ensure_verified_articles(research: LegalResearch, draft: ClaimDraft) -> None:
    """Carry source-bound legal conclusions into the court-facing legal basis.

    The model is not allowed to decide that a VERIFIED article is optional. We
    copy only the already accepted statement+article pair and deliberately omit
    the source URL and internal provision-text metadata from the filing.
    """
    existing = "\n".join(draft.legal_basis).lower()
    additions: list[str] = []
    for line in research.verified_claims:
        parsed = _verified_statement_and_article(str(line))
        if parsed is None:
            continue
        statement, article = parsed
        if article.lower() in existing:
            continue
        additions.append(f"{statement}. Основание: {article}.")
        existing += "\n" + article.lower()
        if len(additions) >= 5:
            break
    if additions:
        draft.legal_basis.extend(additions)


def _remove_invented_subjective_harm(case_context: str, draft: ClaimDraft) -> None:
    """The model may not manufacture distress/health facts to support moral harm."""
    if _MORAL_FACT_RE.search(case_context or ""):
        return
    original = list(draft.facts)
    draft.facts = [item for item in original if not _MORAL_FACT_RE.search(str(item))]
    removed = len(original) - len(draft.facts)
    if removed:
        LOGGER.info("CLAIM_FACT_LOCK removed_invented_subjective_lines=%d", removed)


def _remove_invented_moral_amount(case_context: str, draft: ClaimDraft) -> None:
    """Do not invent a monetary amount for moral harm when the user did not give it."""
    context_amounts = {_digits(match.group(1)) for match in _AMOUNT_RE.finditer(case_context or "")}
    kept: list[str] = []
    removed = False
    for request in draft.requests:
        if not _MORAL_REQUEST_RE.search(request):
            kept.append(request)
            continue
        amounts = {_digits(match.group(1)) for match in _AMOUNT_RE.finditer(request)}
        if amounts and not amounts.issubset(context_amounts):
            removed = True
            continue
        kept.append(request)
    draft.requests = kept
    if removed:
        note = (
            "Размер компенсации морального вреда не указан пользователем; денежное требование не включено, "
            "чтобы KORGAN не придумывал сумму."
        )
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)


def _normalize_filing_notes(draft: ClaimDraft) -> None:
    clean: list[str] = []
    filing: list[str] = []
    for raw in draft.verification_notes:
        note = str(raw).strip()
        if not note:
            continue
        if note.startswith(FILING_ACTION_PREFIX):
            filing.append(note)
            continue
        if _COURT_NOTE_RE.search(note) and "суд" in note.lower():
            filing.append(
                FILING_ACTION_PREFIX
                + "перед подачей подтвердить точное официальное наименование суда и его территориальную компетенцию."
            )
            continue
        clean.append(note)
    draft.verification_notes = list(dict.fromkeys([*clean, *filing]))


def polish_claim_before_quality(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    _remove_invented_subjective_harm(case_context, draft)
    _remove_invented_moral_amount(case_context, draft)
    _ensure_verified_articles(research, draft)
    _normalize_filing_notes(draft)


def _filing_notes(draft: ClaimDraft) -> list[str]:
    return [
        str(note)[len(FILING_ACTION_PREFIX):].strip()
        for note in draft.verification_notes
        if str(note).startswith(FILING_ACTION_PREFIX)
    ]


def _patched_preflight(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
    """Keep substantive contradictions hard; exact court identity is a filing prerequisite."""
    errors = _ORIGINAL_PREFLIGHT(case_context, research, draft)
    return [item for item in errors if _COURT_PREFLIGHT_FRAGMENT not in str(item)]


def _patched_assess_document_quality(
    kind: Any,
    case_context: str,
    research: LegalResearch,
    draft: Any,
):
    if kind != "claim" or not isinstance(draft, ClaimDraft):
        return _ORIGINAL_ASSESS(kind, case_context, research, draft)

    polish_claim_before_quality(case_context, research, draft)

    # Filing-only notes must remain visible to the user but must not be counted
    # as defects in the legal substance score.
    all_notes = list(draft.verification_notes)
    draft.verification_notes = [
        note for note in all_notes if not str(note).startswith(FILING_ACTION_PREFIX)
    ]
    try:
        report = _ORIGINAL_ASSESS(kind, case_context, research, draft)
    finally:
        draft.verification_notes = all_notes

    removed_court: list[str] = []
    remaining: list[str] = []
    restore = 0.0
    for blocker in report.hard_blockers:
        lower = str(blocker).lower()
        if _COURT_QUALITY_MARKERS[0] in lower:
            removed_court.append(str(blocker))
            restore += 0.75
            continue
        if _COURT_QUALITY_MARKERS[1] in lower:
            removed_court.append(str(blocker))
            restore += 0.55
            continue
        remaining.append(str(blocker))

    filing = _filing_notes(draft)
    if removed_court and not filing:
        filing = ["перед подачей подтвердить точное официальное наименование суда и территориальную компетенцию."]
        draft.verification_notes.append(FILING_ACTION_PREFIX + filing[0])

    report.hard_blockers = list(dict.fromkeys(remaining))
    base_score = sum(float(value) for value in report.category_scores.values()) + restore
    report.score = round(max(0.0, min(10.0, base_score)), 1)
    if report.hard_blockers:
        report.score = min(report.score, 8.4)
    for item in filing:
        marker = FILING_ACTION_PREFIX + item
        if marker not in report.issues:
            report.issues.append(marker)
    return report


# Install the policy before importing the fast service. Its `from ... import`
# bindings therefore receive the corrected functions as well.
_dq.assess_document_quality = _patched_assess_document_quality
_sp.deterministic_claim_preflight = _patched_preflight

from korgan.fast_professional_litigation import FastProfessionalLitigationService as _FastProfessionalLitigationService  # noqa: E402


class ProductionClaimService(_FastProfessionalLitigationService):
    """Fast professional litigation plus deterministic final claim polish."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)
        polish_claim_before_quality(case_context, research, draft)
        filing = _filing_notes(draft)
        if filing:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            draft.verification_notes = [
                note for note in draft.verification_notes
                if not str(note).startswith("SENIOR_PREFLIGHT_SCORE:")
            ]
        return draft


def install_runtime_hotfix() -> None:
    """Patch only the claim-delivery caption/status; contracts and responses stay unchanged."""
    from korgan import universal_claim_runtime as runtime
    from korgan.claim_docx import build_claim_docx
    from korgan.claim_failure import ClaimStage, failure_from_exception
    from korgan.document_quality import rendered_docx_blockers
    from korgan.telegram_text import bullets, fit_caption
    from aiogram.types import BufferedInputFile
    from korgan import bot as base_bot

    async def _send_claim(
        message,
        state,
        *,
        context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> None:
        fit = runtime.enforce_legal_basis_fit(draft)
        if fit:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            for item in fit:
                note = f"Правовое основание требует проверки: {item}"
                if note not in draft.verification_notes:
                    draft.verification_notes.append(note)

        release = runtime._downgrade_unverified_citations_live(draft, research)
        if release.citations.blocking or release.integrity:
            LOGGER.error(
                "UNIVERSAL_CLAIM_RELEASE_BLOCK citations=%s integrity=%s",
                [x.as_note() for x in release.citations.blocking[:4]],
                [x.as_note() for x in release.integrity[:4]],
            )
            await message.answer(
                "Не удалось безопасно выпустить Word: финальная проверка обнаружила повреждённый текст или неподтверждённую правовую ссылку.",
                reply_markup=base_bot.MENU,
            )
            return

        quality = _patched_assess_document_quality("claim", context, research, draft)
        filing = [
            str(item)[len(FILING_ACTION_PREFIX):].strip()
            for item in quality.issues
            if str(item).startswith(FILING_ACTION_PREFIX)
        ]
        substantive_issues = [
            str(item) for item in quality.repair_issues()
            if not str(item).startswith(FILING_ACTION_PREFIX)
        ]

        if quality.ready and not filing:
            draft.status = VerificationStatus.VERIFIED
        else:
            draft.status = VerificationStatus.NEEDS_VERIFICATION

        try:
            file_bytes = build_claim_docx(draft)
        except Exception as exc:
            await base_bot._report_claim_failure(
                message,
                failure_from_exception(exc, stage=ClaimStage.RENDER),
            )
            return

        export_blockers = rendered_docx_blockers(
            file_bytes,
            ready_expected=quality.ready and not filing,
        )
        if quality.ready and not filing and export_blockers:
            LOGGER.error("UNIVERSAL_CLAIM_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
            await message.answer(
                "Не удалось безопасно выпустить готовый Word: экспорт не прошёл финальную проверку качества.",
                reply_markup=base_bot.MENU,
            )
            return

        await state.update_data(mode="main", gate_issues=[], claim_draft=None, pending_fields=[])
        if quality.ready and not filing:
            caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nИск сформирован в Word (.docx)."
        elif quality.ready and filing:
            caption = (
                f"⚠️ KORGAN QUALITY {quality.score:.1f}/10 · ПРОЕКТ ГОТОВ\n"
                "Юридическое содержание прошло порог качества. Перед подачей нужно заполнить/проверить реквизиты:"
            )
            caption += "\n" + bullets(filing[:6])
        else:
            caption = (
                f"⚠️ PRELIMINARY · KORGAN QUALITY {quality.score:.1f}/10\n"
                "В проекте остались юридические замечания, которые нужно исправить перед подачей."
            )
            checks = [*substantive_issues, *filing][:6]
            if checks:
                caption += "\n\nПеред подачей требуется:\n" + bullets(checks)

        await message.answer_document(
            BufferedInputFile(file_bytes, filename="KORGAN_iskovoe_zayavlenie.docx"),
            caption=fit_caption(caption),
            reply_markup=base_bot.MENU,
        )

    runtime._send_claim = _send_claim
    LOGGER.info("Installed KORGAN claim quality hotfix: filing prerequisites separated from substantive score")
