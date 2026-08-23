from __future__ import annotations

import logging
import re
import time

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from korgan import bot as base_bot
from korgan import document_quality
from korgan.citation_audit import ProvisionReference, extract_references
from korgan.claim_core_release import core_claim_release_blockers
from korgan.claim_docx import build_claim_docx, missing_required_fields
from korgan.claim_failure import ClaimStage, failure_from_exception
from korgan.claim_intent import is_claim_drafting_request
from korgan.contract_intent import is_contract_drafting_request
from korgan.document_quality import assess_document_quality, rendered_docx_blockers
from korgan.document_release import review_lines
from korgan.gate_instructions import keep_accepted_provisions
from korgan.instant_claim_runtime import _strip_reference_token
from korgan.legal_basis_fit import enforce_legal_basis_fit
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.request_scope import (
    current_request_id,
    is_main_menu_text,
    request_is_current,
    request_label,
    start_new_document_request,
)
from korgan.response_intent import is_response_to_claim_request
from korgan.telegram_text import bullets, fit_caption

LOGGER = logging.getLogger(__name__)
router = Router(name="universal-quality-claim")
_SENIOR_SCORE_RE = re.compile(r"SENIOR_PREFLIGHT_SCORE:\s*(\d+(?:[.,]\d+)?)\s*/\s*10", re.IGNORECASE)


