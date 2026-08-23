from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from korgan import document_quality, universal_quality_service
from korgan.fast_v2_production_legal import _normalize_state_duty_request
from korgan.legal_calc import NEEDS_CALCULATION_MARKER, format_kzt, gosposhlina_line
from korgan.legal_types import ClaimDraft, ContractDraft, LegalResearch, VerificationStatus
from korgan.pretrial import (
    PretrialDraft,
    PretrialProductionService,
    _PRETRIAL_SCHEMA,
    normalize_pretrial,
    pretrial_quality_issues,
)
from korgan.pretrial_response import (
    PretrialResponseDraft,
    PretrialResponseProductionService,
    _PRETRIAL_RESPONSE_SCHEMA,
    normalize_pretrial_response,
    pretrial_response_quality_issues,
)
from korgan.response_types import ResponseToClaimDraft
from korgan.stable_legal_release import StableLegalProductionService
from korgan.universal_quality_service import UniversalQualityProductionService

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
TARGET_READY_SCORE = 10.0

_INSTRUCTION_TAIL_RE = re.compile(
    r"(?i)(?:[,;:\s—-]*(?:при\s+наличии\s+(?:указать|заполнить)|"
    r"если\s+(?:они\s+)?известн\w*(?:\s+истцу|\s+стороне)?\s*[—-]?\s*(?:указать|заполнить)|"
    r"указать\s+при\s+наличии))\s*\.?$"
)
_EMPTY_LABEL_RE = re.compile(
    r"(?i)^(?:телефон|электронн\w*\s+адрес|e-?mail|банковск\w*\s+реквизит\w*|"
    r"банковск\w*\s+реквизит\w*\s*,\s*телефон\s*,\s*электронн\w*\s+адрес|"
    r"телефон\s*,\s*электронн\w*\s+адрес)\s*:?$"
)
_INTERNAL_SCORE_PREFIXES = (
    "KORGAN QUALITY",
    "SENIOR_PREFLIGHT_SCORE:",
)
_STATE_DUTY_REQUEST_RE = re.compile(
    r"(?i)(?:\bгоспошлин\w*\b|\bгосударственн\w*\s+пошлин\w*\b|мемлекеттік\s+баж)"
)
_PENALTY_RE = re.compile(
    r"(?i)(?:договорн\w*\s+неустойк\w*|неустойк\w*|пен[яию]\b|штраф\w*|"
    r"тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)"
)
_PENALTY_EXPLICIT_DEMAND_RE = re.compile(
    r"(?i)(?:взыск\w*|прошу\b|требу\w*|хочу\s+взыск\w*|өндір\w*|талап\s+ет\w*|сұрай\w*)"
)
_PENALTY_AMOUNT_SIGNAL_RE = re.compile(
    r"(?i)(?:взыск\w*|требу\w*|составил\w*|начисл\w*|итогов\w*|в\s+размере|в\s+том\s+числе|"
    r"өндір\w*|мөлшер\w*|сомас\w*)"
)
_PENALTY_CAP_RE = re.compile(r"(?i)(?:не\s+более|лимит|предельн\w*|максимальн\w*|аспау\w*)")
_MONEY_RE = re.compile(
    r"(?<!\d)(\d[\d\s\u00a0]*(?:[.,]\d{1,2})?)\s*(?:тенге|теңге|тг\b|₸)",
    re.IGNORECASE,
)


def _parse_money(raw: str) -> int:
    value = re.sub(r"[\s\u00a0]", "", raw).replace(",", ".")
    try:
        return round(float(value))
    except ValueError:
        return 0


