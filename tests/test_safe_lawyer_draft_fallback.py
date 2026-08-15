from __future__ import annotations

from decimal import Decimal

from korgan_legal_ai.domain.models import (
    DocumentType,
    Fact,
    Financials,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    ProceduralItem,
    ProceduralReport,
    ReadinessStatus,
    RoutingDecision,
    VerificationStatus,
)
from korgan_legal_ai.drafting.debt_claim import DebtClaimDrafter
from korgan_legal_ai.orchestration.debt_claim import DebtClaimWorkflow


class NeedsVerificationProcedural:
    def check(self, case, *, routing, calculation, as_of_date):
        return ProceduralReport(
            items=[
                ProceduralItem(
                    name="jurisdiction",
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    conclusion="определить компетентный суд и территориальную подсудность по верифицированному источнику.",
                ),
                ProceduralItem(
                    name="pretrial",
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    conclusion="проверить обязательность и соблюдение досудебного порядка.",
                ),
                ProceduralItem(
                    name="limitation",
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    conclusion="проверить срок исковой давности.",
                ),
                ProceduralItem(
                    name="state_duty",
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    conclusion="определить размер государственной пошлины по действующей редакции закона.",
                ),
                ProceduralItem(
                    name="authority",
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    conclusion="подтвердить подписанта и его полномочия.",
                ),
                ProceduralItem(
                    name="attachments",
                    status=VerificationStatus.NEEDS_VERIFICATION,
                    conclusion="проверить обязательный комплект приложений к иску.",
                ),
            ]
        )


class UnsafeDraftProvider:
    def parse(self, *, model, system, user, schema):
        # Simulate an otherwise plausible LLM draft that invents an exact article. Final Legal QA
        # must block this version, after which the deterministic safe fallback may be released.
        return schema(
            text="""В неизвестный суд

Истец: ТОО «Korgan Service»
Ответчик: ТОО «Alatau Build»

ИСКОВОЕ ЗАЯВЛЕНИЕ

Итого: 1800000 KZT

Правовое обоснование: статья 999 ГК РК.

ПРОШУ СУД:
Взыскать с ТОО «Alatau Build» в пользу ТОО «Korgan Service» задолженность в размере 1800000 KZT.
"""
        )


def test_llm_qa_block_releases_safe_lawyer_review_fallback_with_markers() -> None:
    debt_fact = Fact(statement="Ответчик не оплатил принятые услуги в размере 1 800 000 тенге.")
    case = LockedCase(
        raw_text="Тестовый спор о взыскании задолженности по договору услуг.",
        parties=[
            Party(name="ТОО «Korgan Service»", role=PartyRole.CLAIMANT),
            Party(name="ТОО «Alatau Build»", role=PartyRole.DEFENDANT),
        ],
        facts=[debt_fact],
        financials=Financials(principal=Decimal("1800000")),
    )
    routing = RoutingDecision(
        document_type=DocumentType.CLAIM,
        legal_area=LegalArea.DEBT_RECOVERY,
        confidence=1.0,
        rationale="test",
    )
    workflow = DebtClaimWorkflow(
        procedural=NeedsVerificationProcedural(),
        drafter=DebtClaimDrafter(provider=UnsafeDraftProvider(), model="test-model"),
    )

    result = workflow.run(case, routing)

    assert result.qa.passed is True
    assert result.document.readiness == ReadinessStatus.LAWYER_REVIEW_DRAFT
    assert "безопасный резервный проект" in result.document.summary
    assert "В: NEEDS_VERIFICATION" in result.document.text
    assert "Государственная пошлина: NEEDS_VERIFICATION" in result.document.text
    assert "NEEDS_VERIFICATION — конкретные нормы" in result.document.text
    assert "статья 999" not in result.document.text
    assert "Итого: 1800000 KZT" in result.document.text
    assert "в размере 1800000 KZT" in result.document.text
    assert workflow.audit.verify() is True
