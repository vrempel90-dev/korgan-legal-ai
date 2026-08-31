from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from korgan.contract_numbering import split_leading_number, strip_leading_number
from korgan.legal_types import VerificationStatus


@dataclass(slots=True)
class ResponseObjection:
    """One structural objection plus optional subclauses and free narrative."""

    text: str
    subclauses: list[str] = field(default_factory=list)
    prose: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.text = strip_leading_number(str(self.text or "").strip())
        self.subclauses = [
            cleaned
            for cleaned in (strip_leading_number(str(item).strip()) for item in self.subclauses)
            if cleaned
        ]
        self.prose = [
            cleaned
            for cleaned in (strip_leading_number(str(item).strip()) for item in self.prose)
            if cleaned
        ]

    def body_lines(self) -> list[str]:
        return [self.text, *self.subclauses, *self.prose]


def normalize_response_objections(raw: Any) -> list[ResponseObjection]:
    """Accept legacy strings and the structured {text, subclauses, prose} shape."""
    result: list[ResponseObjection] = []
    for item in raw or []:
        if isinstance(item, ResponseObjection):
            objection = item
            depth, _ = split_leading_number(objection.text)
        elif isinstance(item, dict):
            raw_text = str(item.get("text", ""))
            depth, _ = split_leading_number(raw_text)
            objection = ResponseObjection(
                text=raw_text,
                subclauses=[str(x) for x in item.get("subclauses", []) or []],
                prose=[str(x) for x in item.get("prose", []) or []],
            )
        else:
            raw_text = str(item)
            depth, _ = split_leading_number(raw_text)
            objection = ResponseObjection(text=raw_text)

        if not objection.text:
            continue
        if depth >= 3 and result:
            result[-1].subclauses.append(objection.text)
            result[-1].subclauses.extend(objection.subclauses)
            result[-1].prose.extend(objection.prose)
            continue
        result.append(objection)
    return result


@dataclass(slots=True)
class ResponseToClaimDraft:
    status: VerificationStatus
    title: str = "ОТЗЫВ НА ИСК"
    court: str = ""
    case_number: str = ""
    claimant: list[str] = field(default_factory=list)
    defendant: list[str] = field(default_factory=list)
    claim_summary: list[str] = field(default_factory=list)
    position: list[str] = field(default_factory=list)
    objections: list[ResponseObjection] = field(default_factory=list)
    legal_basis: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    verification_notes: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    # Разбор позиции истца. Значения по умолчанию пусты намеренно: старые
    # сохранённые черновики продолжают открываться, а пустое признание
    # допустимо — ответчик не обязан признавать ничего.
    admitted_circumstances: list[str] = field(default_factory=list)
    disputed_circumstances: list[str] = field(default_factory=list)
    calculation_review: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.objections = normalize_response_objections(self.objections)

    def body_lines(self) -> list[str]:
        lines = [
            self.title,
            self.court,
            self.case_number,
            *self.claimant,
            *self.defendant,
            *self.claim_summary,
            *self.admitted_circumstances,
            *self.disputed_circumstances,
            *self.position,
        ]
        for objection in self.objections:
            lines.extend(objection.body_lines())
        lines.extend(self.calculation_review)
        lines.extend(self.legal_basis)
        lines.extend(self.requests)
        lines.extend(self.attachments)
        return lines


def response_to_claim_payload(draft: ResponseToClaimDraft) -> dict[str, Any]:
    """Черновик отзыва в форме схемы — для раунда правки качества.

    Живёт рядом с dataclass, чтобы новый раздел нельзя было добавить в схему,
    забыв про раунд правки: иначе правка не видит уже собранный разбор позиции
    истца и пересобирает его заново.
    """
    return {
        "title": draft.title,
        "court": draft.court,
        "case_number": draft.case_number,
        "claimant": list(draft.claimant),
        "defendant": list(draft.defendant),
        "claim_summary": list(draft.claim_summary),
        "admitted_circumstances": list(draft.admitted_circumstances),
        "disputed_circumstances": list(draft.disputed_circumstances),
        "position": list(draft.position),
        "calculation_review": list(draft.calculation_review),
        "objections": [
            {"text": item.text, "subclauses": list(item.subclauses), "prose": list(item.prose)}
            for item in draft.objections
        ],
        "legal_basis": list(draft.legal_basis),
        "requests": list(draft.requests),
        "attachments": list(draft.attachments),
        "verification_notes": list(draft.verification_notes),
    }
