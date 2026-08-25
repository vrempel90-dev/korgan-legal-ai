from __future__ import annotations

import asyncio
from types import SimpleNamespace

from korgan.claim_money_authority import reconcile_claim_money
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.pipeline_invariants_v2 import BlockerClass, _semantic_issues, classify_issue, exact_client_diagnostics
from korgan.pretrial import PretrialDraft
from korgan.pretrial_money_invariant import ensure_pretrial_money
from korgan import request_scope


MONEY_FIXTURE = (
    "Просим взыскать задолженность в размере 3 250 000 тенге и договорную неустойку. "
    "По договору предусмотрена договорная неустойка 0,2% от суммы задолженности "
    "за каждый календарный день просрочки, но не более 20%. "
    "Просрочка с 08.03.2026 по 25.08.2026 включительно."
)


def _claim() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="И С К о взыскании задолженности и договорной неустойки",
        court="[ДАННЫЕ: суд]",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="",
        facts=[],
        legal_basis=[],
        requests=["Взыскать с ответчика основной долг."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def _pretrial() -> PretrialDraft:
    return PretrialDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Досудебная претензия",
        sender=["Кредитор"],
        recipient=["Должник"],
        facts=[],
        legal_basis=[],
        demands=["Просим произвести расчет пени и уплатить ее."],
        deadline="",
        consequences=[],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_i5_source_money_reaches_claim_ledger_and_cap_is_applied() -> None:
    draft = _claim()

    result = reconcile_claim_money(MONEY_FIXTURE, draft)

    assert result.ledger.total == 3_900_000
    assert result.price == 3_900_000
    assert draft.price_of_claim == "3 900 000 тенге"
    assert any("3 250 000 тенге" in request for request in draft.requests)
    assert any("650 000 тенге" in request for request in draft.requests)
    calculation = "\n".join(draft.facts)
    assert "650 000 тенге" in calculation
    assert "15.06.2026" in calculation


def test_i2_pretrial_cannot_degrade_calculable_penalty_to_calculate_yourself() -> None:
    draft = _pretrial()

    result = ensure_pretrial_money(MONEY_FIXTURE, draft)

    assert result.calculated is True
    assert result.amount == 650_000
    assert result.cap_reached_on == "2026-06-15"
    demands = "\n".join(draft.demands).lower()
    assert "650 000 тенге" in demands
    assert "произвести расчет" not in demands
    facts = "\n".join(draft.facts)
    assert "3 250 000 тенге" in facts
    assert "650 000 тенге" in facts
    assert "15.06.2026" in facts


def test_i2_missing_penalty_period_is_visible_user_data_not_silent_degradation() -> None:
    draft = _pretrial()
    context = MONEY_FIXTURE.replace(" Просрочка с 08.03.2026 по 25.08.2026 включительно.", "")

    result = ensure_pretrial_money(context, draft)

    assert result.calculated is False
    assert "дата начала" in result.issue
    assert "[ДАННЫЕ:" in "\n".join(draft.demands)
    assert result.issue in draft.verification_notes


def test_i3_article_469_paraphrase_is_internal_quality() -> None:
    issue = (
        "FINAL_RELEASE_CITATION: статья 469 ГК РК: пересказ обобщает узкое условие нормы: "
        "норма формулирует право, а не обязанность"
    )

    assert classify_issue(issue) is BlockerClass.INTERNAL_QUALITY
    message = exact_client_diagnostics("claim", [issue])
    assert "INTERNAL_QUALITY" in message
    assert "469" in message
    assert "право, а не обязанность" in message


def test_i3_missing_bin_is_user_data() -> None:
    issue = "Не указан БИН истца во входных материалах"

    assert classify_issue(issue) is BlockerClass.NEEDS_USER_DATA
    assert "NEEDS_USER_DATA" in exact_client_diagnostics("claim", [issue])


def test_i7_semantic_blockers_match_across_layer_prefixes() -> None:
    first = ["T2: статья 469 ГК РК: пересказ обобщает узкое условие нормы"]
    second = ["FINAL_RELEASE_CITATION: статья 469 ГК РК: пересказ обобщает узкое условие нормы"]

    assert _semantic_issues(first) == _semantic_issues(second)


class _FakeState:
    def __init__(self) -> None:
        self.key = SimpleNamespace(bot_id=1, chat_id=10, user_id=20, thread_id=None)
        self._data: dict[str, object] = {}

    async def get_data(self):
        return dict(self._data)

    async def set_data(self, data):
        self._data = dict(data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)
        return dict(self._data)


def test_i10_new_request_cancels_old_heavy_task_before_next_generation() -> None:
    async def scenario() -> None:
        state = _FakeState()
        await request_scope.start_new_document_request(state, kind="claim", mode="claim_waiting")
        registered = asyncio.Event()
        cancelled = asyncio.Event()

        async def old_generation() -> None:
            try:
                request_id = await request_scope.current_request_id(state, "claim")
                assert request_id
                registered.set()
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(old_generation())
        await asyncio.wait_for(registered.wait(), timeout=1)
        await request_scope.start_new_document_request(state, kind="pretrial", mode="pretrial_waiting")
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("previous heavy generation task was not cancelled")

        data = await state.get_data()
        assert data["request_kind"] == "pretrial"

    asyncio.run(scenario())
