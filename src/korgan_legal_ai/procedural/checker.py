from __future__ import annotations

from datetime import date

from korgan_legal_ai.blueprints.models import STYLE_SUPPORT_ITEM, DocumentBlueprint
from korgan_legal_ai.domain.models import (
    CalculationResult,
    EvidenceKind,
    FilingMode,
    LegalArea,
    LockedCase,
    Party,
    PartyRole,
    ProceduralItem,
    ProceduralReport,
    RepresentativeKind,
    ResearchCitation,
    RoutingDecision,
    VerificationStatus,
)
from korgan_legal_ai.procedural_rules.deadlines import DeadlineCalculator
from korgan_legal_ai.procedural_rules.jurisdiction import JurisdictionResolver
from korgan_legal_ai.procedural_rules.state_duty import StateDutyCalculator
from korgan_legal_ai.research.gateway import CitationGateway


PROCEDURAL_ISSUES = {
    "jurisdiction": "Компетентный суд и территориальная/родовая подсудность",
    "pretrial": "Обязательный досудебный или претензионный порядок",
    "limitation": "Срок исковой давности и иные процессуальные сроки",
    "state_duty": "Размер и порядок расчета государственной пошлины",
    "authority": "Процессуальный статус и полномочия подписанта/представителя",
    "attachments": "Обязательные приложения к иску",
}

_LEGAL_ENTITY_PREFIXES = ("ТОО", "АО", "НАО", "РГП", "КГП", "ГКП")
_MERITS_EVIDENCE = {
    EvidenceKind.CONTRACT,
    EvidenceKind.PRIMARY_DOCUMENT,
    EvidenceKind.PAYMENT,
    EvidenceKind.OTHER,
}


