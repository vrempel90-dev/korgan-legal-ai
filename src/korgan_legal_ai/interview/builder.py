from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from korgan_legal_ai.blueprints.interview import UNKNOWN
from korgan_legal_ai.blueprints.models import DocumentBlueprint
from korgan_legal_ai.domain.models import (
    Evidence,
    EvidenceKind,
    Fact,
    FilingMode,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    Payment,
    ProcedureFacts,
    RepresentativeKind,
    RoutingDecision,
)

# Mapping from what a user calls a document to the evidence category the procedural checks reason
# about. Only explicit wording is classified; anything unrecognised stays OTHER rather than being
# guessed into a category that would make a procedural requirement look satisfied.
_EVIDENCE_KEYWORDS: tuple[tuple[tuple[str, ...], EvidenceKind], ...] = (
    (("акт сверки", "сверк"), EvidenceKind.RECONCILIATION),
    # Checked before delivery proof: a state-duty receipt is also a "квитанция", and the more
    # specific meaning has to win or the filing fee would be mistaken for proof of service.
    (("госпошлин", "пошлин"), EvidenceKind.STATE_DUTY_PAYMENT),
    (("доказательство направления", "чек об отправке", "квитанц", "почтов", "опись вложения",
      "уведомление о вручении", "трек"), EvidenceKind.PRETRIAL_DELIVERY),
    (("претензи", "требование о погашении"), EvidenceKind.PRETRIAL_DEMAND),
    (("доверенн",), EvidenceKind.AUTHORITY),
    (("приказ о назначении", "решение единственного участника", "устав", "протокол о назначении",
      "выписка о руководител"), EvidenceKind.AUTHORITY),
    (("удостоверение адвоката", "лицензи", "свидетельство юридического консультанта",
      "членств"), EvidenceKind.PROFESSIONAL_STATUS),
    (("справка о регистрации", "справка о государственной регистрации", "регистрацион",
      "выписка из егр"), EvidenceKind.REGISTRATION),
    (("платеж", "платёж", "выписка", "банков", "оплат"), EvidenceKind.PAYMENT),
    (("договор", "контракт", "соглашение"), EvidenceKind.CONTRACT),
    (("акт", "накладн", "счет-фактур", "счёт-фактур", "счет", "счёт", "смет",
      "товарно"), EvidenceKind.PRIMARY_DOCUMENT),
)

# Evidence the user is asserting proves the merits of the case, as opposed to procedural paperwork.
_MERITS_KINDS = {
    EvidenceKind.CONTRACT,
    EvidenceKind.PRIMARY_DOCUMENT,
    EvidenceKind.PAYMENT,
    EvidenceKind.RECONCILIATION,
}

_REPRESENTATIVE_KINDS = {
    "director": RepresentativeKind.DIRECTOR,
    "employee": RepresentativeKind.EMPLOYEE,
    "advocate": RepresentativeKind.ADVOCATE,
    "legal_consultant": RepresentativeKind.LEGAL_CONSULTANT,
    "other": RepresentativeKind.OTHER,
}


def classify_evidence(title: str) -> EvidenceKind:
    lowered = title.lower()
    for keywords, kind in _EVIDENCE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return kind
    return EvidenceKind.OTHER


def _answer(answers: dict[str, object], key: str) -> object | None:
    value = answers.get(key)
    if value == UNKNOWN:
        return None
    return value


def _decimal(answers: dict[str, object], key: str) -> Decimal | None:
    value = _answer(answers, key)
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _date(answers: dict[str, object], key: str) -> date | None:
    value = _answer(answers, key)
    if not value:
        return None
    return date.fromisoformat(str(value))


def _bool(answers: dict[str, object], key: str) -> bool | None:
    value = _answer(answers, key)
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def _split_items(raw: object | None, *, split_commas: bool = False) -> list[str]:
    """Split a free-text answer into separate entries.

    Commas are only separators in list-style answers such as the attachment list. Splitting prose on
    commas would chop a single circumstance into fragments, so narrative answers are split on
    semicolons and line breaks only.
    """
    if not raw:
        return []
    pattern = r"[;\n]+"
    if split_commas:
        pattern += r"|\s*,\s*"
    parts = re.split(pattern, str(raw))
    return [part.strip(" .;") for part in parts if part.strip(" .;")]


