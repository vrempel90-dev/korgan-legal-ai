from __future__ import annotations

import re
from dataclasses import dataclass

from korgan_legal_ai.domain.models import DraftDocument, LockedCase, QAViolation, ResearchCitation, VerificationStatus


ARTICLE_RE = re.compile(r"\bстат(?:ья|ьи|ье|ью|ей)\s+(\d+[\-\d]*)", re.IGNORECASE)


@dataclass(frozen=True)
class FinalQAPolicy:
    code: str

    def check(
        self,
        *,
        case: LockedCase,
        document: DraftDocument,
        citations: list[ResearchCitation],
    ) -> list[QAViolation]:
        raise NotImplementedError


class PartyPresencePolicy(FinalQAPolicy):
    def check(self, *, case: LockedCase, document: DraftDocument, citations: list[ResearchCitation]) -> list[QAViolation]:
        missing = [p.name for p in case.parties if p.name not in document.text]
        if not missing:
            return []
        return [QAViolation(code=self.code, message=f"В документе отсутствуют стороны: {', '.join(missing)}")]


class ExactCitationPolicy(FinalQAPolicy):
    def check(self, *, case: LockedCase, document: DraftDocument, citations: list[ResearchCitation]) -> list[QAViolation]:
        used = set(ARTICLE_RE.findall(document.text))
        if not used:
            return []
        verified = {
            c.article.strip()
            for c in citations
            if c.status == VerificationStatus.VERIFIED and c.article
        }
        unknown = sorted(article for article in used if article not in verified)
        if not unknown:
            return []
        return [
            QAViolation(
                code=self.code,
                message="В тексте есть непроверенные точные номера статей: " + ", ".join(unknown),
            )
        ]


class OutcomeGuaranteePolicy(FinalQAPolicy):
    FORBIDDEN = ("вы точно выиграете", "суд обязательно удовлетворит", "гарантированно выигра")

    def check(self, *, case: LockedCase, document: DraftDocument, citations: list[ResearchCitation]) -> list[QAViolation]:
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [QAViolation(code=self.code, message="Документ содержит недопустимую гарантию исхода дела.")]


class FilingReadinessLanguagePolicy(FinalQAPolicy):
    FORBIDDEN = ("готов к подаче", "можно подавать без проверки")

    def check(self, *, case: LockedCase, document: DraftDocument, citations: list[ResearchCitation]) -> list[QAViolation]:
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [QAViolation(code=self.code, message="Система не может объявлять документ готовым к подаче без финальной проверки человеком.")]


class ClaimRoleDirectionPolicy(FinalQAPolicy):
    """For claims, claimant/creditor must stay on claimant side and defendant/debtor on defendant side."""

    def check(self, *, case: LockedCase, document: DraftDocument, citations: list[ResearchCitation]) -> list[QAViolation]:
        from korgan_legal_ai.domain.models import DocumentType, PartyRole

        if document.document_type != DocumentType.CLAIM:
            return []
        claimant = next((p for p in case.parties if p.role in {PartyRole.CLAIMANT, PartyRole.CREDITOR}), None)
        defendant = next((p for p in case.parties if p.role in {PartyRole.DEFENDANT, PartyRole.DEBTOR}), None)
        violations: list[QAViolation] = []
        if claimant and not re.search(rf"(?im)^\s*Истец\s*:\s*{re.escape(claimant.name)}\s*$", document.text):
            violations.append(QAViolation(code=self.code, message=f"Не подтверждено сохранение роли истца/кредитора: {claimant.name}"))
        if defendant and not re.search(rf"(?im)^\s*Ответчик\s*:\s*{re.escape(defendant.name)}\s*$", document.text):
            violations.append(QAViolation(code=self.code, message=f"Не подтверждено сохранение роли ответчика/должника: {defendant.name}"))
        return violations
