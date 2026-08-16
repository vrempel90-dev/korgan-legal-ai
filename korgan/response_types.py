from __future__ import annotations

from dataclasses import dataclass, field

from korgan.legal_types import VerificationStatus


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
    objections: list[str] = field(default_factory=list)
    legal_basis: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)
    verification_notes: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)

    def body_lines(self) -> list[str]:
        return [
            self.title,
            self.court,
            self.case_number,
            *self.claimant,
            *self.defendant,
            *self.claim_summary,
            *self.position,
            *self.objections,
            *self.legal_basis,
            *self.requests,
            *self.attachments,
        ]
