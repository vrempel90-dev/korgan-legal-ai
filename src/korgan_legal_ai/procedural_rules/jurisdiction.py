from __future__ import annotations

from datetime import date

from korgan_legal_ai.domain.models import VerificationStatus
from korgan_legal_ai.procedural_rules.basis import LegalBasisVerifier
from korgan_legal_ai.procedural_rules.models import JurisdictionResult
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository


class JurisdictionResolver:
    def __init__(self, repository: ProceduralRuleRepository, basis_verifier: LegalBasisVerifier) -> None:
        self.repository = repository
        self.basis_verifier = basis_verifier

    def resolve(
        self, *, plaintiff_type: str, defendant_type: str,
        dispute_type: str, event_date: date
    ) -> JurisdictionResult:
        subject = self.repository.find_jurisdiction(
            dimension="subject_matter", plaintiff_type=plaintiff_type,
            defendant_type=defendant_type, dispute_type=dispute_type, event_date=event_date,
        )
        territorial = self.repository.find_jurisdiction(
            dimension="territorial", plaintiff_type=plaintiff_type,
            defendant_type=defendant_type, dispute_type=dispute_type, event_date=event_date,
        )
        if subject is None or territorial is None:
            return JurisdictionResult(
                status=VerificationStatus.NEEDS_VERIFICATION,
                verification_note="Both canonical subject-matter and territorial rules are required.",
            )
        subject_citation = self.basis_verifier.verify(subject.basis, event_date=event_date)
        territorial_citation = self.basis_verifier.verify(territorial.basis, event_date=event_date)
        if subject_citation is None or territorial_citation is None:
            return JurisdictionResult(
                status=VerificationStatus.NEEDS_VERIFICATION,
                verification_note="A jurisdiction rule exists, but at least one legal basis is not VERIFIED.",
            )
        return JurisdictionResult(
            status=VerificationStatus.VERIFIED,
            court_type=subject.result_code,
            territorial_rule=territorial.result_code,
            citations=[subject_citation, territorial_citation],
            verification_note=(
                "This identifies the verified court type and territorial rule, not a fabricated court name. "
                "A concrete court still requires the defendant's verified location."
            ),
        )
