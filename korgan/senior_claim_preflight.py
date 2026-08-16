from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from korgan.legal_types import ClaimDraft, LegalResearch

MIN_SENIOR_SCORE = 8.5

SENIOR_CLAIM_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "minimum": 0, "maximum": 10},
        "ready_for_document_release": {"type": "boolean"},
        "fact_integrity_errors": {"type": "array", "items": {"type": "string"}},
        "jurisdiction_errors": {"type": "array", "items": {"type": "string"}},
        "legal_theory_errors": {"type": "array", "items": {"type": "string"}},
        "remedy_errors": {"type": "array", "items": {"type": "string"}},
        "evidence_errors": {"type": "array", "items": {"type": "string"}},
        "document_form_errors": {"type": "array", "items": {"type": "string"}},
        "filing_actions": {"type": "array", "items": {"type": "string"}},
        "repair_instructions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "score",
        "ready_for_document_release",
        "fact_integrity_errors",
        "jurisdiction_errors",
        "legal_theory_errors",
        "remedy_errors",
        "evidence_errors",
        "document_form_errors",
        "filing_actions",
        "repair_instructions",
    ],
    "additionalProperties": False,
}

_ENTITY_RE = re.compile(
    r"\b(?:ТОО|АО|РГП|РГУ|КГУ|КГП|ОО)\b|\bБИН\b|"
    r"товариществ\w*\s+с\s+ограниченн\w*\s+ответственност\w*|"
    r"акционерн\w*\s+обществ\w*",
    re.IGNORECASE,
)
_ENTREPRENEUR_RE = re.compile(
    r"\bИП\b|индивидуальн\w*\s+предпринимател\w*|"
    r"осуществля\w*\s+индивидуальн\w*\s+предпринимательск\w*\s+деятельност\w*",
    re.IGNORECASE,
)
_INDIVIDUAL_RE = re.compile(r"\bИИН\b|дата\s+рождения", re.IGNORECASE)
_CORPORATE_RE = re.compile(r"корпоративн\w*\s+спор", re.IGNORECASE)
_ECONOMIC_COURT_RE = re.compile(
    r"специализированн\w*\s+межрайонн\w*\s+экономическ\w*\s+суд|\bСМЭС\b",
    re.IGNORECASE,
)
_MORAL_REQUEST_RE = re.compile(r"моральн\w*\s+вред", re.IGNORECASE)
_MORAL_FACT_RE = re.compile(
    r"нервн\w*|стресс\w*|переживан\w*|моральн\w*\s+страдан\w*|"
    r"нравственн\w*\s+страдан\w*|физическ\w*\s+страдан\w*|"
    r"ухудшен\w*\s+(?:здоров|самочувств)|бессонниц\w*",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"(?<!\d)\d[\d\s ]*(?:[.,]\d{1,2})?\s*(?:тенге|тг\b|₸)", re.IGNORECASE)
_BLANK_RE = re.compile(r"_{3,}|\[(?:ТРЕБУЕТ|НЕИЗВЕСТНО)[^\]]*\]", re.IGNORECASE)


@dataclass(slots=True)
class SeniorClaimReview:
    score: float
    ready_for_document_release: bool
    fact_integrity_errors: list[str] = field(default_factory=list)
    jurisdiction_errors: list[str] = field(default_factory=list)
    legal_theory_errors: list[str] = field(default_factory=list)
    remedy_errors: list[str] = field(default_factory=list)
    evidence_errors: list[str] = field(default_factory=list)
    document_form_errors: list[str] = field(default_factory=list)
    filing_actions: list[str] = field(default_factory=list)
    repair_instructions: list[str] = field(default_factory=list)
    deterministic_errors: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        deterministic_errors: list[str] | None = None,
    ) -> "SeniorClaimReview":
        errors = list(dict.fromkeys(deterministic_errors or []))
        score = float(payload.get("score", 0.0) or 0.0)
        # A deterministic filing/legal contradiction is a major defect, not an
        # artificial 8.4 ceiling. This keeps the displayed score meaningful.
        if errors:
            score = min(score, 6.9)
        return cls(
            score=round(max(0.0, min(10.0, score)), 1),
            ready_for_document_release=bool(payload.get("ready_for_document_release")) and not errors,
            fact_integrity_errors=_strings(payload.get("fact_integrity_errors")),
            jurisdiction_errors=_strings(payload.get("jurisdiction_errors")),
            legal_theory_errors=_strings(payload.get("legal_theory_errors")),
            remedy_errors=_strings(payload.get("remedy_errors")),
            evidence_errors=_strings(payload.get("evidence_errors")),
            document_form_errors=_strings(payload.get("document_form_errors")),
            filing_actions=_strings(payload.get("filing_actions")),
            repair_instructions=_strings(payload.get("repair_instructions")),
            deterministic_errors=errors,
        )

    @property
    def hard_blockers(self) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *self.deterministic_errors,
                    *self.fact_integrity_errors,
                    *self.jurisdiction_errors,
                    *self.legal_theory_errors,
                    *self.remedy_errors,
                    *self.evidence_errors,
                    *self.document_form_errors,
                ]
            )
        )

    @property
    def ready(self) -> bool:
        return (
            self.ready_for_document_release
            and self.score >= MIN_SENIOR_SCORE
            and not self.hard_blockers
        )

    def repair_list(self, limit: int = 16) -> list[str]:
        return list(dict.fromkeys([*self.hard_blockers, *self.repair_instructions]))[:limit]


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in (value or []) if str(item).strip()]


