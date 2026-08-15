from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"


@dataclass(frozen=True, slots=True)
class LegalSource:
    title: str
    article: str
    url: str
    text: str
    score: float


@dataclass(frozen=True, slots=True)
class LegalAnswer:
    status: VerificationStatus
    text: str
    sources: tuple[LegalSource, ...] = ()