class ProceduralChecker:
    def __init__(
        self,
        gateway: CitationGateway,
        *,
        state_duty_calculator: StateDutyCalculator | None = None,
        jurisdiction_resolver: JurisdictionResolver | None = None,
        deadline_calculator: DeadlineCalculator | None = None,
    ) -> None:
        self.gateway = gateway
        self.state_duty_calculator = state_duty_calculator
        self.jurisdiction_resolver = jurisdiction_resolver
        self.deadline_calculator = deadline_calculator

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
    def _has_evidence(case: LockedCase, kind: EvidenceKind) -> bool:
        return any(evidence.kind == kind for evidence in case.evidence)

    @staticmethod
    def _needs(
        name: str,
        conclusion: str,
        sources: list[ResearchCitation] | None = None,
    ) -> ProceduralItem:
        return ProceduralItem(
            name=name,
            status=VerificationStatus.NEEDS_VERIFICATION,
            conclusion=conclusion,
            sources=sources or [],
        )

    def _exact_sources(
        self,
        locators: list[tuple[str, str, str, str]],
        *,
        as_of_date: date | None,
    ) -> tuple[list[ResearchCitation], bool]:
        if as_of_date is None:
            return [], False
        citations: list[ResearchCitation] = []
        for code_id, article, part, point in locators:
            result = self.gateway.research_locator(
                code_id=code_id,
                article_number=article,
                part=part,
                point=point,
                event_date=as_of_date.isoformat(),
            )
            citations.extend(result)
        return citations, bool(citations) and all(
            citation.status == VerificationStatus.VERIFIED for citation in citations
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
                f"ставка {result.rate_percent}%."
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

    def _limitation_item(self, case: LockedCase, *, as_of_date: date | None) -> ProceduralItem:
        if self.deadline_calculator is None:
            return self._needs(
                "limitation",
                "Детерминированный калькулятор срока исковой давности не подключен.",
            )
        if as_of_date is None:
            return self._needs("limitation", "Нет даты, на которую проверяется срок исковой давности.")
        due_date = case.procedure.obligation_due_date
        if due_date is None:
            return self._needs(
                "limitation",
                "Нужен явно подтвержденный срок исполнения обязательства (obligation_due_date); "
                "произвольная дата из текста дела не используется как начало срока.",
            )

        result = self.deadline_calculator.calculate(
            rule_code="general_debt_limitation",
            trigger_date=due_date,
            event_date=as_of_date,
        )
        if result.status != VerificationStatus.VERIFIED or result.final_deadline is None:
            detail = result.verification_note or "Срок исковой давности не прошел полную верификацию."
            if result.nominal_deadline is not None:
                detail = f"Номинальная дата окончания: {result.nominal_deadline.isoformat()}. {detail}"
            return self._needs("limitation", detail, result.citations)

        timing = (
            "расчетная дата окончания еще не наступила"
            if as_of_date <= result.final_deadline
            else "расчетная дата окончания уже наступила"
        )
        return ProceduralItem(
            name="limitation",
            status=VerificationStatus.VERIFIED,
            conclusion=(
                f"Срок рассчитан от даты исполнения {due_date.isoformat()}; "
                f"окончание {result.final_deadline.isoformat()} ({timing})."
            ),
            sources=result.citations,
        )

    def _pretrial_item(self, case: LockedCase, *, as_of_date: date | None) -> ProceduralItem:
        required = case.procedure.pretrial_required_by_contract
        if required is None:
            return self._needs(
                "pretrial",
                "Не установлено, содержит ли договор обязательный досудебный порядок; "
                "отдельно требуется проверка специальных норм закона.",
            )
        if required is False:
            return self._needs(
                "pretrial",
                "По зафиксированным фактам договор не устанавливает обязательный претензионный порядок, "
                "но отсутствие специального требования закона должно быть проверено отдельно.",
            )

        citations, verified = self._exact_sources(
            [
                ("GPK_RK", "5", "6", ""),
                ("GPK_RK", "148", "2", "6"),
                ("GPK_RK", "149", "1", "5"),
            ],
            as_of_date=as_of_date,
        )
        missing: list[str] = []
        if not self._has_evidence(case, EvidenceKind.CONTRACT):
            missing.append("договор с условием о досудебном порядке")
        if not self._has_evidence(case, EvidenceKind.PRETRIAL_DEMAND):
            missing.append("претензия/требование")
        if not self._has_evidence(case, EvidenceKind.PRETRIAL_DELIVERY):
            missing.append("доказательство направления/доставки претензии")
        if case.procedure.pretrial_demand_sent_date is None:
            missing.append("дата направления претензии")

        if not verified or missing:
            reason = "Не подтверждены обязательные элементы: " + ", ".join(missing) if missing else (
                "Точные процессуальные нормы досудебного порядка не прошли canonical-верификацию."
            )
            return self._needs("pretrial", reason, citations)

        return ProceduralItem(
            name="pretrial",
            status=VerificationStatus.VERIFIED,
            conclusion=(
                "Договорный досудебный порядок зафиксирован; претензия и доказательство ее "
                "направления/доставки присутствуют."
            ),
            sources=citations,
        )

    def _authority_item(self, case: LockedCase, *, as_of_date: date | None) -> ProceduralItem:
        kind = case.procedure.representative_kind
        if kind is None:
            return self._needs(
                "authority",
                "Не указан подписант и основание его полномочий; нельзя определить, кто вправе подписать иск.",
            )

        if kind == RepresentativeKind.DIRECTOR:
            citations, verified = self._exact_sources(
                [("GPK_RK", "57", "2", ""), ("GPK_RK", "148", "4", "")],
                as_of_date=as_of_date,
            )
            if not self._has_evidence(case, EvidenceKind.AUTHORITY):
                return self._needs(
                    "authority",
                    "Для руководителя юридического лица нужен документ, подтверждающий должность/полномочия.",
                    citations,
                )
            if not verified:
                return self._needs("authority", "Нормы о полномочиях руководителя не VERIFIED.", citations)
            return ProceduralItem(
                name="authority",
                status=VerificationStatus.VERIFIED,
                conclusion="Подписант указан как руководитель; документ о должности/полномочиях присутствует.",
                sources=citations,
            )

        locators = [
            ("GPK_RK", "60", "3", ""),
            ("GPK_RK", "61", "1", ""),
            ("GPK_RK", "148", "4", ""),
        ]
        if kind == RepresentativeKind.ADVOCATE:
            locators.append(("GPK_RK", "61", "3", ""))
        elif kind == RepresentativeKind.LEGAL_CONSULTANT:
            locators.append(("GPK_RK", "61", "5", ""))

        citations, verified = self._exact_sources(locators, as_of_date=as_of_date)
        missing: list[str] = []
        if not case.procedure.representative_name:
            missing.append("имя/наименование представителя")
        if case.procedure.representative_can_sign_claim is not True:
            missing.append("специальное полномочие на подписание иска")
        if not self._has_evidence(case, EvidenceKind.AUTHORITY):
            missing.append("доверенность/иной документ о полномочиях")
        if kind in {RepresentativeKind.ADVOCATE, RepresentativeKind.LEGAL_CONSULTANT} and not self._has_evidence(
            case, EvidenceKind.PROFESSIONAL_STATUS
        ):
            missing.append("документ профессионального статуса")

        if not verified or missing:
            reason = "Не подтверждены полномочия: " + ", ".join(missing) if missing else (
                "Точные нормы о полномочиях представителя не прошли canonical-верификацию."
            )
            return self._needs("authority", reason, citations)

        return ProceduralItem(
            name="authority",
            status=VerificationStatus.VERIFIED,
            conclusion="Полномочия представителя и специальное полномочие на подписание иска подтверждены.",
            sources=citations,
        )

    def _attachments_item(
        self,
        case: LockedCase,
        *,
        as_of_date: date | None,
    ) -> ProceduralItem:
        claimant = self._party(case, {PartyRole.CLAIMANT, PartyRole.CREDITOR})
        claimant_type = self._party_type(claimant)
        mode = case.procedure.filing_mode
        if mode is None:
            return self._needs(
                "attachments",
                "Не выбран способ подачи (paper/electronic), поэтому обязательный комплект приложений не фиксируется.",
            )

        locators: list[tuple[str, str, str, str]] = [
            ("GPK_RK", "149", "1", "2"),
            ("GPK_RK", "149", "1", "4"),
        ]
        if mode == FilingMode.PAPER:
            locators.append(("GPK_RK", "149", "1", "1"))
        else:
            locators.append(("GPK_RK", "149", "2", ""))
        if case.procedure.representative_kind not in {None, RepresentativeKind.DIRECTOR}:
            locators.append(("GPK_RK", "149", "1", "3"))
        if case.procedure.pretrial_required_by_contract is True:
            locators.append(("GPK_RK", "149", "1", "5"))
        if claimant_type == "legal_entity":
            locators.append(("GPK_RK", "149", "1", "7"))
        if self._has_evidence(case, EvidenceKind.RECONCILIATION):
            locators.append(("GPK_RK", "149", "1", "5-1"))

        citations, verified = self._exact_sources(locators, as_of_date=as_of_date)
        missing: list[str] = []
        if mode == FilingMode.PAPER and case.procedure.copies_prepared is not True:
            missing.append("копии иска и приложений по числу ответчиков/третьих лиц")
        if not self._has_evidence(case, EvidenceKind.STATE_DUTY_PAYMENT):
            missing.append("документ об уплате госпошлины либо ходатайство")
        if not any(
            evidence.kind in _MERITS_EVIDENCE and evidence.supports_fact_ids
            for evidence in case.evidence
        ):
            missing.append("доказательства обстоятельств иска")
        if case.procedure.representative_kind not in {None, RepresentativeKind.DIRECTOR} and not self._has_evidence(
            case, EvidenceKind.AUTHORITY
        ):
            missing.append("документ о полномочиях представителя")
        if case.procedure.pretrial_required_by_contract is True and (
            not self._has_evidence(case, EvidenceKind.PRETRIAL_DEMAND)
            or not self._has_evidence(case, EvidenceKind.PRETRIAL_DELIVERY)
        ):
            missing.append("документы о соблюдении досудебного порядка")
        if claimant_type == "legal_entity" and not self._has_evidence(case, EvidenceKind.REGISTRATION):
            missing.append("регистрационные документы юридического лица")

        if not verified or missing:
            reason = "Не хватает приложений: " + ", ".join(missing) if missing else (
                "Требования к приложениям не прошли canonical-верификацию."
            )
            return self._needs("attachments", reason, citations)

        return ProceduralItem(
            name="attachments",
            status=VerificationStatus.VERIFIED,
            conclusion="Обязательный комплект приложений для выбранного способа подачи подтвержден по зафиксированным данным.",
            sources=citations,
        )

    def _style_support_item(
        self,
        blueprint: DocumentBlueprint,
        *,
        as_of_date: date | None,
    ) -> ProceduralItem:
        """Resolve norms quoted for presentation only.

        The result is deliberately never NEEDS_VERIFICATION. A house-style quote the corpus cannot
        confirm is simply not printed, and reporting it as a legal gap would put a false
        NEEDS_VERIFICATION on a document whose actual legal content is fully determined.
        """
        citations, verified = self._exact_sources(
            list(blueprint.style_norm_locators),
            as_of_date=as_of_date,
        )
        return ProceduralItem(
            name=STYLE_SUPPORT_ITEM,
            status=VerificationStatus.VERIFIED if verified else VerificationStatus.NOT_APPLICABLE,
            conclusion=(
                "Формулировки фирменного стиля подтверждены по canonical-корпусу."
                if verified
                else "Стилевые цитаты недоступны в канoническом корпусе и не выводятся в документ."
            ),
            sources=[
                citation
                for citation in citations
                if citation.status == VerificationStatus.VERIFIED
            ],
        )

    def check(
        self,
        case: LockedCase,
        *,
        routing: RoutingDecision | None = None,
        calculation: CalculationResult | None = None,
        as_of_date: date | None = None,
        blueprint: DocumentBlueprint | None = None,
    ) -> ProceduralReport:
        issues = (
            blueprint.procedural_issues if blueprint is not None else tuple(PROCEDURAL_ISSUES)
        )
        items: list[ProceduralItem] = []
        for name in issues:
            issue = PROCEDURAL_ISSUES.get(name, name)
            if name == "state_duty":
                item = self._state_duty_item(case, routing, calculation, as_of_date=as_of_date)
            elif name == "jurisdiction":
                item = self._jurisdiction_item(case, routing, as_of_date=as_of_date)
            elif name == "limitation":
                item = self._limitation_item(case, as_of_date=as_of_date)
            elif name == "pretrial":
                item = self._pretrial_item(case, as_of_date=as_of_date)
            elif name == "authority":
                item = self._authority_item(case, as_of_date=as_of_date)
            elif name == "attachments":
                item = self._attachments_item(case, as_of_date=as_of_date)
            else:
                item = self._generic_item(name, issue, as_of_date=as_of_date)
            items.append(item)
        if blueprint is not None and blueprint.style_norm_locators:
            items.append(self._style_support_item(blueprint, as_of_date=as_of_date))
        return ProceduralReport(items=items)
