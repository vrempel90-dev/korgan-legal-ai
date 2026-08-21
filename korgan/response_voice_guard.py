from __future__ import annotations

import logging
import re
from typing import Iterable

from korgan.legal_types import VerificationStatus
from korgan.pretrial_response import (
    PretrialResponseDraft,
    _PRETRIAL_RESPONSE_SCHEMA,
    normalize_pretrial_response,
)
from korgan.response_legal import _RESPONSE_DRAFT_SCHEMA
from korgan.response_types import ResponseToClaimDraft

LOGGER = logging.getLogger(__name__)

# These patterns are intentionally narrow. They are checked only in the fields
# where the author states its own position. Third-person references to the
# claimant / sender of the demand remain valid in summaries and legal analysis.
_THIRD_PERSON_SELF = (
    re.compile(r"(?i)\bсо\s+стороны\s+(?:ответчик\w*|получател\w*|адресат\w*|ТОО\b|АО\b|ИП\b)"),
    re.compile(
        r"(?i)\bответчик\w*\s+(?:сообщает|указывает|считает|полагает|возражает|"
        r"не\s+призна[её]т|не\s+может|просит|выражает|готов)\b"
    ),
    re.compile(
        r"(?i)\b(?:получател\w*|адресат\w*)\s+(?:претензи\w*\s+)?"
        r"(?:сообщает|указывает|считает|полагает|возражает|не\s+призна[её]т|"
        r"не\s+может|просит|выражает|готов)\b"
    ),
    re.compile(
        r"(?i)\b(?:ТОО|АО|ИП)\s+[«\"].{1,140}?[»\"]\s+"
        r"(?:сообщает|указывает|считает|полагает|возражает|не\s+призна[её]т|"
        r"не\s+может|просит|выражает|готов)\b"
    ),
)

_META_REASONING = (
    re.compile(r"(?i)\bотсутствует\s+подтвержденн\w*\s+позици\w*"),
    re.compile(r"(?i)\bнет\s+подтвержденн\w*\s+согласия\b"),
    re.compile(r"(?i)\bправов\w*\s+оценк\w*.{0,50}\bне\s+проведен\w*"),
    re.compile(r"(?i)\bотсутствует\s+согласованн\w*\s+пониман\w*"),
    re.compile(r"(?i)\bпозици\w*.{0,40}\bне\s+определен\w*"),
    re.compile(r"(?i)\bвыработк\w*.{0,40}\bсогласованн\w*\s+позици\w*"),
)


def own_voice_issues(lines: Iterable[str]) -> list[str]:
    text = "\n".join(str(item or "").strip() for item in lines if str(item or "").strip())
    if not text:
        return []

    issues: list[str] = []
    if any(pattern.search(text) for pattern in _THIRD_PERSON_SELF):
        issues.append("позиция автора изложена от третьего лица вместо прямой позиции стороны")
    if any(pattern.search(text) for pattern in _META_REASONING):
        issues.append("в тело документа попало внутреннее рассуждение о неопределённости позиции")
    return issues


def _pretrial_stance_lines(draft: PretrialResponseDraft) -> list[str]:
    return [*draft.position, *draft.objections, *draft.response_terms]


def _claim_response_stance_lines(draft: ResponseToClaimDraft) -> list[str]:
    lines = [*draft.position]
    for objection in draft.objections:
        lines.extend(objection.body_lines())
    lines.extend(draft.requests)
    return lines


def _voice_rules(language: str, document: str) -> str:
    if language == "kk":
        return (
            f"8. {document} автор тараптың атынан тікелей жазылсын. Автордың өз ұстанымы үшін үшінші жақтағы "
            "баяндауды қолданба. Белгісіз немесе расталмаған деректерді құжат мәтінінде ішкі талқылау ретінде жазба; "
            "олар тек verification_notes ішінде қалсын. Қарсы тарап туралы үшінші жақпен жазуға болады. "
            "FACT LOCK және LAW LOCK қатаң сақталсын."
        )
    return (
        f"8. {document} должен говорить НАПРЯМУЮ ОТ ИМЕНИ АВТОРА документа. В полях position, objections и "
        "response_terms/requests используй деловые формы «сообщаем», «не признаём», «возражаем», «считаем», "
        "«просим», «готовы рассмотреть» либо нейтральные прямые формулировки без называния автора в третьем лице. "
        "Запрещены формулы «со стороны ТОО...», «ответчик считает/сообщает», «ТОО ... не может», когда речь идёт "
        "о собственной позиции автора. Не включай в тело документа внутренние рассуждения вроде «позиция не "
        "определена», «нет подтверждённого согласия», «правовая оценка не проведена». Неизвестные сведения оставляй "
        "только в verification_notes. Третье лицо допустимо для описания требований и доводов ПРОТИВНОЙ стороны. "
        "FACT LOCK и LAW LOCK обязательны: не меняй факты, суммы, даты, стороны, доказательства и VERIFIED-нормы."
    )


