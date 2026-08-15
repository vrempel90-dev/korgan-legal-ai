from __future__ import annotations

from datetime import date

from korgan_legal_ai.domain.models import (
    CalculationResult,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    ProceduralItem,
    ProceduralReport,
    RoutingDecision,
    VerificationStatus,
)
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import CitationGateway


PROCEDURAL_ISSUES = {
    "jurisdiction": "Компетентный суд и территориальная/родовая подсудность",
    "pretrial": "Обязательный досудебный или претензионный порядок",
    "limitation": "Срок исковой давности и иные процессуальные сроки",
    "state_duty": "Размер и порядок расчета государственной пошлины",
    "authority": "Процессуальный статус и полномочия представителя",
    "attachments": "Обязательные приложения к иску",
}

_LEGAL_ENTITY_PREFIXES = ("ТОО", "АО", "НАО", "РГП", "КГП", "ГКП")


class ProceduralChecker:
    def __init__(
        self,
        gateway: CitationGateway,
        *,
        state_duty_calculator: StateDutyCalculator | None = None,
        jurisdiction_resolver: JurisdictionResolver | None = None,
    ) -> None:
        self.gateway = gateway
        self.state_duty_calculator = state_duty_calculator
        self.jurisdiction_resolver = jurisdiction_resolver

    @staticmethod
    def _party(case: LockedCase, roles: set[PartyRole]) -> Party | None:
        return next((party for party in case.parties if party.role in roles), None)

    @staticmethod
    def _party_type(party: Party | None) -> str | None:
        """Classify only explicit Kazakhstan legal-form markers; otherwise stay unknown."""
        if party is None:
            return None
        normalized = party.name.strip().upper().replace("«", " ").replace("»", " ")
        first = normalized.split(maxsplit=1)[0] if normalized else ""
        if first in _LEGAL_ENTITY_PREFIXES:
            return "legal_entity"
        return None

    @staticmethod
    def _needs(name: str, conclusion: str) -> ProceduralItem:
        return ProceduralItem(
            name=name,
            status=VerificationStatus.NEEDS_VERIFICATION,
            conclusion=conclusion,
            sources=[],
        )

    def _generic_item(self, name: str, issue: str, *, as_of_date: date | None) -> ProceduralItem:
        citations = self.gateway.research(
            issue,
            event_date=as_of_date.isoformat() if as_of_date is not None else None,
        )
        verified = bool(citations) and all(
            citation.status == VerificationStatus.VERIFIED for citation in citations
        )
        return ProceduralItem(
            name=name,
            status=VerificationStatus.VERIFIED if verified else VerificationStatus.NEEDS_VERIFICATION,
            conclusion=(
                "Проверено по canonical-корпусу и официальному источнику."
                if verified
                else "Требует проверки по официальному источнику перед финальной юридической проверкой."
            ),
            sources=citations,
        )

    def _state_duty_item(
        self,
        case: LockedCase,
        routing: RoutingDecision | None,
        calculation: CalculationResult | None,
        *,
        as_of_date: date | None,
    ) -> ProceduralItem:
        if self.state_duty_calculator is None:
            return self._needs(
                "state_duty",
                "Детерминированный модуль госпошлины не подключен; сумма не рассчитывается.",
            )
        if as_of_date is None:
            return self._needs("state_duty", "Для расчета госпошлины требуется дата расчета/подачи.")
        if routing is None or routing.legal_area != LegalArea.DEBT_RECOVERY:
            return self._needs("state_duty", "Нет подтвержденной классификации денежного долгового иска.")
        if calculation is None or calculation.currency != "KZT" or calculation.total <= 0:
            return self._needs("state_duty", "Нет подтвержденной положительной цены иска в KZT.")

        claimant = self._party(case, {PartyRole.CLAIMANT, PartyRole.CREDITOR})
        claimant_type = self._party_type(claimant)
        if claimant_type is None:
            return self._needs(
                "state_duty",
                "Тип истца не установлен из явной организационно-правовой формы; ставка не угадывается.",
            )

        result = self.state_duty_calculator.calculate(
            claim_amount_kzt=calculation.total,
            claimant_type=claimant_type,
            claim_type="property",
            event_date=as_of_date,
        )
        if result.status != VerificationStatus.VERIFIED or result.amount_kzt is None:
            return ProceduralItem(
                name="state_duty",
                status=VerificationStatus.NEEDS_VERIFICATION,
                conclusion=result.verification_note or "Госпошлина не прошла полную верификацию.",
                sources=result.citations,
            )
        return ProceduralItem(
            name="state_duty",
            status=VerificationStatus.VERIFIED,
            conclusion=(
                f"Государственная пошлина: {result.amount_kzt} KZT; "
                f"ставка {result.rate_percent}% по версии правил на {as_of_date.isoformat()}."
            ),
            sources=result.citations,
        )

    def _jurisdiction_item(
        self,
        case: LockedCase,
        routing: RoutingDecision | None,
        *,
        as_of_date: date | None,
    ) -> ProceduralItem:
        if self.jurisdiction_resolver is None:
            return self._needs(
                "jurisdiction",
                "Детерминированный модуль подсудности не подключен; суд не угадывается.",
            )
        if as_of_date is None:
            return self._needs("jurisdiction", "Для определения подсудности требуется дата применения правил.")
        if routing is None or routing.legal_area != LegalArea.DEBT_RECOVERY:
            return self._needs("jurisdiction", "Нет подтвержденной классификации долгового спора.")

        claimant = self._party(case, {PartyRole.CLAIMANT, PartyRole.CREDITOR})
        defendant = self._party(case, {PartyRole.DEFENDANT, PartyRole.DEBTOR})
        plaintiff_type = self._party_type(claimant)
        defendant_type = self._party_type(defendant)
        if plaintiff_type is None or defendant_type is None:
            return self._needs(
                "jurisdiction",
                "Тип хотя бы одной стороны не установлен из явной организационно-правовой формы; "
                "подсудность не угадывается.",
            )

        result = self.jurisdiction_resolver.resolve(
            plaintiff_type=plaintiff_type,
            defendant_type=defendant_type,
            dispute_type="commercial_debt",
            event_date=as_of_date,
        )
        if result.status != VerificationStatus.VERIFIED:
            return ProceduralItem(
                name="jurisdiction",
                status=VerificationStatus.NEEDS_VERIFICATION,
                conclusion=result.verification_note or "Подсудность не прошла полную верификацию.",
                sources=result.citations,
            )

        court = {
            "specialized_interdistrict_economic_court":
                "специализированный межрайонный экономический суд"
        }.get(result.court_type or "", result.court_type or "не определен")
        territory = {
            "defendant_location": "по месту нахождения ответчика"
        }.get(result.territorial_rule or "", result.territorial_rule or "не определено")
        return ProceduralItem(
            name="jurisdiction",
            status=VerificationStatus.VERIFIED,
            conclusion=(
                f"Родовая подсудность: {court}; территориальное правило: {territory}. "
                "Конкретное наименование суда не генерируется без отдельной проверки адреса и справочника судов."
            ),
            sources=result.citations,
        )

    def check(
        self,
        case: LockedCase,
        *,
        routing: RoutingDecision | None = None,
        calculation: CalculationResult | None = None,
        as_of_date: date | None = None,
    ) -> ProceduralReport:
        items: list[ProceduralItem] = []
        for name, issue in PROCEDURAL_ISSUES.items():
            if name == "state_duty":
                item = self._state_duty_item(
                    case, routing, calculation, as_of_date=as_of_date
                )
            elif name == "jurisdiction":
                item = self._jurisdiction_item(case, routing, as_of_date=as_of_date)
            elif name == "limitation":
                # Task 9 requires deadlines from structured formulas, not free-text RAG.
                # LockedCase does not yet carry a typed obligation_due_date trigger, so we
                # deliberately remain fail-closed instead of guessing which fact starts the term.
                item = self._needs(
                    "limitation",
                    "Формула срока хранится в структурированных правилах, но для расчета нужен "
                    "явно типизированный trigger obligation_due_date; по произвольной дате из фактов "
                    "срок не угадывается.",
                )
            else:
                item = self._generic_item(name, issue, as_of_date=as_of_date)
            items.append(item)
        return ProceduralReport(items=items)
