from __future__ import annotations

import re

from korgan.claim_filing_accuracy import FILING_ACTION_PREFIX
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus

_PENALTY_INTENT_RE = re.compile(
    r"(?is)(?:неустойк\w*|пен[яию]\b|тұрақсыздық\s+айыб\w*).{0,180}(?:определ|рассчит|взыск|треб|заяв)|"
    r"(?:определ|рассчит|взыск|треб|заяв).{0,180}(?:неустойк\w*|пен[яию]\b|тұрақсыздық\s+айыб\w*)"
)
_MORAL_INTENT_RE = re.compile(
    r"(?is)(?:моральн\w*\s+вред\w*|моральдық\s+зиян\w*).{0,180}(?:определ|основан|компенсац|взыск|треб|заяв)|"
    r"(?:определ|основан|компенсац|взыск|треб|заяв).{0,180}(?:моральн\w*\s+вред\w*|моральдық\s+зиян\w*)"
)
_JURISDICTION_INTENT_RE = re.compile(r"(?i)(?:подсудност\w*|правильн\w*\s+суд\w*|қай\s+сот)")
_COSTS_INTENT_RE = re.compile(r"(?i)(?:судебн\w*\s+расход\w*|судебн\w*\s+издерж\w*|сот\s+шығын\w*)")

_PENALTY_REQUEST_RE = re.compile(r"(?i)(?:взыск\w*|өндір\w*).{0,160}(?:неустойк\w*|пен[яию]\b|тұрақсыздық\s+айыб\w*)")
_MORAL_REQUEST_RE = re.compile(r"(?i)(?:взыск\w*|өндір\w*|компенсир\w*).{0,160}(?:моральн\w*\s+вред\w*|моральдық\s+зиян\w*)")
_SUBJECTIVE_RE = re.compile(
    r"(?i)(?:переживан\w*|стресс\w*|нервн\w*|нравственн\w*\s+страдан\w*|"
    r"моральн\w*\s+страдан\w*|физическ\w*\s+страдан\w*|бессонниц\w*|"
    r"ухудшен\w*\s+(?:здоров|самочувств)|эмоциональн\w*\s+состояни\w*)"
)
_CONSUMER_SOURCE_RE = re.compile(
    r"(?i)(?:Z100000274_|защит\w*\s+прав\w*\s+потребител\w*|тұтынушылардың\s+құқықтарын\s+қорға)"
)
_PENALTY_NORM_RE = re.compile(r"(?is)(?:неустойк\w*|тұрақсыздық\s+айыб\w*).{0,300}(?:один\s+процент|1\s*(?:%|процент)|бір\s+пайыз)")
_MORAL_NORM_RE = re.compile(r"(?is)(?:моральн\w*\s+вред\w*|моральдық\s+зиян\w*).{0,240}компенсац")

_STALE_DUTY_REFERENCE_RE = re.compile(
    r"(?i)(?:стать(?:я|и|ей|ю)|ст\.)\s*105-1\s+ГПК\s+РК"
)


def _joined(values: list[str]) -> str:
    return "\n".join(str(item or "") for item in values or [])


def _append_note(draft: ClaimDraft, note: str) -> None:
    if note not in draft.verification_notes:
        draft.verification_notes.append(note)
    draft.status = VerificationStatus.NEEDS_VERIFICATION


def _mark_penalty_calculation_pending(draft: ClaimDraft) -> None:
    draft.price_of_claim = "[ТРЕБУЕТ РАСЧЁТА: цена иска с учетом неустойки на дату подачи]"
    draft.state_duty = NEEDS_CALCULATION_MARKER


def _verified_consumer_penalty(research: LegalResearch) -> bool:
    text = _joined(research.verified_claims)
    return bool(_CONSUMER_SOURCE_RE.search(text) and _PENALTY_NORM_RE.search(text))


def _verified_consumer_moral(research: LegalResearch) -> bool:
    text = _joined(research.verified_claims)
    return bool(_CONSUMER_SOURCE_RE.search(text) and _MORAL_NORM_RE.search(text))


def _sanitize_retired_state_duty_reference(draft: ClaimDraft) -> None:
    """Do not let the retired GPK 105-1 route survive model prose.

    The authoritative state-duty router writes the current rule separately.
    Keeping an old procedural citation in legal basis or a motion would make an
    otherwise correct filing internally contradictory.
    """
    draft.legal_basis = [line for line in draft.legal_basis if not _STALE_DUTY_REFERENCE_RE.search(str(line))]
    draft.requests = [line for line in draft.requests if not _STALE_DUTY_REFERENCE_RE.search(str(line))]
    draft.facts = [line for line in draft.facts if not _STALE_DUTY_REFERENCE_RE.search(str(line))]