def build_locked_case(
    blueprint: DocumentBlueprint,
    answers: dict[str, object],
) -> LockedCase:
    """Turn validated dialogue answers into a locked case without a model in the loop.

    Every value here was typed by the user and validated by a deterministic parser, so this path
    involves no extraction step that could misread an amount, a date or a party. "Не знаю" answers
    are dropped rather than defaulted: an absent value is what later produces an explicit
    NEEDS_VERIFICATION instead of an invented one.
    """
    presentation = blueprint.parties

    author = Party(
        name=str(answers.get("author_name", "")).strip(),
        role=presentation.author_role,
        iin_bin=_answer(answers, "author_bin") and str(_answer(answers, "author_bin")) or None,
        address=_answer(answers, "author_address") and str(_answer(answers, "author_address")) or None,
    )
    opponent = Party(
        name=str(answers.get("opponent_name", "")).strip(),
        role=presentation.opponent_role,
        iin_bin=_answer(answers, "opponent_bin") and str(_answer(answers, "opponent_bin")) or None,
        address=_answer(answers, "opponent_address")
        and str(_answer(answers, "opponent_address"))
        or None,
    )

    facts: list[Fact] = []
    for key in ("basis", "contested_act", "contract_subject", "circumstances",
                "response_position", "motion_request", "case_number"):
        for statement in _split_items(_answer(answers, key)):
            facts.append(Fact(statement=statement))
    if not facts:
        facts.append(Fact(statement="Обстоятельства изложены в приложенных документах."))

    evidence_titles = _split_items(_answer(answers, "evidence_list"), split_commas=True)
    evidence = [Evidence(title=title, kind=classify_evidence(title)) for title in evidence_titles]
    # The user asserted these documents are the proof for this matter, so merits documents are
    # linked to the locked facts. Procedural paperwork (state duty receipt, power of attorney) is
    # not treated as proof of the underlying facts.
    fact_ids = [fact.id for fact in facts]
    for item in evidence:
        if item.kind in _MERITS_KINDS:
            item.supports_fact_ids = list(fact_ids)

    payments_raw = _answer(answers, "payments") or []
    payment_schedule = [
        Payment(
            amount=Decimal(str(entry["amount"])),
            paid_on=date.fromisoformat(entry["paid_on"]) if entry.get("paid_on") else None,
        )
        for entry in payments_raw
        if isinstance(entry, dict)
    ]

    financials = Financials(
        contract_amount=_decimal(answers, "contract_amount"),
        payment_schedule=payment_schedule,
        penalty_rate_percent_per_day=_decimal(answers, "penalty_rate"),
        penalty_cap_percent_of_principal=_decimal(answers, "penalty_cap"),
        other=_decimal(answers, "other_amount"),
    )

    representative_kind = _answer(answers, "representative_kind")
    filing_mode = _answer(answers, "filing_mode")
    procedure = ProcedureFacts(
        obligation_due_date=_date(answers, "obligation_due_date"),
        pretrial_required_by_contract=_bool(answers, "pretrial_required"),
        pretrial_demand_sent_date=_date(answers, "pretrial_sent_date"),
        representative_kind=_REPRESENTATIVE_KINDS.get(str(representative_kind))
        if representative_kind
        else None,
        representative_name=_answer(answers, "representative_name")
        and str(_answer(answers, "representative_name"))
        or None,
        # A director signs by virtue of office; there is no separate power of attorney to confirm.
        representative_can_sign_claim=(
            True
            if representative_kind == "director"
            else _bool(answers, "representative_can_sign")
        ),
        filing_mode=FilingMode(str(filing_mode)) if filing_mode else None,
        copies_prepared=_bool(answers, "copies_prepared"),
    )

    return LockedCase(
        raw_text="",
        parties=[author, opponent],
        facts=facts,
        evidence=evidence,
        financials=financials,
        procedure=procedure,
    )


def build_routing(blueprint: DocumentBlueprint) -> RoutingDecision:
    """Routing for a guided request is a user choice, not a classification."""
    return RoutingDecision(
        document_type=blueprint.document_type,
        legal_area=blueprint.legal_area or LegalArea.CIVIL_OTHER,
        confidence=1.0,
        rationale="Тип документа выбран пользователем в пошаговом диалоге.",
    )