class _ClaimWaiting(Filter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        text = message.text or ""
        return (
            data.get("mode") == "universal_claim_waiting"
            and bool(text)
            and not text.startswith("/")
            and not is_main_menu_text(text)
        )


class _ClaimIntent(Filter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details", "response_details"}:
            return False
        text = message.text or ""
        if is_main_menu_text(text):
            return False
        if is_response_to_claim_request(text) or is_contract_drafting_request(text):
            return False
        return bool(text and is_claim_drafting_request(text))


async def _append_fact_once(state: FSMContext, text: str) -> None:
    value = (text or "").strip()
    if not value or is_main_menu_text(value):
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != value:
        facts.append(value)
    await state.update_data(facts=facts[-20:])


async def begin_claim_request(message: Message, state: FSMContext) -> None:
    """Prompt for new-case materials without starting generation."""
    lang = await base_bot._language(state)
    await state.update_data(mode="universal_claim_waiting")
    if lang == "kk":
        text = (
            f"🆕 Жаңа өтінім — {request_label('claim', lang)}.\n\n"
            "Істің мән-жайын бір хабарламада сипаттаңыз немесе материалдарды (PDF/DOCX/фото) тіркеңіз. "
            "Алдыңғы өтінімнің деректері бұл іске қолданылмайды."
        )
    else:
        text = (
            f"🆕 Новая заявка — {request_label('claim', lang)}.\n\n"
            "Опишите обстоятельства дела одним сообщением или приложите материалы (PDF/DOCX/фото). "
            "Данные предыдущей заявки в это дело не переносятся."
        )
    await message.answer(text, reply_markup=base_bot.MENU)


def _fill_only_empty_structural_blocks(draft: ClaimDraft) -> None:
    """Never re-run legacy field-intake heuristics after quality repair."""
    if not draft.claimant:
        draft.claimant = ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"]
    if not draft.defendant:
        draft.defendant = ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]
    if not draft.facts:
        draft.facts = ["[ТРЕБУЕТ УТОЧНЕНИЯ: обстоятельства дела]"]
    if not draft.requests:
        draft.requests = ["[ТРЕБУЕТ УТОЧНЕНИЯ: требования к ответчику]"]


def _claim_release_lines(draft: ClaimDraft) -> list[str]:
    """Legal/model text only; deterministic state duty has its own verifier."""
    return [
        draft.title,
        *draft.facts,
        *draft.legal_basis,
        draft.late_interest,
        *draft.requests,
        *draft.attachments,
    ]


def _blocking_references(report) -> list[ProvisionReference]:
    refs: list[ProvisionReference] = []
    for finding in report.citations.blocking:
        ref = ProvisionReference(finding.act, finding.article, finding.part)
        if ref not in refs:
            refs.append(ref)
    return refs


def _downgrade_unverified_citations_live(
    draft: ClaimDraft,
    research: LegalResearch,
):
    """Downgrade only citations absent from current live VERIFIED and corpus."""
    report = review_lines(
        _claim_release_lines(draft),
        verified_claims=research.verified_claims,
    )
    refs = _blocking_references(report)
    if not refs:
        return report

    draft.legal_basis, kept = keep_accepted_provisions(list(draft.legal_basis), refs)

    for attribute in ("facts", "requests", "attachments"):
        original = list(getattr(draft, attribute, []) or [])
        rebuilt: list[str] = []
        for value in original:
            updated = value
            for ref in refs:
                if any(ref.matches(found) for found in extract_references(updated)):
                    updated = _strip_reference_token(updated, ref)
            if updated.strip():
                rebuilt.append(updated)
        setattr(draft, attribute, rebuilt)

    if draft.late_interest:
        updated = draft.late_interest
        for ref in refs:
            if any(ref.matches(found) for found in extract_references(updated)):
                updated = _strip_reference_token(updated, ref)
        draft.late_interest = updated

    draft.status = VerificationStatus.NEEDS_VERIFICATION
    for ref in kept or refs:
        note = (
            f"{ref.label()}: содержание не подтверждено ни source-bound исследованием текущего дела, "
            "ни проверенным корпусом; требуется сверка до подачи."
        )
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    return review_lines(
        _claim_release_lines(draft),
        verified_claims=research.verified_claims,
    )


def _quality_note(score: float, issues: list[str]) -> str:
    details = "; ".join(issues[:6]) or "остались вопросы, требующие проверки"
    return f"KORGAN QUALITY {score:.1f}/10: {details}"


def _senior_score_from_notes(draft: ClaimDraft) -> float | None:
    scores: list[float] = []
    for note in draft.verification_notes:
        match = _SENIOR_SCORE_RE.search(str(note))
        if not match:
            continue
        try:
            scores.append(float(match.group(1).replace(",", ".")))
        except ValueError:
            continue
    return min(scores) if scores else None


def _apply_senior_score_to_quality(draft: ClaimDraft, quality) -> None:
    """Do not display the old synthetic 8.4 when senior counsel scored lower."""
    senior_score = _senior_score_from_notes(draft)
    if senior_score is None:
        return
    quality.score = round(min(float(quality.score), senior_score), 1)


async def _send_claim(
    message: Message,
    state: FSMContext,
    *,
    context: str,
    research: LegalResearch,
    draft: ClaimDraft,
    request_id: str,
) -> None:
    if not await request_is_current(state, request_id, "claim"):
        LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
        return

    fit = enforce_legal_basis_fit(draft)
    if fit:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        for item in fit:
            note = f"Правовое основание требует проверки: {item}"
            if note not in draft.verification_notes:
                draft.verification_notes.append(note)

    release = _downgrade_unverified_citations_live(draft, research)
    if release.citations.blocking or release.integrity:
        LOGGER.error(
            "UNIVERSAL_CLAIM_RELEASE_BLOCK citations=%s integrity=%s",
            [x.as_note() for x in release.citations.blocking[:4]],
            [x.as_note() for x in release.integrity[:4]],
        )
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        await message.answer(
            "Не удалось безопасно выпустить Word: финальная проверка обнаружила повреждённый текст или неподтверждённую правовую ссылку.",
            reply_markup=base_bot.MENU,
        )
        return

    core_blockers = core_claim_release_blockers(research, draft)
    if core_blockers:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        LOGGER.error(
            "UNIVERSAL_CLAIM_CORE_RELEASE_BLOCK request_id=%s blockers=%s",
            request_id,
            core_blockers[:4],
        )
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        lang = await base_bot._language(state)
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        if lang == "kk":
            text = (
                "Иск Word ретінде әлі шығарылмады: сотқа берілетін құжатта орындалатын талаптар "
                "және ресми дереккөзбен расталған материалдық-құқықтық негіз міндетті түрде болуы керек. "
                "KORGAN тексеруді аяқтамайынша толық емес талап қою арызын дайын құжат ретінде бермейді."
            )
        else:
            text = (
                "Иск пока не выпущен в Word: в судебном документе обязательно должны быть "
                "исполнимая просительная часть и подтверждённое официальным источником "
                "материально-правовое основание. KORGAN не выдаёт неполный иск как готовый документ."
            )
        await message.answer(text, reply_markup=base_bot.MENU)
        return

    quality = assess_document_quality("claim", context, research, draft)
    _apply_senior_score_to_quality(draft, quality)
    if quality.ready:
        draft.status = VerificationStatus.VERIFIED
    else:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = _quality_note(quality.score, quality.repair_issues())
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    try:
        file_bytes = build_claim_docx(draft)
    except Exception as exc:
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        await base_bot._report_claim_failure(
            message,
            failure_from_exception(exc, stage=ClaimStage.RENDER),
        )
        return

    export_blockers = rendered_docx_blockers(file_bytes, ready_expected=quality.ready)
    if quality.ready and export_blockers:
        LOGGER.error("UNIVERSAL_CLAIM_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        await message.answer(
            "Не удалось безопасно выпустить готовый Word: экспорт не прошёл финальную проверку качества.",
            reply_markup=base_bot.MENU,
        )
        return

    if not await request_is_current(state, request_id, "claim"):
        LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
        return

    await state.update_data(mode="main", gate_issues=[], claim_draft=None, pending_fields=[])
    if quality.ready:
        caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nИск сформирован в Word (.docx)."
    else:
        caption = (
            f"⚠️ PRELIMINARY · KORGAN QUALITY {quality.score:.1f}/10\n"
            f"Проект иска сформирован, но не достиг порога {document_quality.MIN_READY_SCORE:.1f}/10."
        )
        checks = quality.repair_issues()[:6]
        if checks:
            caption += "\n\nПеред подачей требуется:\n" + bullets(checks)

    if not await request_is_current(state, request_id, "claim"):
        LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
        return
    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_iskovoe_zayavlenie.docx"),
        caption=fit_caption(caption),
        reply_markup=base_bot.MENU,
    )


