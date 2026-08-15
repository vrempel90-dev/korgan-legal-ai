from __future__ import annotations

import re
from dataclasses import dataclass

from korgan_legal_ai.domain.models import (
    DraftDocument,
    LockedCase,
    QAViolation,
    ResearchCitation,
    VerificationStatus,
)


ARTICLE_RE = re.compile(
    r"\bстат(?:ья|ьи|ье|ью|ей)\s+"
    r"(?P<article>\d+(?:-\d+)?)"
    r"(?:\s*,?\s*(?:част(?:ь|и)|ч\.)\s*(?P<part>\d+))?"
    r"(?:\s*,?\s*(?:пункт(?:а|е|у|ом)?|п\.)\s*(?P<point>\d+))?",
    re.IGNORECASE,
)
CITATION_LOCATOR_RE = re.compile(
    r"^\s*(?P<article>\d+(?:-\d+)?)"
    r"(?:\s*,\s*часть\s+(?P<part>\d+))?"
    r"(?:\s*,\s*пункт\s+(?P<point>\d+))?\s*$",
    re.IGNORECASE,
)


def _locator(article: str, part: str | None, point: str | None) -> tuple[str, str, str]:
    return article, part or "", point or ""


def _citation_locator(value: str) -> tuple[str, str, str] | None:
    match = CITATION_LOCATOR_RE.match(value)
    if match is None:
        return None
    return _locator(match.group("article"), match.group("part"), match.group("point"))


def _format_locator(value: tuple[str, str, str]) -> str:
    article, part, point = value
    result = article
    if part:
        result += f", часть {part}"
    if point:
        result += f", пункт {point}"
    return result


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
    def check(
        self, *, case: LockedCase, document: DraftDocument,
        citations: list[ResearchCitation]
    ) -> list[QAViolation]:
        missing = [party.name for party in case.parties if party.name not in document.text]
        if not missing:
            return []
        return [
            QAViolation(
                code=self.code,
                message=f"В документе отсутствуют стороны: {', '.join(missing)}",
            )
        ]


class ExactCitationPolicy(FinalQAPolicy):
    """Require the exact canonical article/part/point locator used in the draft."""

    def check(
        self, *, case: LockedCase, document: DraftDocument,
        citations: list[ResearchCitation]
    ) -> list[QAViolation]:
        used = {
            _locator(match.group("article"), match.group("part"), match.group("point"))
            for match in ARTICLE_RE.finditer(document.text)
        }
        if not used:
            return []

        verified: set[tuple[str, str, str]] = set()
        for citation in citations:
            if citation.status != VerificationStatus.VERIFIED or not citation.article:
                continue
            parsed = _citation_locator(citation.article.strip())
            if parsed is not None:
                verified.add(parsed)

        unknown = sorted(_format_locator(value) for value in used if value not in verified)
        if not unknown:
            return []
        return [
            QAViolation(
                code=self.code,
                message=(
                    "В тексте есть непроверенные или неточно процитированные нормы: "
                    + ", ".join(unknown)
                ),
            )
        ]


class OutcomeGuaranteePolicy(FinalQAPolicy):
    FORBIDDEN = ("вы точно выиграете", "суд обязательно удовлетворит", "гарантированно выигра")

    def check(
        self, *, case: LockedCase, document: DraftDocument,
        citations: list[ResearchCitation]
    ) -> list[QAViolation]:
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [
            QAViolation(
                code=self.code,
                message="Документ содержит недопустимую гарантию исхода дела.",
            )
        ]


class FilingReadinessLanguagePolicy(FinalQAPolicy):
    FORBIDDEN = ("готов к подаче", "можно подавать без проверки")

    def check(
        self, *, case: LockedCase, document: DraftDocument,
        citations: list[ResearchCitation]
    ) -> list[QAViolation]:
        lower = document.text.lower()
        if not any(phrase in lower for phrase in self.FORBIDDEN):
            return []
        return [
            QAViolation(
                code=self.code,
                message=(
                    "Система не может объявлять документ готовым к подаче "
                    "без финальной проверки человеком."
                ),
            )
        ]


class ClaimRoleDirectionPolicy(FinalQAPolicy):
    """For claims, claimant/creditor must stay on claimant side and defendant/debtor on defendant side."""

    def check(
        self, *, case: LockedCase, document: DraftDocument,
        citations: list[ResearchCitation]
    ) -> list[QAViolation]:
        from korgan_legal_ai.domain.models import DocumentType, PartyRole

        if document.document_type != DocumentType.CLAIM:
            return []
        claimant = next(
            (party for party in case.parties if party.role in {PartyRole.CLAIMANT, PartyRole.CREDITOR}),
            None,
        )
        defendant = next(
            (party for party in case.parties if party.role in {PartyRole.DEFENDANT, PartyRole.DEBTOR}),
            None,
        )
        violations: list[QAViolation] = []
        if claimant and not re.search(
            rf"(?im)^\s*Истец\s*:\s*{re.escape(claimant.name)}\s*$", document.text
        ):
            violations.append(
                QAViolation(
                    code=self.code,
                    message=f"Не подтверждено сохранение роли истца/кредитора: {claimant.name}",
                )
            )
        if defendant and not re.search(
            rf"(?im)^\s*Ответчик\s*:\s*{re.escape(defendant.name)}\s*$", document.text
        ):
            violations.append(
                QAViolation(
                    code=self.code,
                    message=f"Не подтверждено сохранение роли ответчика/должника: {defendant.name}",
                )
            )
        return violations