async def _repair_pretrial_voice(
    service: object,
    draft: PretrialResponseDraft,
    *,
    case_context: str,
    research: object,
    language: str,
    issues: list[str],
) -> PretrialResponseDraft:
    current = {
        "title": draft.title,
        "sender": draft.sender,
        "recipient": draft.recipient,
        "reference": draft.reference,
        "claim_summary": draft.claim_summary,
        "position": draft.position,
        "objections": draft.objections,
        "legal_basis": draft.legal_basis,
        "response_terms": draft.response_terms,
        "attachments": draft.attachments,
        "verification_notes": draft.verification_notes,
    }
    payload = await service._quality_repair(  # type: ignore[attr-defined]
        schema_name="korgan_voice_pretrial_response",
        schema=_PRETRIAL_RESPONSE_SCHEMA,
        case_context=case_context,
        research=research,
        current_payload=current,
        issues=issues,
        language=language,
        document_label="отзыв на претензию",
        extra_rules=_voice_rules(language, "Отзыв на претензию"),
    )
    repaired = PretrialResponseDraft(
        status=getattr(research, "status", VerificationStatus.NEEDS_VERIFICATION),
        source_urls=list(getattr(research, "source_urls", []) or []),
        **payload,
    )
    normalize_pretrial_response(repaired)
    return repaired


async def _repair_claim_response_voice(
    service: object,
    draft: ResponseToClaimDraft,
    *,
    case_context: str,
    research: object,
    language: str,
    issues: list[str],
) -> ResponseToClaimDraft:
    current = {
        "title": draft.title,
        "court": draft.court,
        "case_number": draft.case_number,
        "claimant": draft.claimant,
        "defendant": draft.defendant,
        "claim_summary": draft.claim_summary,
        "position": draft.position,
        "objections": [
            {"text": item.text, "subclauses": item.subclauses, "prose": item.prose}
            for item in draft.objections
        ],
        "legal_basis": draft.legal_basis,
        "requests": draft.requests,
        "attachments": draft.attachments,
        "verification_notes": draft.verification_notes,
    }
    payload = await service._quality_repair(  # type: ignore[attr-defined]
        schema_name="korgan_voice_response_to_claim",
        schema=_RESPONSE_DRAFT_SCHEMA,
        case_context=case_context,
        research=research,
        current_payload=current,
        issues=issues,
        language=language,
        document_label="отзыв на иск",
        extra_rules=_voice_rules(language, "Отзыв на иск"),
    )
    return ResponseToClaimDraft(
        status=getattr(research, "status", VerificationStatus.NEEDS_VERIFICATION),
        source_urls=list(getattr(research, "source_urls", []) or []),
        **payload,
    )


def install_response_voice_guard() -> None:
    """Install a voice-only repair for the two defensive document types.

    No claim, pre-trial demand, contract, consultation, routing or payment logic
    is modified here.
    """
    from korgan.pretrial_response import PretrialResponseProductionService

    if getattr(PretrialResponseProductionService, "_response_voice_guard_installed", False):
        return

    original_pretrial = PretrialResponseProductionService.draft_pretrial_response
    original_claim_response = PretrialResponseProductionService.draft_response_to_claim

    async def guarded_pretrial(self, case_context, research, language="ru"):
        draft = await original_pretrial(self, case_context, research, language=language)
        issues = own_voice_issues(_pretrial_stance_lines(draft))
        if not issues:
            return draft
        LOGGER.warning("RESPONSE_VOICE_REPAIR kind=pretrial_response issues=%s", issues)
        repaired = await _repair_pretrial_voice(
            self,
            draft,
            case_context=case_context,
            research=research,
            language=language,
            issues=issues,
        )
        remaining = own_voice_issues(_pretrial_stance_lines(repaired))
        if remaining:
            raise RuntimeError("pretrial response voice repair failed: " + "; ".join(remaining))
        return repaired

    async def guarded_claim_response(self, case_context, research, language="ru"):
        draft = await original_claim_response(self, case_context, research, language=language)
        issues = own_voice_issues(_claim_response_stance_lines(draft))
        if not issues:
            return draft
        LOGGER.warning("RESPONSE_VOICE_REPAIR kind=response_to_claim issues=%s", issues)
        repaired = await _repair_claim_response_voice(
            self,
            draft,
            case_context=case_context,
            research=research,
            language=language,
            issues=issues,
        )
        remaining = own_voice_issues(_claim_response_stance_lines(repaired))
        if remaining:
            raise RuntimeError("response to claim voice repair failed: " + "; ".join(remaining))
        return repaired

    PretrialResponseProductionService.draft_pretrial_response = guarded_pretrial  # type: ignore[method-assign]
    PretrialResponseProductionService.draft_response_to_claim = guarded_claim_response  # type: ignore[method-assign]
    PretrialResponseProductionService._response_voice_guard_installed = True  # type: ignore[attr-defined]
    LOGGER.info("KORGAN response voice guard installed for pretrial response and response to claim")