async def _generate_now(message: Message, state: FSMContext) -> None:
    service = base_bot.service
    if service is None:
        return

    request_id = await current_request_id(state, "claim")
    context = await base_bot._case_context(state)
    if not context.strip():
        await begin_claim_request(message, state)
        return

    await state.update_data(
        mode="main",
        pending_fields=[],
        intake_repeats=0,
        critical_answered=False,
        gate_issues=[],
        claim_draft=None,
    )
    lang = await base_bot._language(state)
    await message.bot.send_chat_action(message.chat.id, "typing")

    started = time.perf_counter()
    try:
        research = await service.research_case(context, language=lang)
    except Exception as exc:
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        await base_bot._report_claim_failure(
            message,
            failure_from_exception(exc, stage=ClaimStage.RESEARCH),
        )
        return

    try:
        draft = await service.draft_claim(context, research, language=lang)
    except Exception as exc:
        if not await request_is_current(state, request_id, "claim"):
            LOGGER.info("STALE_DOCUMENT_SUPPRESSED kind=claim request_id=%s", request_id)
            return
        await base_bot._report_claim_failure(
            message,
            failure_from_exception(exc, stage=ClaimStage.DRAFT),
        )
        return

    _fill_only_empty_structural_blocks(draft)
    if missing_required_fields(draft):
        draft.status = VerificationStatus.NEEDS_VERIFICATION

    LOGGER.info(
        "UNIVERSAL_CLAIM_GENERATED seconds=%.2f status=%s",
        time.perf_counter() - started,
        draft.status.value,
    )
    await _send_claim(
        message,
        state,
        context=context,
        research=research,
        draft=draft,
        request_id=request_id,
    )


@router.message(Command("claim"))
@router.message(F.text == "📄 Подготовить иск")
async def claim_button(message: Message, state: FSMContext) -> None:
    await start_new_document_request(state, kind="claim", mode="universal_claim_waiting")
    await begin_claim_request(message, state)


@router.message(_ClaimWaiting(), F.text)
async def claim_description(message: Message, state: FSMContext) -> None:
    await _append_fact_once(state, message.text or "")
    await _generate_now(message, state)


@router.message(_ClaimIntent(), F.text)
async def claim_from_one_message(message: Message, state: FSMContext) -> None:
    await start_new_document_request(state, kind="claim", mode="main")
    if (message.text or "").strip() != "📄 Подготовить иск":
        await _append_fact_once(state, message.text or "")
    await _generate_now(message, state)