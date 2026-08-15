from __future__ import annotations

from korgan_legal_ai.domain.models import LockedCase, ProceduralItem, ProceduralReport, VerificationStatus
from korgan_legal_ai.research.gateway import CitationGateway


PROCEDURAL_ISSUES = {
    "jurisdiction": "Компетентный суд и территориальная/родовая подсудность",
    "pretrial": "Обязательный досудебный или претензионный порядок",
    "limitation": "Срок исковой давности и иные процессуальные сроки",
    "state_duty": "Размер и порядок расчета государственной пошлины",
    "authority": "Процессуальный статус и полномочия представителя",
    "attachments": "Обязательные приложения к иску",
}


class ProceduralChecker:
    def __init__(self, gateway: CitationGateway) -> None:
        self.gateway = gateway

    def check(self, case: LockedCase) -> ProceduralReport:
        items: list[ProceduralItem] = []
        for name, issue in PROCEDURAL_ISSUES.items():
            citations = self.gateway.research(issue)
            verified = bool(citations) and all(c.status == VerificationStatus.VERIFIED for c in citations)
            status = VerificationStatus.VERIFIED if verified else VerificationStatus.NEEDS_VERIFICATION
            conclusion = (
                "Проверено по официальному источнику."
                if verified
                else "Требует проверки по официальному источнику перед финальной юридической проверкой."
            )
            items.append(ProceduralItem(name=name, status=status, conclusion=conclusion, sources=citations))
        return ProceduralReport(items=items)
