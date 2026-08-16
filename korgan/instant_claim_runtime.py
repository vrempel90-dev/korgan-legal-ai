from __future__ import annotations

import logging
import re
import time

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from korgan import bot as base_bot
from korgan.claim_docx import build_claim_docx, missing_required_fields
from korgan.claim_failure import ClaimStage, failure_from_exception
from korgan.claim_intake_policy import apply_formal_placeholders, inspect_claim_gaps, placeholder_notes
from korgan.claim_intent import is_claim_drafting_request
from korgan.citation_audit import ProvisionReference, extract_references
from korgan.civil_claim_hotfix import _sanitize_civil_research
from korgan.document_release import review_lines
from korgan.gate_instructions import keep_accepted_provisions
from korgan.legal_basis_fit import enforce_legal_basis_fit
from korgan.legal_routing import detect_claim_profile
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.response_legal import ProductionOpenAILegalService as _StrictProductionService
from korgan.telegram_text import bullets, fit_caption

LOGGER = logging.getLogger(__name__)
router = Router(name="instant_claim")


class InstantClaimProductionService(_StrictProductionService):
    """Fast claim path without mandatory model QA or a second research pass.

    Source-bound legal research remains mandatory. If the one search pass cannot
    confirm a proposition, the draft is downgraded to NEEDS_VERIFICATION instead
    of making the user wait for another web-search round.

    Model QA is not run for every claim. The inherited claim builder still runs
    deterministic hard checks and can repair a genuinely broken draft, while the
    final document release audit verifies every cited provision and text
    integrity before the DOCX is sent.
    """

    async def validate_claim(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> dict[str, list[str]]:
        # The normal path must not spend a third OpenAI request on an independent
        # validator. Deterministic hard checks and the release audit still run.
        return {
            "critical_errors": [],
            "unsupported_legal_claims": [],
            "missing_required_fields": [],
        }

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        profile = detect_claim_profile(case_context)
        cache_key = self._claim_cache_key(case_context, language)
        cached = self._claim_research_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= 15 * 60:
            LOGGER.info("KORGAN instant claim research cache HIT profile=%s", profile.code)
            return cached[1]

        started = time.perf_counter()
        # One medium source-bound pass is the latency budget for an ordinary
        # claim. No automatic second high-context search: weak support becomes
        # NEEDS_VERIFICATION, never a guessed legal proposition.
        research = await self._profiled_claim_research(
            case_context,
            language,
            search_context_size="medium",
        )
        research = _sanitize_civil_research(research)
        if not research.verified_claims or not research.source_urls:
            research.status = VerificationStatus.NEEDS_VERIFICATION
            note = (
                "Правовое основание не удалось полностью подтвердить за один source-bound проход; "
                "неподтвержденные нормы не должны утверждаться как достоверные и требуют сверки до подачи."
            )
            if note not in research.unverified_claims:
                research.unverified_claims.append(note)

        self._claim_research_cache[cache_key] = (time.monotonic(), research)
        LOGGER.info(
            "KORGAN instant claim research seconds=%.2f profile=%s verified=%d sources=%d",
            time.perf_counter() - started,
            profile.code,
            len(research.verified_claims),
            len(research.source_urls),
        )
        return research


class _InstantClaimMode(Filter):
    async def __call__(self, message: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("mode") == "instant_claim_waiting"


class _ClaimIntent(Filter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.text and is_claim_drafting_request(message.text))


async def _append_fact_once(state: FSMContext, text: str) -> None:
    value = (text or "").strip()
    if not value:
        return
    data = await state.get_data()
    facts = list(data.get("facts", []) or [])
    if not facts or str(facts[-1]).strip() != value:
        facts.append(value)
    await state.update_data(facts=facts[-20:])


def _claim_lines(draft: ClaimDraft) -> list[str]:
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


def _strip_reference_token(text: str, reference: ProvisionReference) -> str:
    """Remove only the citation label outside legal_basis, preserving the relief/fact."""
    act_pattern = {
        "ГК РК": r"(?:ГК\s*РК|Гражданск\w*\s+кодекс\w*(?:\s+РК)?)",
        "ГПК РК": r"(?:ГПК\s*РК|Гражданск\w*\s+процессуальн\w*\s+кодекс\w*(?:\s+РК)?)",
        "НК РК": r"(?:НК\s*РК|Налогов\w*\s+кодекс\w*(?:\s+РК)?)",
        "ТК РК": r"(?:ТК\s*РК|Трудов\w*\s+кодекс\w*(?:\s+РК)?)",
        "КАС РК": r"(?:КАС\s*РК)",
        "КоАП РК": r"(?:КоАП\s*РК)",
    }.get(reference.act, re.escape(reference.act))
    part = (
        rf"(?:(?:част[ьи]|ч\.)\s*{re.escape(reference.part)}\s*)?"
        if reference.part
        else r"(?:(?:част[ьи]|ч\.)\s*\d+\s*)?"
    )
    pattern = re.compile(
        rf"{part}(?:стать[ьяиюеё]\w*|ст\.)\s*{re.escape(reference.article)}\s*(?:{act_pattern})?",
        re.IGNORECASE,
    )
    cleaned = pattern.sub("", text or "")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip(" ,;:")


def _downgrade_unverified_citations(draft: ClaimDraft):
    """Turn citation defects into visible NEEDS_VERIFICATION instead of a dialogue gate."""
    report = review_lines(_claim_lines(draft))
    refs = _blocking_references(report)
    if not refs:
        return report

    # Legal reasoning keeps the article number but stops asserting its content.
    draft.legal_basis, kept = keep_accepted_provisions(list(draft.legal_basis), refs)

    # Citations outside legal_basis are not needed to preserve the factual
    # narrative or requested relief. Remove only the citation token there; every
    # original line remains in place.
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
            f"{ref.label()}: содержание не подтверждено проверенным корпусом; "
            "номер сохранён/ссылка помечена, действующую редакцию нужно сверить до подачи."
        )
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    return review_lines(_claim_lines(draft))


async def _send_claim(message: Message, state: FSMContext, draft: ClaimDraft) -> None:
    defects = enforce_legal_basis_fit(draft)
    if defects:
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        for defect in defects:
            note = f"Правовое основание требует проверки: {defect}"
            if note not in draft.verification_notes:
                draft.verification_notes.append(note)

    report = _downgrade_unverified_citations(draft)

    # NEEDS_VERIFICATION never starts a dialogue gate. Citation defects are
    # automatically downgraded. A residual defect means the rewrite itself was
    # unsafe; report it once without asking the user to choose a branch.
    if report.citations.blocking:
        LOGGER.error(
            "INSTANT_CLAIM_CITATION_BLOCK residual=%s",
            [x.as_note() for x in report.citations.blocking],
        )
        await state.update_data(mode="main", gate_issues=[], claim_draft=None)
        await message.answer(
            "Не удалось безопасно выпустить Word: одна правовая ссылка не прошла автоматическую пометку. "
            "Данные дела сохранены — повторите подготовку иска.",
            reply_markup=base_bot.MENU,
        )
        return

    if report.integrity:
        LOGGER.error(
            "INSTANT_CLAIM_INTEGRITY_BLOCK findings=%s",
            [x.as_note() for x in report.integrity],
        )
        await state.update_data(mode="main", gate_issues=[], claim_draft=None)
        await message.answer(
            "Не удалось безопасно выпустить Word из-за технического дефекта текста. "
            "Данные дела сохранены — повторите подготовку иска.",
            reply_markup=base_bot.MENU,
        )
        return

    try:
        file_bytes = build_claim_docx(draft)
    except Exception as exc:
        await base_bot._report_claim_failure(
            message,
            failure_from_exception(exc, stage=ClaimStage.RENDER),
        )
        return

    await state.update_data(mode="main", gate_issues=[], claim_draft=None, pending_fields=[])
    marker = "✅ VERIFIED" if draft.status == VerificationStatus.VERIFIED else "⚠️ NEEDS_VERIFICATION"
    checklist = report.checklist(draft.verification_notes)
    caption = f"{marker}\nГотовый проект иска — файл Word (.docx)."
    if checklist:
        caption += "\n\nПеред подачей проверьте:\n" + bullets(checklist)
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
        await state.update_data(mode="instant_claim_waiting")
        await message.answer(
            "Опишите обстоятельства дела одним сообщением — после этого сразу сформирую проект иска без анкеты по реквизитам.",
            reply_markup=base_bot.MENU,
        )
        return

    # Nothing from claim_preflight is allowed to block drafting. Every missing
    # field becomes a visible placeholder in the delivered Word project.
    gaps = inspect_claim_gaps(context).after_the_single_question()
    await state.update_data(
        mode="main",
        pending_fields=[],
        intake_repeats=0,
        critical_answered=False,
        gate_issues=[],
        claim_draft=None,
    )
    lang = await base_bot._language(state)
    await message.answer("Формирую проект иска…", reply_markup=base_bot.MENU)
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

    marked = apply_formal_placeholders(draft, gaps)
    if marked:
        for note in placeholder_notes(marked):
            if note not in draft.verification_notes:
                draft.verification_notes.append(note)
        draft.status = VerificationStatus.NEEDS_VERIFICATION

    # Missing template blocks never send the user back into intake. Fill the
    # court-facing placeholders and deliver a preliminary project instead.
    absent = missing_required_fields(draft)
    if absent:
        if not draft.claimant:
            draft.claimant = ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"]
        if not draft.defendant:
            draft.defendant = ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]
        if not draft.facts:
            draft.facts = ["[ТРЕБУЕТ УТОЧНЕНИЯ: обстоятельства дела]"]
        if not draft.requests:
            draft.requests = ["[ТРЕБУЕТ УТОЧНЕНИЯ: требование к ответчику]"]
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        note = "Перед подачей заполните обязательные поля проекта: " + ", ".join(absent)
        if note not in draft.verification_notes:
            draft.verification_notes.append(note)

    LOGGER.info(
        "INSTANT_CLAIM_READY seconds=%.2f status=%s",
        time.perf_counter() - started,
        draft.status.value,
    )
    await _send_claim(message, state, draft)


@router.message(Command("claim"))
@router.message(F.text == "📄 Подготовить иск")
async def instant_claim_button(message: Message, state: FSMContext) -> None:
    await _generate_now(message, state)


@router.message(_InstantClaimMode(), F.text)
async def instant_claim_description(message: Message, state: FSMContext) -> None:
    await _append_fact_once(state, message.text or "")
    await _generate_now(message, state)


@router.message(_ClaimIntent(), F.text)
async def instant_claim_from_one_message(message: Message, state: FSMContext) -> None:
    # A complete request such as «Хочу подготовить иск. Истец: ... Ответчик: ...»
    # is itself case material; persist it before building the context.
    if (message.text or "").strip() != "📄 Подготовить иск":
        await _append_fact_once(state, message.text or "")
    await _generate_now(message, state)
