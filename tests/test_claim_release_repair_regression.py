from __future__ import annotations

import asyncio

from korgan import claim_release_repair
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus


class _Finding:
    def as_note(self) -> str:
        return "исправить неподтвержденную правовую ссылку"


class _Citations:
    blocking = [_Finding()]


class _Release:
    citations = _Citations()
    integrity: list[object] = []


class _RepairService:
    async def _quality_repair(self, **kwargs):
        # Reproduce the production regression: the last model repair returns a
        # cleaner citation payload but loses the penalty, total claim price and
        # state-duty request that deterministic code had already calculated.
        return {
            "title": "Иск о взыскании задолженности и договорной неустойки",
            "court": "Специализированный межрайонный экономический суд города Астаны",
            "claimant": ["ТОО «Поставщик», БИН 123456789012"],
            "defendant": ["ТОО «Покупатель», БИН 210987654321"],
            "price_of_claim": "12 000 000 тенге",
            "facts": ["Товар поставлен, основной долг не оплачен."],
            "legal_basis": [],
            "requests": ["Взыскать с ответчика основной долг в размере 12 000 000 тенге."],
            "attachments": [],
            "verification_notes": [],
        }


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск о взыскании задолженности и договорной неустойки",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["ТОО «Поставщик», БИН 123456789012"],
        defendant=["ТОО «Покупатель», БИН 210987654321"],
        price_of_claim="12 996 000 тенге",
        facts=[],
        legal_basis=[],
        requests=[
            "Взыскать с ответчика основной долг в размере 12 000 000 тенге.",
            "Взыскать с ответчика договорную неустойку в размере 996 000 тенге.",
        ],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _context() -> str:
    return (
        "Истец: ТОО «Поставщик», БИН 123456789012. Ответчик: ТОО «Покупатель». "
        "По договору поставки основной долг составляет 12 000 000 тенге.\n"
        "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: Взыскать договорную неустойку в размере 996 000 тенге."
    )


def test_final_release_repair_reapplies_penalty_price_and_state_duty(monkeypatch) -> None:
    monkeypatch.setattr(claim_release_repair, "_repair_service", lambda: _RepairService())

    repaired = asyncio.run(
        claim_release_repair.repair_claim_release(
            context=_context(),
            research=_research(),
            draft=_draft(),
            language="ru",
            release=_Release(),
        )
    )

    assert repaired is not None
    requests = "\n".join(repaired.requests)
    assert "12 000 000" in requests
    assert "996 000" in requests
    assert "ТРЕБУЕТ ПРОВЕРКИ" in requests
    # No verified Art. 353 or contractual rate/date exists here: the exact
    # 996k survives only because it is explicit in source materials, never
    # because a model or statutory calculator invented it.
    assert repaired.late_interest == ""
    assert "государственной пошлины" in requests.lower()
    assert "12 996 000" in repaired.price_of_claim
    assert "389 880" in repaired.state_duty


def test_final_release_repair_keeps_kazakh_state_duty_request_single_language(monkeypatch) -> None:
    monkeypatch.setattr(claim_release_repair, "_repair_service", lambda: _RepairService())

    repaired = asyncio.run(
        claim_release_repair.repair_claim_release(
            context=_context(),
            research=_research(),
            draft=_draft(),
            language="kk",
            release=_Release(),
        )
    )

    assert repaired is not None
    duty_requests = [
        request
        for request in repaired.requests
        if "мемлекеттік баж" in request.lower() or "государственной пошлины" in request.lower()
    ]
    assert len(duty_requests) == 1
    assert "мемлекеттік баж" in duty_requests[0].lower()
    assert "государственной пошлины" not in duty_requests[0].lower()
    assert "389 880" in repaired.state_duty
