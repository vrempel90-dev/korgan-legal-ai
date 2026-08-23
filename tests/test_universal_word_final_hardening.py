from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.document_generator_ownership_guard import (
    StaleDocumentRequest,
    _guard_generator,
    _guard_quality_repair,
    _guard_service_draft,
)
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.universal_word_final_hardening import (
    install_universal_word_final_hardening,
    parse_money_exact,
    penalty_amount_from_source,
)


def _claim() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск о взыскании задолженности и неустойки",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["ТОО Истец"],
        defendant=["ТОО Ответчик"],
        price_of_claim="12 000 000 тенге",
        facts=[],
        legal_basis=[],
        requests=["Взыскать основной долг в размере 12 000 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_decimal_parser_preserves_integer_above_float_precision_limit() -> None:
    assert parse_money_exact("9 007 199 254 740 993") == 9_007_199_254_740_993
    assert parse_money_exact("10,50") == 11
    assert parse_money_exact("10,49") == 10


def test_professional_claim_price_recalculation_uses_exact_decimal_after_install() -> None:
    from korgan import professional_claim_finalizer as finalizer

    install_universal_word_final_hardening()
    draft = _claim()
    draft.requests = ["Взыскать 9 007 199 254 740 993 тенге основного долга."]

    finalizer._recalculate_price(draft)

    assert draft.price_of_claim == "9 007 199 254 740 993 тенге"


def test_penalty_extraction_does_not_confuse_principal_and_penalty_in_same_sentence() -> None:
    draft = _claim()
    context = (
        "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА: взыскать договорную неустойку.\n"
        "Пеня начислена на сумму долга 12 000 000 тенге и составила 996 000 тенге.\n"
        "Лимит неустойки — не более 10%, то есть 1 200 000 тенге."
    )

    assert penalty_amount_from_source(context, draft) == 996_000


def test_penalty_extraction_refuses_to_guess_without_explicit_source_demand() -> None:
    draft = _claim()
    context = (
        "Договор предусматривает пеню 0,1% в день. "
        "Пеня начислена на сумму долга 12 000 000 тенге и составила 996 000 тенге."
    )

    assert penalty_amount_from_source(context, draft) is None


class _FakeState:
    def __init__(self, kind: str, request_id: str) -> None:
        self.data = {
            "request_kind": kind,
            "request_id": request_id,
            "mode": "main",
        }

    async def get_data(self) -> dict:
        return dict(self.data)


async def _stale_during_initial_draft(kind: str) -> None:
    state = _FakeState(kind, "request-old")
    calls = {"draft": 0, "repair": 0}

    class FakeService:
        async def draft(self) -> dict:
            calls["draft"] += 1
            # Simulate the client opening another document while the initial
            # model draft is in flight. Any bounded repair must now be aborted.
            state.data["request_kind"] = "contract" if kind != "contract" else "claim"
            state.data["request_id"] = "request-new"
            return await self._quality_repair(current_payload={"safe": True})

        async def _quality_repair(self, **_kwargs) -> dict:
            calls["repair"] += 1
            return {"unsafe": True}

    _guard_service_draft(FakeService, "draft", kind)
    _guard_quality_repair(FakeService)

    async def generate(_message, _state):
        service = FakeService()
        try:
            await service.draft()
        except StaleDocumentRequest:
            return "stale"
        return "unexpected"

    module = SimpleNamespace(generate=generate)
    _guard_generator(module, "generate", kind)

    result = await module.generate(None, state)

    assert result == "stale"
    assert calls["draft"] == 1
    assert calls["repair"] == 0


def test_request_switch_aborts_repair_for_all_five_document_kinds() -> None:
    async def scenario() -> None:
        for kind in ("claim", "contract", "response", "pretrial", "pretrial_response"):
            await _stale_during_initial_draft(kind)

    asyncio.run(scenario())
