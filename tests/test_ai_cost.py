"""Расход на модель измеряется, а не оценивается на глаз.

`monthly_ai_budget_usd` до сих пор был числом, которое попадало только в текст
лог-сообщения. Эти тесты держат то, что заменило его на измерение: цены,
подсчёт веб-поисков, отказ выдумывать цену незнакомой модели и обещание не
уронить генерацию документа ради телеметрии.
"""

from __future__ import annotations

import asyncio
from functools import wraps
from types import SimpleNamespace

from korgan.ai_cost import (
    WEB_SEARCH_USD_PER_CALL,
    CostMeter,
    cost_of,
    price_for,
    usage_of,
)
from korgan.ai_provider import MeteredClient


def _sync(test):
    @wraps(test)
    def run(*args: object, **kwargs: object) -> None:
        asyncio.run(test(*args, **kwargs))

    return run


def _response(model: str, input_tokens: int, output_tokens: int, searches: int = 0):
    return SimpleNamespace(
        model=model,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        output=[SimpleNamespace(type="web_search_call") for _ in range(searches)],
    )


def test_dated_model_keeps_the_price_of_its_family() -> None:
    assert price_for("gpt-5.1-2026-01-01") == price_for("gpt-5.1")
    assert price_for("claude-sonnet-5") == (2.00, 10.00)


def test_unknown_model_has_no_invented_price() -> None:
    """Цена, которую никто не подтвердил, не выдумывается."""
    assert price_for("some-future-model") is None
    assert cost_of("some-future-model", 1_000_000, 1_000_000, 0) is None


def test_web_search_is_counted_as_its_own_line() -> None:
    """Поиск стоит цент, и на документ их несколько — при $10 в месяц это заметно."""
    tokens_only = cost_of("claude-sonnet-5", 100_000, 10_000, 0)
    with_searches = cost_of("claude-sonnet-5", 100_000, 10_000, 4)
    assert tokens_only is not None and with_searches is not None
    assert round(with_searches - tokens_only, 6) == round(4 * WEB_SEARCH_USD_PER_CALL, 6)


def test_cost_follows_the_published_rate() -> None:
    # Claude Sonnet 5: $2 за миллион входа, $10 за миллион выхода.
    assert cost_of("claude-sonnet-5", 1_000_000, 0, 0) == 2.00
    assert cost_of("claude-sonnet-5", 0, 1_000_000, 0) == 10.00


def test_searches_are_counted_the_same_way_for_both_providers() -> None:
    _, _, searches = usage_of(_response("claude-sonnet-5", 10, 10, searches=3))
    assert searches == 3


def test_meter_accumulates_tokens_searches_and_spend() -> None:
    meter = CostMeter(budget_usd=10.0)
    meter.record("claude-sonnet-5", _response("claude-sonnet-5", 1_000_000, 100_000, searches=2))

    snapshot = meter.snapshot()
    assert snapshot["input_tokens"] == 1_000_000
    assert snapshot["output_tokens"] == 100_000
    assert snapshot["web_searches"] == 2
    # 2.00 за вход + 1.00 за выход + 0.02 за два поиска.
    assert snapshot["spend_usd_since_start"] == 3.02
    assert snapshot["budget_usd_month"] == 10.0
    assert not meter.over_budget


def test_unpriced_call_is_reported_rather_than_hidden() -> None:
    meter = CostMeter(budget_usd=10.0)
    meter.record("some-future-model", _response("some-future-model", 500_000, 50_000))

    snapshot = meter.snapshot()
    assert snapshot["unpriced_calls"] == 1
    # Токены посчитаны, стоимость — нет: занижать расход молча нельзя.
    assert snapshot["input_tokens"] == 500_000
    assert snapshot["spend_usd_since_start"] == 0.0


def test_over_budget_is_visible() -> None:
    meter = CostMeter(budget_usd=1.0)
    meter.record("claude-sonnet-5", _response("claude-sonnet-5", 1_000_000, 0))
    assert meter.over_budget


def test_broken_response_does_not_break_the_document() -> None:
    """Клиент платит за документ, а не за телеметрию."""
    meter = CostMeter(budget_usd=10.0)

    class Hostile:
        @property
        def usage(self):  # noqa: ANN201
            raise RuntimeError("нет такого поля")

    assert meter.record("claude-sonnet-5", Hostile()) is None
    assert meter.snapshot()["calls"] == 0


@_sync
async def test_metered_client_prices_by_the_model_that_answered() -> None:
    """При работе через Anthropic вызывающий код всё ещё передаёт имя OpenAI.

    Учёт по переданному имени считал бы расход Claude по тарифу gpt-5.1.
    """
    meter = CostMeter(budget_usd=10.0)
    answered = _response("claude-sonnet-5", 1_000_000, 0)

    async def create(**kwargs: object) -> object:
        return answered

    client = MeteredClient(SimpleNamespace(responses=SimpleNamespace(create=create)), meter)
    await client.responses.create(model="gpt-5.1", input="вопрос")

    # Тариф Claude Sonnet 5 ($2), а не gpt-5.1 ($1.25).
    assert meter.snapshot()["spend_usd_since_start"] == 2.00