def _party_text(values: list[str]) -> str:
    return " ".join(str(item) for item in values if str(item).strip())


def _ordinary_individual(values: list[str]) -> bool:
    text = _party_text(values)
    if _ENTITY_RE.search(text) or _ENTREPRENEUR_RE.search(text):
        return False
    return bool(_INDIVIDUAL_RE.search(text))


def deterministic_claim_preflight(
    case_context: str,
    research: LegalResearch,
    draft: ClaimDraft,
) -> list[str]:
    """High-confidence legal/fact contradictions that must never reach release.

    These are generic invariants, not case-name or article-specific patches.
    Current RK procedural law limits economic-court subject composition to
    statutory business/legal-person categories (with separate corporate/investor
    exceptions). Therefore an ordinary natural person in a non-corporate dispute
    is a hard contradiction when the draft selects an economic court.
    """
    errors: list[str] = []
    context = case_context or ""
    body = "\n".join(
        [
            draft.court,
            *draft.claimant,
            *draft.defendant,
            *draft.facts,
            *draft.legal_basis,
            *draft.requests,
        ]
    )

    if _ECONOMIC_COURT_RE.search(draft.court or "") and not _CORPORATE_RE.search(context + "\n" + body):
        if _ordinary_individual(draft.claimant) or _ordinary_individual(draft.defendant):
            errors.append(
                "Выбран специализированный межрайонный экономический суд, хотя в споре участвует обычное физическое лицо без установленного статуса ИП; предметная компетенция суда противоречит составу сторон и требует исправления."
            )

    requests_text = "\n".join(draft.requests)
    if _BLANK_RE.search(requests_text):
        errors.append("В просительной части осталась незаполненная сумма/формальное поле; денежное или иное требование не является исполнимым в таком виде.")

    for request in draft.requests:
        if _MORAL_REQUEST_RE.search(request) and not _AMOUNT_RE.search(request):
            errors.append("Заявлено денежное требование о компенсации морального вреда без определенного размера.")
            break

    # Subjective suffering is a source fact. Legal availability of moral damages
    # does not authorize the model to invent stress, insomnia or suffering.
    draft_subjective = "\n".join(draft.facts)
    if _MORAL_FACT_RE.search(draft_subjective) and not _MORAL_FACT_RE.search(context):
        errors.append(
            "В фактическую часть добавлены субъективные последствия (страдания/стресс/переживания), которых пользователь не сообщал. Такие факты должны быть удалены или подтверждены материалами."
        )

    # A court can be named only when the source-bound research carried the same
    # official court identity into VERIFIED_COURT. A court name present only in
    # model prose is not enough for a filing-ready document.
    court = (draft.court or "").strip()
    if court:
        normalized = _normalize(court)
        supported = normalized in _normalize(context)
        if not supported:
            for note in research.notes:
                if not str(note).startswith("VERIFIED_COURT:"):
                    continue
                verified = str(note).split(":", 1)[1].strip()
                vnorm = _normalize(verified)
                if vnorm and (vnorm in normalized or normalized in vnorm):
                    supported = True
                    break
        if not supported:
            errors.append("Точное наименование суда не подтверждено материалами пользователя или source-bound записью VERIFIED_COURT.")

    return list(dict.fromkeys(errors))


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", (value or "").lower())


def claim_review_payload(draft: ClaimDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "court": draft.court,
        "claimant": draft.claimant,
        "defendant": draft.defendant,
        "price_of_claim": draft.price_of_claim,
        "state_duty": draft.state_duty,
        "late_interest": draft.late_interest,
        "facts": draft.facts,
        "legal_basis": draft.legal_basis,
        "requests": draft.requests,
        "attachments": draft.attachments,
        "verification_notes": draft.verification_notes,
    }
