"""Final additive filing guard for KORGAN statements of claim.

The existing production claim generator remains authoritative.  This module is
installed last and only prevents a court-facing Word file from being released
when the final draft still has a substantive legal defect.  Missing filing
requisites (for example an exact court name, a physical claimant's date of
birth, or a state-duty calculation) remain one-shot project placeholders and
are surfaced as filing actions instead of restarting a questionnaire.

The structural checklist mirrors the currently verified requirements of
Articles 148-149 GPK RK.  Exact substantive law is never hard-coded here: each
claim remedy must still be supported by source-bound VERIFIED research/current
Adilet corpus through the existing release pipeline.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from korgan.claim_quality_hotfix import FILING_ACTION_PREFIX, _patched_assess_document_quality
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import sanitize_prayer_requests
from korgan.request_basis_coverage import ensure_request_basis_coverage

LOGGER = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(
    r"\[(?:ТРЕБУЕТ\s+УТОЧНЕНИЯ|ТРЕБУЕТ\s+ПРОВЕРКИ|ТРЕБУЕТ\s+ДОБАВИТЬ|"
    r"НАҚТЫЛАУ\s+ҚАЖЕТ|ТЕКСЕРУ\s+ҚАЖЕТ)[^\]]*\]",
    re.IGNORECASE,
)
_INTERNAL_LEGAL_RE = re.compile(
    r"(?i)(?:\[\s*ТРЕБУЕТ\s+ПРОВЕРКИ\s*:|NEEDS_VERIFICATION|KORGAN\s+QA\s+STATUS|"
    r"source-bound|содержание\s+нормы\s+не\s+воспроизводится\s+до\s+сверки|"
    r"подлежит\s+сверке\s+по\s+официальному\s+источнику)"
)
_BROKEN_BASIS_RE = re.compile(
    r"(?i)(?:Правовое\s+основание\s*:\s*(?:(?:пункт|статья)\s*\d+(?:-\d+)?\s+)?Республики\s+Казахстан\b|"
    r"На\s+основании\s+Республики\s+Казахстан\b|"
    r"установленн\w*\s+Республики\s+Казахстан\b)"
)
_ARTICLE_RE = re.compile(r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*\d+(?:-\d+)?|\d+(?:-\d+)?-бап")
_ENTITY_RE = re.compile(
    r"(?i)\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ОО)\b|\bБИН\b|"
    r"товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|акционерн\w*\s+обществ\w*"
)
_MONEY_RE = re.compile(r"(?<!\d)\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:тенге|тг\b|₸)", re.IGNORECASE)
_PRETRIAL_REQUIRED_RE = re.compile(
    r"(?i)(?:обязательн\w*.{0,80}(?:досудебн\w*|внесудебн\w*|согласительн\w*\s+комисс)|"
    r"(?:досудебн\w*|внесудебн\w*|согласительн\w*\s+комисс).{0,80}обязательн\w*)"
)
_PRETRIAL_DONE_RE = re.compile(
    r"(?i)(?:претензи\w*|согласительн\w*\s+комисс|досудебн\w*\s+(?:обращ|урегулир)|"
    r"направил\w*.{0,80}(?:требован|уведомлен)|получил\w*.{0,80}(?:претензи|требован)|"
    r"сотқа\s+дейінгі\s+талап|келісу\s+комиссия)"
)

# Quality defects that are allowed only as explicit pre-filing actions.  They do
# not lower the legal substance standard, but the client must fill/check them
# before actual filing.
_FILING_ONLY_QUALITY_RE = re.compile(
    r"(?i)(?:незаполненные\s+обязательные/проверочные\s+поля|"
    r"не\s+определено\s+конкретное\s+наименование\s+суда|"
    r"наименование\s+суда\s+не\s+подтверждено|"
    r"не\s+определена\s+госпошлина|"
    r"точное\s+наименование\s+суда|"
    r"госпошлин|дата\s+рождения|\bии[нм]\b|адрес\w*)"
)


def _lines(values: list[str]) -> str:
    return "\n".join(str(value or "") for value in values)


def _has_specific_placeholder(values: list[str], *tokens: str) -> bool:
    text = _lines(values).lower()
    return any(token.lower() in text and "[" in text for token in tokens)


def _add_filing_action(draft: ClaimDraft, message: str) -> None:
    marker = FILING_ACTION_PREFIX + message
    if marker not in draft.verification_notes:
        draft.verification_notes.append(marker)


def add_gpk_filing_actions(case_context: str, research: LegalResearch, draft: ClaimDraft) -> list[str]:
    """Add client-actionable Article 148/149 filing prerequisites without a form."""
    before = set(draft.verification_notes)
    court = (draft.court or "").strip().lower()
    if not court or "требует уточнения" in court or "нақтылау қажет" in court or "общей юрисдикции" in court:
        _add_filing_action(draft, "до подачи указать и проверить точное наименование компетентного суда и территориальную подсудность.")

    claimant = _lines(draft.claimant)
    defendant = _lines(draft.defendant)
    if claimant:
        if not _ENTITY_RE.search(claimant):
            lower = claimant.lower()
            if "дата рождения" not in lower and "туған" not in lower:
                _add_filing_action(draft, "для истца-физлица заполнить дату рождения, требуемую для подачи иска.")
            if "иин" not in lower and not re.search(r"(?<!\d)\d{12}(?!\d)", claimant):
                _add_filing_action(draft, "для истца-физлица заполнить ИИН перед подачей.")
            if not re.search(r"(?i)(?:адрес|мест[оа]\s+жительств|тұрғылықты\s+жер|мекенжай)", claimant):
                _add_filing_action(draft, "для истца указать место жительства/адрес перед подачей.")
        else:
            lower = claimant.lower()
            if "бин" not in lower and not re.search(r"(?<!\d)\d{12}(?!\d)", claimant):
                _add_filing_action(draft, "для истца-юрлица заполнить БИН перед подачей.")
            if not re.search(r"(?i)(?:адрес|мест[оа]\s+нахожд|мекенжай)", claimant):
                _add_filing_action(draft, "для истца-юрлица указать место нахождения перед подачей.")
            if not re.search(r"(?i)(?:банковск\w*\s+реквизит|iban|иик|банк)", claimant):
                _add_filing_action(draft, "для истца-юрлица заполнить банковские реквизиты перед подачей.")

    if defendant:
        if not re.search(r"(?i)(?:адрес|мест[оа]\s+(?:жительств|нахожд)|тұрғылықты\s+жер|мекенжай)", defendant):
            _add_filing_action(draft, "указать известное место жительства/нахождения ответчика и проверить подсудность.")

    if _MONEY_RE.search(_lines(draft.requests)) and not (draft.price_of_claim or "").strip():
        _add_filing_action(draft, "перед подачей указать цену денежного иска и проверить расчет взыскиваемых сумм.")

    duty = (draft.state_duty or "").lower()
    if not duty or "требует расч" in duty or "есептеу қажет" in duty:
        _add_filing_action(draft, "перед подачей рассчитать госпошлину либо подтвердить применимую льготу/основание отсрочки.")

    if not [x for x in draft.attachments if str(x).strip()]:
        _add_filing_action(draft, "приложить документы, подтверждающие обстоятельства, на которых основаны требования.")

    procedure_text = "\n".join([*research.procedural_requirements, *research.verified_claims])
    if _PRETRIAL_REQUIRED_RE.search(procedure_text) and not _PRETRIAL_DONE_RE.search(case_context or ""):
        _add_filing_action(draft, "до подачи выполнить и подтвердить обязательный досудебный/внесудебный порядок, установленный для этого спора.")

    return [
        str(note)[len(FILING_ACTION_PREFIX):].strip()
        for note in draft.verification_notes
        if str(note).startswith(FILING_ACTION_PREFIX) and note not in before
    ]


def substantive_release_defects(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> list[str]:
    """Return reasons that make the legal substance unsafe for client Word."""
    sanitize_prayer_requests(draft)
    missing_basis = ensure_request_basis_coverage(case_context, draft, research)
    defects: list[str] = []

    if not draft.requests:
        defects.append("просительная часть пуста после финальной очистки")

    for section_name, values in (
        ("facts", draft.facts),
        ("legal_basis", draft.legal_basis),
        ("requests", draft.requests),
    ):
        text = _lines(values)
        if _INTERNAL_LEGAL_RE.search(text):
            defects.append(f"в разделе {section_name} остался внутренний verification-текст")
        if section_name in {"facts", "requests"} and _PLACEHOLDER_RE.search(text):
            defects.append(f"в содержательной части {section_name} остался незаполненный юридический элемент")

    body = "\n".join([*draft.legal_basis, *draft.requests])
    if _BROKEN_BASIS_RE.search(body):
        defects.append("обнаружено поврежденное правовое основание в судебном тексте")

    if missing_basis:
        defects.append("не каждое самостоятельное требование имеет собственную VERIFIED правовую опору")

    if not research.verified_claims:
        defects.append("отсутствует source-bound VERIFIED правовая основа текущего дела")
    if not draft.legal_basis or not _ARTICLE_RE.search(_lines(draft.legal_basis)):
        defects.append("в финальном правовом обосновании нет конкретной проверенной нормы")

    # Reuse the existing >=8.5 quality engine, but do not turn formal Article
    # 148/149 requisites into a second questionnaire.  Any remaining non-filing
    # defect after the normal repair pass is a release blocker.
    quality = _patched_assess_document_quality("claim", case_context, research, draft)
    nonfiling = [
        str(item)
        for item in quality.repair_issues()
        if not _FILING_ONLY_QUALITY_RE.search(str(item))
        and not str(item).startswith(FILING_ACTION_PREFIX)
    ]
    if quality.score < 8.5 and nonfiling:
        defects.append("финальный юридический quality-gate ниже 8.5 по содержательным причинам")
        defects.extend(nonfiling[:3])

    return list(dict.fromkeys(defects))


def install_court_ready_claim_guard() -> None:
    """Wrap the already installed claim sender; do not replace claim generation."""
    from korgan import bot as base_bot
    from korgan import universal_claim_runtime as runtime

    if getattr(runtime, "_court_ready_claim_guard_installed", False):
        return

    original_send = runtime._send_claim

    async def guarded_send(
        message: Any,
        state: Any,
        *,
        context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> None:
        add_gpk_filing_actions(context, research, draft)
        defects = substantive_release_defects(context, research, draft)
        if defects:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            LOGGER.error("COURT_READY_CLAIM_BLOCK defects=%s", defects[:8])
            await state.update_data(mode="main", gate_issues=[], claim_draft=None, pending_fields=[])
            await message.answer(
                "Иск пока не прошёл финальную юридическую проверку KORGAN, поэтому Word-файл не выдан. "
                "Система не будет отдавать клиенту судебный документ с неполным правовым основанием или повреждённой просительной частью. "
                "Добавьте недостающие факты/доказательства, если они есть, и повторите подготовку иска.",
                reply_markup=base_bot.MENU,
            )
            return
        await original_send(message, state, context=context, research=research, draft=draft)

    runtime._send_claim = guarded_send
    runtime._court_ready_claim_guard_installed = True
    LOGGER.info("Installed KORGAN court-ready claim release guard")
