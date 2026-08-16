from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from korgan import bot as base_bot
from korgan.claim_docx import build_claim_docx, missing_required_fields
from korgan.claim_failure import ClaimStage, failure_from_exception
from korgan.claim_intent import is_claim_drafting_request
from korgan.contract_intent import is_contract_drafting_request
from korgan.document_quality import assess_document_quality, rendered_docx_blockers
from korgan.instant_claim_runtime import _downgrade_unverified_citations
from korgan.legal_basis_fit import enforce_legal_basis_fit
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.response_intent import is_response_to_claim_request
from korgan.telegram_text import bullets, fit_caption

LOGGER = logging.getLogger(__name__)
router = Router(name="universal-quality-claim")


class _ClaimWaiting(Filter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "universal_claim_waiting"


class _ClaimIntent(Filter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        if data.get("mode") in {"consultation", "contract_details", "response_details"}:
            return False
        text = message.text or ""
        # «подготовь отзыв на иск» contains both an action verb and the word
        # «иск»; document type routing must win before generic claim detection.
        if is_response_to_claim_request(text) or is_contract_drafting_request(text):
            return False
        return bool(text and is_claim_drafting_request(text))


async def _append_fact_once(state: FSMContext, text: str) -> None:
    value = (text or "").strip()
    if not value:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != value:
        facts.append(value)
    await state.update_data(facts=facts[-20:])


def _fill_only_empty_structural_blocks(draft: ClaimDraft) -> None:
    """Never re-run the old field-intake policy after quality repair.

    Only a completely empty court-document block gets a visible fail-closed
    placeholder. Individual requisites are left to source-bound drafting and
    the universal quality gate; stale intake heuristics cannot reintroduce
    impossible requisites after a repaired draft.
    """
    if not draft.claimant:
        draft.claimant = ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"]
    if not draft.defendant:
        draft.defendant = ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]
    if not draft.facts:
        draft.facts = ["[ТРЕБУЕТ УТОЧНЕНИЯ: обстоятельства дела]"]
    if not draft.requests:
        draft.requests = ["[ТРЕБУЕТ УТОЧНЕНИЯ: требования к ответчику]"]


def _quality_note(score: float, issues: list[str]) -> str:
    details = "; ".join(issues[:6]) or "остались вопросы, требующие проверки"
    return f"KORGAN QUALITY {score:.1f}/10: {details}"


async def _send_claim(
    message: Message,
    state: FSMContext,
    *,
    context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> None:
    # Fit check is generic: the law must prove the requested remedy, not merely
    # belong to the same legal topic.
    fit = enforce_legal_basis_fit(draft)
    if fit:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        for item in fit:
            note = f"Правовое основание требует проверки: {item}"
            if note not in draft.verification_notes:
                draft.verification_notes.append(note)

    release = _downgrade_unverified_citations(draft)
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

    quality = assess_document_quality("claim", context, research, draft)
    if not quality.ready:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = _quality_note(quality.score, quality.repair_issues())
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    try:
        file_bytes = build_claim_docx(draft)
    except Exception as exc:
        await base_bot._report_claim_failure(
            message,
            failure_from_exception(exc, stage=ClaimStage.RENDER),
        )
        return

    export_blockers = rendered_docx_blockers(file_bytes, ready_expected=quality.ready)
    if quality.ready and export_blockers:
        LOGGER.error("UNIVERSAL_CLAIM_DOCX_BLOCK quality=%.1f issues=%s", quality.score, export_blockers)
        await message.answer(
            "Не удалось безопасно выпустить готовый Word: экспорт не прошёл финальную проверку качества.",
            reply_markup=base_bot.MENU,
        )
        return

    await state.update_data(mode="main", gate_issues=[], claim_draft=None, pending_fields=[])
    if quality.ready:
        caption = f"✅ KORGAN QUALITY {quality.score:.1f}/10\nИск сформирован в Word (.docx)."
    else:
        caption = f"⚠️ PRELIMINARY · KORGAN QUALITY {quality.score:.1f}/10\nПроект иска сформирован, но не достиг порога 8.5/10."
        checks = quality.repair_issues()[:6]
        if checks:
            caption += "\n\nПеред подачей требуется:\n" + bullets(checks)

    await message.answer_document(
        BufferedInputFile(file_bytes, filename="KORGAN_iskovoe_zayavlenie.docx"),
        caption=fit_caption(caption),
        reply_markup=base_bot.MENU,
    )


async def _generate_now(message: Message, state: FSMContext) -> None:
    service = base_bot.service
    if service is None:
        return

    context = await base_bot._case_context(state)
    if not context.strip():
        await state.update_data(mode="universal_claim_waiting")
        await message.answer(
            "Опишите обстоятельства дела одним сообщением — после этого сразу сформирую иск без анкеты по реквизитам.",
            reply_markup=base_bot.MENU,
        )
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
    await message.answer("Формирую и проверяю проект иска…", reply_markup=base_bot.MENU)
    await message.bot.send_chat_action(message.chat.id, "typing")

    started = time.perf_counter()
    try:
        research = await service.research_case(context, language=lang)
    except Exception as exc:
        await base_bot._report_claim_failure(
            message,
            failure_from_exception(exc, stage=ClaimStage.RESEARCH),
        )
        return

    try:
        draft = await service.draft_claim(context, research, language=lang)
    except Exception as exc:
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
    await _send_claim(message, state, context=context, research=research, draft=draft)


@router.message(Command("claim"))
@router.message(F.text == "📄 Подготовить иск")
async def claim_button(message: Message, state: FSMContext) -> None:
    await _generate_now(message, state)


@router.message(_ClaimWaiting(), F.text)
async def claim_description(message: Message, state: FSMContext) -> None:
    await _append_fact_once(state, message.text or "")
    await _generate_now(message, state)


@router.message(_ClaimIntent(), F.text)
async def claim_from_one_message(message: Message, state: FSMContext) -> None:
    if (message.text or "").strip() != "📄 Подготовить иск":
        await _append_fact_once(state, message.text or "")
    await _generate_now(message, state)