def _ensure_requested_penalty(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    if not _PENALTY_INTENT_RE.search(case_context or ""):
        return

    requests = _joined(draft.requests)
    if _PENALTY_REQUEST_RE.search(requests):
        # An amount/formula already exists.  The normal arithmetic and citation
        # gates decide whether it is filing-ready.
        return

    if not _verified_consumer_penalty(research):
        _mark_penalty_calculation_pending(draft)
        _append_note(
            draft,
            FILING_ACTION_PREFIX
            + "пользователь просил проверить/взыскать неустойку, но действующее основание и размер не подтверждены VERIFIED-источником; требование нельзя молча исключать, а цену иска и госпошлину нельзя считать окончательными.",
        )
        return

    draft.requests.append(
        "Взыскать с ответчика неустойку за нарушение срока выполнения работ "
        "[ДАННЫЕ: сумма неустойки на дату подачи иска; СВЕРИТЬ: конечную дату расчета и наличие в договоре иного законного размера неустойки]."
    )
    # Until the amount is known, both claim price and duty are necessarily
    # incomplete.  A plausible-looking 850 000 тенге must not be labelled as the
    # final claim price while an expressly requested monetary remedy is pending.
    _mark_penalty_calculation_pending(draft)
    _append_note(
        draft,
        FILING_ACTION_PREFIX
        + "рассчитать неустойку на фактическую дату подачи иска и после этого пересчитать цену иска и государственную пошлину.",
    )


def _ensure_requested_moral_damage(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    if not _MORAL_INTENT_RE.search(case_context or ""):
        return
    if _MORAL_REQUEST_RE.search(_joined(draft.requests)):
        return

    if not _verified_consumer_moral(research):
        _append_note(
            draft,
            FILING_ACTION_PREFIX
            + "пользователь просил оценить моральный вред, но применимая норма не подтверждена VERIFIED-источником; вопрос нельзя молча исключать.",
        )
        return

    if not _SUBJECTIVE_RE.search(case_context or ""):
        _append_note(
            draft,
            FILING_ACTION_PREFIX
            + "право на компенсацию морального вреда проверено, но в материалах нет конкретных фактов физических/нравственных страданий и заявляемого размера; уточнить их перед включением требования, не выдумывая обстоятельства.",
        )
        return

    _append_note(
        draft,
        FILING_ACTION_PREFIX
        + "материалы содержат факты, относящиеся к моральному вреду, но не указан заявляемый размер компенсации; получить сумму от истца перед финальной подачей.",
    )


def _ensure_requested_jurisdiction(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    if not _JURISDICTION_INTENT_RE.search(case_context or ""):
        return
    court = str(draft.court or "")
    verified_court = any(str(note).startswith("VERIFIED_COURT:") for note in research.notes or [])
    if not court.strip() or "ТРЕБУЕТ" in court.upper() or "ДАННЫЕ" in court.upper() or not verified_court:
        _append_note(
            draft,
            FILING_ACTION_PREFIX
            + "пользователь просил определить подсудность; до подачи требуется подтвержденное наименование компетентного суда.",
        )


def _ensure_requested_costs(case_context: str, draft: ClaimDraft) -> None:
    if not _COSTS_INTENT_RE.search(case_context or ""):
        return
    # Existing proven monetary costs (expert/specialist etc.) may already be a
    # substantive loss or a litigation cost.  Do not invent a representative or
    # an amount merely because the user asked to recover recoverable costs.
    request_text = _joined(draft.requests)
    if re.search(r"(?i)(?:расход\w*|издерж\w*|специалист\w*|эксперт\w*)", request_text):
        return
    _append_note(
        draft,
        FILING_ACTION_PREFIX
        + "пользователь просил взыскать судебные расходы при наличии оснований; конкретные понесенные расходы и подтверждающие документы не определены, поэтому сумма не выдумывается.",
    )


def enforce_requested_remedy_coverage(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> None:
    """Every remedy explicitly requested by the user must have an outcome.

    Outcome means either an executable prayer supported by VERIFIED current law
    or an explicit filing action explaining what is missing.  Silent omission is
    forbidden.  This is deliberately deterministic and adds no model call.
    """
    _sanitize_retired_state_duty_reference(draft)
    _ensure_requested_penalty(case_context, research, draft)
    _ensure_requested_moral_damage(case_context, research, draft)
    _ensure_requested_jurisdiction(case_context, research, draft)
    _ensure_requested_costs(case_context, draft)
