from __future__ import annotations

from pydantic import BaseModel

from korgan_legal_ai.domain.models import (
    CalculationResult,
    DocumentType,
    DraftDocument,
    EvidenceMap,
    LockedCase,
    PartyRole,
    ProceduralReport,
    ReadinessStatus,
)
from korgan_legal_ai.llm.base import LLMProvider
from korgan_legal_ai.prompts.debt_claim import DEBT_CLAIM_SYSTEM


class DraftText(BaseModel):
    text: str


class DebtClaimDrafter:
    def __init__(self, provider: LLMProvider | None = None, model: str | None = None) -> None:
        self.provider = provider
        self.model = model

    def draft(
        self,
        case: LockedCase,
        procedural: ProceduralReport,
        evidence_map: EvidenceMap,
        calculation: CalculationResult,
    ) -> DraftDocument:
        needs = list(dict.fromkeys(procedural.needs_verification))
        if evidence_map.unsupported_fact_ids:
            needs.append("evidence_gaps")
        if calculation.mismatch_with_user_total:
            needs.append("claim_total_mismatch")

        if self.provider is not None and self.model:
            payload = {
                "locked_case": case.model_dump(mode="json"),
                "procedural": procedural.model_dump(mode="json"),
                "evidence_map": evidence_map.model_dump(mode="json"),
                "calculation": calculation.model_dump(mode="json"),
                "instruction": "Do not introduce exact article numbers unless status is VERIFIED.",
            }
            generated = self.provider.parse(
                model=self.model,
                system=DEBT_CLAIM_SYSTEM,
                user=str(payload),
                schema=DraftText,
            )
            text = generated.text
        else:
            text = self._deterministic_draft(case, calculation)

        readiness = (
            ReadinessStatus.LAWYER_REVIEW_DRAFT
            if needs
            else ReadinessStatus.READY_FOR_FINAL_HUMAN_REVIEW
        )
        return DraftDocument(
            document_type=DocumentType.CLAIM,
            text=text,
            readiness=readiness,
            needs_verification=needs,
            summary="Сформирован проект иска о взыскании задолженности на основе зафиксированных фактов.",
        )

    @staticmethod
    def _deterministic_draft(case: LockedCase, calculation: CalculationResult) -> str:
        claimant = next(
            (p for p in case.parties if p.role in {PartyRole.CLAIMANT, PartyRole.CREDITOR}),
            case.parties[0],
        )
        defendant = next(
            (p for p in case.parties if p.role in {PartyRole.DEFENDANT, PartyRole.DEBTOR}),
            case.parties[1],
        )
        facts = "\n".join(f"- {f.statement}" for f in case.facts)
        total = f"{calculation.total} {calculation.currency}"
        return f"""В ______________________________ суд

Истец: {claimant.name}
Ответчик: {defendant.name}

ИСКОВОЕ ЗАЯВЛЕНИЕ
о взыскании задолженности

ОБСТОЯТЕЛЬСТВА ДЕЛА
{facts}

РАСЧЕТ ТРЕБОВАНИЙ
Основной долг: {calculation.principal} {calculation.currency}
Неустойка: {calculation.penalty} {calculation.currency}
Проценты: {calculation.interest} {calculation.currency}
Иные суммы: {calculation.other} {calculation.currency}
Итого: {total}

ПРАВОВОЕ ОБОСНОВАНИЕ
Требования основываются на обязательстве, описанном в зафиксированных фактах дела. Точные
ссылки на нормы законодательства, подсудность, государственная пошлина, сроки и необходимость
досудебного порядка подлежат отдельной верификации по официальным источникам до финальной
проверки юристом.

ПРОШУ СУД:
1. Взыскать с {defendant.name} в пользу {claimant.name} сумму требований в размере {total}.
2. Разрешить вопрос о судебных расходах в соответствии с применимым законодательством после
   проверки состава и документального подтверждения расходов.

ПРИЛОЖЕНИЯ:
Перечень приложений формируется по фактически предоставленным доказательствам и после
процессуальной проверки обязательного состава приложений.
"""