def _clean_instruction_line(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    cleaned = _INSTRUCTION_TAIL_RE.sub("", text).strip(" ,;:-—")
    if not cleaned or _EMPTY_LABEL_RE.fullmatch(cleaned):
        return ""
    return cleaned


def _clean_list(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        cleaned = _clean_instruction_line(str(value))
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def sanitize_draft_instructions(draft: Any) -> None:
    """Remove model-to-user instructions from filing-facing party/requisite blocks.

    Unknown client data stays unknown; the guard removes only instructions such as
    «при наличии указать». It never invents a phone, e-mail, bank account or party.
    """
    for attr in (
        "claimant", "defendant", "party_a", "party_b", "requisites_a", "requisites_b",
        "sender", "recipient", "plaintiff",
    ):
        if hasattr(draft, attr):
            current = getattr(draft, attr)
            if isinstance(current, list):
                setattr(draft, attr, _clean_list([str(item) for item in current]))


def _strip_internal_score_notes(draft: Any) -> None:
    notes = list(getattr(draft, "verification_notes", []) or [])
    setattr(
        draft,
        "verification_notes",
        [
            str(note)
            for note in notes
            if not str(note).startswith(_INTERNAL_SCORE_PREFIXES)
        ],
    )


def _claim_context_with_role(case_context: str, draft: ClaimDraft) -> str:
    """Give deterministic calculators the already-extracted claimant role.

    Uploaded contracts/pre-trial demands often label the same company as Supplier,
    Contractor or Creditor rather than literally «Истец». The draft has already
    resolved the litigation role, so using that role here prevents a false
    [ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ] without changing any factual party data.
    """
    claimant = "\n".join(str(item) for item in draft.claimant if str(item).strip())
    return f"{case_context}\n\nИстец:\n{claimant}" if claimant else case_context


def _localize_state_duty_request(draft: ClaimDraft, language: str) -> None:
    if language != "kk":
        return
    duty = (draft.state_duty or "").strip()
    if not duty or duty.startswith("["):
        return
    amount = duty.split("(", 1)[0].strip().replace(" тенге", " теңге")
    draft.requests = [
        request for request in draft.requests if not _STATE_DUTY_REQUEST_RE.search(str(request))
    ]
    if amount:
        draft.requests.append(
            "Жауапкерден талап қоюшының пайдасына мемлекеттік бажды төлеуге жұмсалған "
            f"шығыстарды {amount} мөлшерінде өндіріп алу."
        )


def apply_state_duty_from_draft(
    case_context: str,
    draft: ClaimDraft,
    language: str = "ru",
) -> None:
    from korgan import production_legal

    draft.state_duty = gosposhlina_line(_claim_context_with_role(case_context, draft), draft.price_of_claim)
    if draft.state_duty == NEEDS_CALCULATION_MARKER:
        if production_legal.STATE_DUTY_NOTE not in draft.verification_notes:
            draft.verification_notes.append(production_legal.STATE_DUTY_NOTE)
        return

    draft.verification_notes = [
        note for note in draft.verification_notes
        if not production_legal._is_stale_duty_note(str(note))
    ]
    _normalize_state_duty_request(draft)
    _localize_state_duty_request(draft, language)


def _amount_occurrences(text: str) -> list[tuple[int, int, int]]:
    result: list[tuple[int, int, int]] = []
    for match in _MONEY_RE.finditer(text or ""):
        amount = _parse_money(match.group(1))
        if amount > 0:
            result.append((amount, match.start(), match.end()))
    return result


def _source_penalty_demand_segments(case_context: str) -> list[str]:
    """Return only user/upload source segments that explicitly demand a penalty.

    Mentioning a contractual penalty clause or a model-generated claim title is not
    enough. This protects the client from KORGAN silently adding a remedy the source
    materials never asked to pursue.
    """
    result: list[str] = []
    for segment in re.split(r"(?<=[.!?])\s+|\n+", case_context or ""):
        value = segment.strip()
        if not value or not _PENALTY_RE.search(value):
            continue
        if "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА:" in value or _PENALTY_EXPLICIT_DEMAND_RE.search(value):
            result.append(value)
    return result


def _penalty_amount(case_context: str) -> int | None:
    """Find the penalty amount from source context, never from generated draft text.

    Candidate selection is deterministic and proximity-based. Sentences describing
    «не более 10% / лимит» are heavily penalized so a contractual cap is not
    mistaken for the amount actually demanded by the client.
    """
    candidates: list[tuple[int, int]] = []
    explicit_segments = _source_penalty_demand_segments(case_context)
    if not explicit_segments:
        return None

    # Search the whole source context so a marker can state the remedy while the
    # immediately adjacent source sentence contains its already-calculated amount.
    segments = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n+", case_context or "") if segment.strip()]
    for segment in segments:
        terms = list(_PENALTY_RE.finditer(segment))
        if not terms:
            continue
        for amount, start, _end in _amount_occurrences(segment):
            distance = min(abs(start - term.start()) for term in terms)
            score = max(0, 8 - distance // 20)
            if segment in explicit_segments:
                score += 8
            if _PENALTY_AMOUNT_SIGNAL_RE.search(segment):
                score += 4
            if "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА:" in segment:
                score += 7
            if _PENALTY_CAP_RE.search(segment):
                score -= 12
            candidates.append((score, amount))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    score, amount = candidates[0]
    return amount if score > 0 else None


def _penalty_should_be_in_prayer(case_context: str, draft: ClaimDraft) -> bool:
    if _PENALTY_RE.search("\n".join(draft.requests)):
        return False
    return bool(_source_penalty_demand_segments(case_context))


def _render_penalty_request(amount: int, language: str) -> str:
    amount_text = format_kzt(amount)
    if language == "kk":
        amount_text = amount_text.replace(" тенге", " теңге")
        return (
            "Жауапкерден талап қоюшының пайдасына шарттық тұрақсыздық айыбын "
            f"{amount_text} мөлшерінде өндіріп алу."
        )
    return f"Взыскать с ответчика в пользу истца договорную неустойку в размере {amount_text}."


def complete_claim_relief_from_materials(
    case_context: str,
    draft: ClaimDraft,
    *,
    language: str = "ru",
) -> bool:
    """Restore a secondary penalty only when source materials explicitly claim it."""
    if not _penalty_should_be_in_prayer(case_context, draft):
        return False
    amount = _penalty_amount(case_context)
    if amount is None:
        return False
    draft.requests.append(_render_penalty_request(amount, language))
    LOGGER.info("UNIVERSAL_WORD_QUALITY restored_penalty amount=%s language=%s", amount, language)
    return True


def finalize_claim_for_release(
    case_context: str,
    draft: ClaimDraft,
    *,
    language: str = "ru",
) -> None:
    from korgan.professional_claim_finalizer import _recalculate_price

    sanitize_draft_instructions(draft)
    complete_claim_relief_from_materials(case_context, draft, language=language)
    _recalculate_price(draft)
    apply_state_duty_from_draft(case_context, draft, language=language)
    _strip_internal_score_notes(draft)


def _pretrial_payload(draft: PretrialDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "sender": list(draft.sender),
        "recipient": list(draft.recipient),
        "facts": list(draft.facts),
        "legal_basis": list(draft.legal_basis),
        "demands": list(draft.demands),
        "deadline": draft.deadline,
        "consequences": list(draft.consequences),
        "attachments": list(draft.attachments),
        "verification_notes": list(draft.verification_notes),
    }


def _pretrial_response_payload(draft: PretrialResponseDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "sender": list(draft.sender),
        "recipient": list(draft.recipient),
        "reference": draft.reference,
        "claim_summary": list(draft.claim_summary),
        "position": list(draft.position),
        "objections": list(draft.objections),
        "legal_basis": list(draft.legal_basis),
        "response_terms": list(draft.response_terms),
        "attachments": list(draft.attachments),
        "verification_notes": list(draft.verification_notes),
    }


def _refresh_issue_notes(notes: list[str], old_issues: list[str], new_issues: list[str]) -> list[str]:
    old = set(str(item) for item in old_issues)
    result = [str(note) for note in notes if str(note) not in old]
    for issue in new_issues:
        if issue not in result:
            result.append(issue)
    return result


def _preliminary_after_repair_failure(draft: Any, issues: list[str]) -> Any:
    draft.status = VerificationStatus.NEEDS_VERIFICATION
    notes = list(getattr(draft, "verification_notes", []) or [])
    for issue in issues:
        if issue not in notes:
            notes.append(issue)
    draft.verification_notes = notes
    return draft


async def repair_pretrial_to_target(
    self: Any,
    original: Callable[..., Awaitable[PretrialDraft]],
    case_context: str,
    research: LegalResearch,
    language: str = "ru",
) -> PretrialDraft:
    draft = await original(self, case_context, research, language=language)
    sanitize_draft_instructions(draft)
    first = pretrial_quality_issues(draft, research)
    if not first:
        return draft

    try:
        repaired_payload = await self._quality_repair(
            schema_name="korgan_10_of_10_pretrial",
            schema=_PRETRIAL_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=_pretrial_payload(draft),
            issues=first,
            language=language,
            document_label="досудебную претензию",
            extra_rules=(
                "8. Доведи документ до полноценного делового письма: стороны, факты нарушения, конкретные требования, "
                "срок только при фактической/VERIFIED опоре, последствия, приложения и VERIFIED правовое основание.\n"
                "9. Не оставляй инструкции пользователю, пустые служебные поля или внутренние [ТРЕБУЕТ ...] маркеры в тексте документа."
            ),
        )
        repaired = PretrialDraft(status=research.status, source_urls=list(research.source_urls), **repaired_payload)
        normalize_pretrial(repaired)
        sanitize_draft_instructions(repaired)
        second = pretrial_quality_issues(repaired, research)
        repaired.verification_notes = _refresh_issue_notes(repaired.verification_notes, first, second)
        repaired.status = (
            VerificationStatus.VERIFIED
            if not second and research.status is VerificationStatus.VERIFIED and not repaired.verification_notes
            else VerificationStatus.NEEDS_VERIFICATION
        )
        LOGGER.info(
            "UNIVERSAL_WORD_QUALITY kind=pretrial target=10 issues_before=%d issues_after=%d",
            len(first),
            len(second),
        )
        return repaired
    except Exception:
        LOGGER.exception(
            "UNIVERSAL_WORD_QUALITY repair_failed kind=pretrial; preserving original PRELIMINARY Word"
        )
        return _preliminary_after_repair_failure(draft, first)


async def repair_pretrial_response_to_target(
    self: Any,
    original: Callable[..., Awaitable[PretrialResponseDraft]],
    case_context: str,
    research: LegalResearch,
    language: str = "ru",
) -> PretrialResponseDraft:
    draft = await original(self, case_context, research, language=language)
    sanitize_draft_instructions(draft)
    first = pretrial_response_quality_issues(draft, research)
    if not first:
        return draft

    try:
        repaired_payload = await self._quality_repair(
            schema_name="korgan_10_of_10_pretrial_response",
            schema=_PRETRIAL_RESPONSE_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=_pretrial_response_payload(draft),
            issues=first,
            language=language,
            document_label="ответ на досудебную претензию",
            extra_rules=(
                "8. Отрази каждое существенное требование исходной претензии и дай на него позицию только из материалов клиента.\n"
                "9. Документ должен содержать связные возражения/условия ответа, VERIFIED право при его наличии и реальные приложения.\n"
                "10. Не оставляй инструкции пользователю, пустые служебные поля или внутренние [ТРЕБУЕТ ...] маркеры в тексте документа."
            ),
        )
        repaired = PretrialResponseDraft(status=research.status, source_urls=list(research.source_urls), **repaired_payload)
        normalize_pretrial_response(repaired)
        sanitize_draft_instructions(repaired)
        second = pretrial_response_quality_issues(repaired, research)
        repaired.verification_notes = _refresh_issue_notes(repaired.verification_notes, first, second)
        repaired.status = (
            VerificationStatus.VERIFIED
            if not second and research.status is VerificationStatus.VERIFIED and not repaired.verification_notes
            else VerificationStatus.NEEDS_VERIFICATION
        )
        LOGGER.info(
            "UNIVERSAL_WORD_QUALITY kind=pretrial_response target=10 issues_before=%d issues_after=%d",
            len(first),
            len(second),
        )
        return repaired
    except Exception:
        LOGGER.exception(
            "UNIVERSAL_WORD_QUALITY repair_failed kind=pretrial_response; preserving original PRELIMINARY Word"
        )
        return _preliminary_after_repair_failure(draft, first)


def install_universal_word_quality_guard() -> None:
    """Install one 10/10 target without turning QA into a Word-delivery kill switch."""
    global _INSTALLED
    if _INSTALLED:
        return

    # Existing UniversalQualityProductionService already performs one bounded
    # repair for claim/contract/response. Raising the target makes that same
    # mechanism repair every deterministic defect instead of stopping at 8.5.
    document_quality.MIN_READY_SCORE = TARGET_READY_SCORE
    universal_quality_service.MIN_READY_SCORE = TARGET_READY_SCORE

    # Make the common AI repair itself fail-open. Claim/contract/response already
    # had a quality repair loop before this guard; raising the threshold must not
    # make a transient repair failure suppress an otherwise renderable Word file.
    original_quality_repair = UniversalQualityProductionService._quality_repair

    async def resilient_quality_repair(self: UniversalQualityProductionService, **kwargs: Any) -> dict[str, Any]:
        try:
            return await original_quality_repair(self, **kwargs)
        except Exception:
            LOGGER.exception(
                "UNIVERSAL_WORD_QUALITY common_repair_failed document=%s; using original payload as PRELIMINARY",
                kwargs.get("document_label", "unknown"),
            )
            current = kwargs.get("current_payload")
            if not isinstance(current, dict):
                raise
            return dict(current)

    UniversalQualityProductionService._quality_repair = resilient_quality_repair  # type: ignore[assignment]

    # The production claim calculator is imported by value into fast_v2, so patch
    # both globals. Calls from existing deterministic QA remain RU-compatible;
    # the final release pass receives the actual document language and localizes
    # the filing-facing duty request for Kazakh documents.
    from korgan import fast_v2_production_legal, production_legal

    production_legal._apply_state_duty = apply_state_duty_from_draft
    fast_v2_production_legal._apply_state_duty = apply_state_duty_from_draft

    original_claim = StableLegalProductionService.draft_claim

    async def guarded_claim(
        self: StableLegalProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await original_claim(self, case_context, research, language=language)
        finalize_claim_for_release(case_context, draft, language=language)
        return draft

    StableLegalProductionService.draft_claim = guarded_claim  # type: ignore[assignment]

    original_contract = UniversalQualityProductionService.draft_contract

    async def guarded_contract(
        self: UniversalQualityProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ContractDraft:
        draft = await original_contract(self, case_context, research, language=language)
        sanitize_draft_instructions(draft)
        return draft

    UniversalQualityProductionService.draft_contract = guarded_contract  # type: ignore[assignment]

    original_response = UniversalQualityProductionService.draft_response_to_claim

    async def guarded_response(
        self: UniversalQualityProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ResponseToClaimDraft:
        draft = await original_response(self, case_context, research, language=language)
        sanitize_draft_instructions(draft)
        return draft

    UniversalQualityProductionService.draft_response_to_claim = guarded_response  # type: ignore[assignment]

    original_pretrial = PretrialProductionService.draft_pretrial

    async def guarded_pretrial(
        self: PretrialProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> PretrialDraft:
        return await repair_pretrial_to_target(self, original_pretrial, case_context, research, language)

    PretrialProductionService.draft_pretrial = guarded_pretrial  # type: ignore[assignment]

    original_pretrial_response = PretrialResponseProductionService.draft_pretrial_response

    async def guarded_pretrial_response(
        self: PretrialResponseProductionService,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> PretrialResponseDraft:
        return await repair_pretrial_response_to_target(
            self,
            original_pretrial_response,
            case_context,
            research,
            language,
        )

    PretrialResponseProductionService.draft_pretrial_response = guarded_pretrial_response  # type: ignore[assignment]

    _INSTALLED = True
    LOGGER.info(
        "Installed universal Word quality guard: target=10/10 for claim/contract/response/pretrial/pretrial_response; preliminary delivery preserved"
    )
