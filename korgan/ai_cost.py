"""Сколько стоит каждый вызов модели и сколько уже потрачено.

Зачем модуль существует
-----------------------
`monthly_ai_budget_usd` в настройках до сих пор был числом, которое попадало
только в текст лог-сообщения. Ни одного места, где считалось бы фактическое
потребление, в проекте не было: «бюджет на четыре месяца» нельзя ни
подтвердить, ни опровергнуть, если расход нигде не измеряется. Здесь он
измеряется.

Считается по цифрам, которые вернул сам провайдер — `usage.input_tokens`,
`usage.output_tokens` и число выполненных веб-поисков, — а не по оценке длины
промпта. Это разные величины: серверный поиск дописывает в контекст найденные
страницы, и реальный input оказывается в разы больше отправленного.

Веб-поиск считается отдельной строкой не для полноты. У обоих провайдеров он
стоит $10 за 1000 запросов, то есть цент за поиск, и юридическое исследование
делает их несколько на документ. При месячном ориентире в $10 это не
округление, а заметная доля бюджета.

Цены
----
Проверены по официальным страницам тарифов 1 сентября 2026 года. Цена, которую
никто не подтвердил, не выдумывается: неизвестная модель попадает в
`unpriced_calls`, её токены считаются, а стоимость — нет. Занизить расход
молчаливой подстановкой «примерно как у похожей модели» хуже, чем честно
показать, что часть вызовов не оценена.
"""

from __future__ import annotations

import logging
import time
from typing import Any

LOGGER = logging.getLogger(__name__)

# Модель -> (цена входа, цена выхода) в долларах за миллион токенов.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # Anthropic, platform.claude.com/docs/en/about-claude/pricing
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI, developers.openai.com/api/docs/pricing
    "gpt-5.1": (1.25, 10.00),
}

# $10 за 1000 поисков — совпадает у обоих провайдеров.
WEB_SEARCH_USD_PER_CALL = 0.01


def price_for(model: str) -> tuple[float, float] | None:
    """Цена модели с учётом суффиксов вида `gpt-5.1-2026-01-01`."""
    name = (model or "").strip().lower()
    if not name:
        return None
    if name in PRICES_USD_PER_MTOK:
        return PRICES_USD_PER_MTOK[name]
    for known, price in PRICES_USD_PER_MTOK.items():
        if name.startswith(known + "-"):
            return price
    return None


def usage_of(response: Any) -> tuple[int, int, int]:
    """Токены и число веб-поисков из ответа любого из двух провайдеров.

    Поиски считаются по элементам `web_search_call` в `output`. Правило одно
    для обоих: адаптер Anthropic выдаёт ровно такой же элемент на каждый
    `web_search_tool_result`, поэтому отдельная ветка на провайдера не нужна.
    """
    usage = getattr(response, "usage", None)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

    searches = 0
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "web_search_call":
            searches += 1
    return input_tokens, output_tokens, searches


def cost_of(model: str, input_tokens: int, output_tokens: int, searches: int) -> float | None:
    """Стоимость вызова в долларах, либо None для неизвестной модели."""
    price = price_for(model)
    if price is None:
        return None
    input_price, output_price = price
    return (
        input_tokens * input_price / 1_000_000
        + output_tokens * output_price / 1_000_000
        + searches * WEB_SEARCH_USD_PER_CALL
    )


class CostMeter:
    """Накопленный расход процесса.

    Счётчик живёт в памяти и обнуляется при рестарте — это ограничение названо
    прямо в имени поля `spend_usd_since_start`. Записать «за месяц» число,
    которое на деле означает «с последнего деплоя», значило бы отчитываться
    цифрой, которой нельзя верить.
    """

    def __init__(self, budget_usd: float = 0.0):
        self.budget_usd = budget_usd
        self.started_at = time.time()
        self.calls = 0
        self.unpriced_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.web_searches = 0
        self.spend_usd = 0.0
        self._over_budget_warned = False

    def record(self, model: str, response: Any) -> float | None:
        """Учесть один ответ. Не поднимает исключений.

        Счётчик стоимости не имеет права уронить генерацию документа: клиент
        платит за документ, а не за телеметрию. Любая неожиданная форма ответа
        приводит к пропуску записи, а не к отказу в ответе.
        """
        try:
            input_tokens, output_tokens, searches = usage_of(response)
            cost = cost_of(model, input_tokens, output_tokens, searches)
            self.calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.web_searches += searches
            if cost is None:
                self.unpriced_calls += 1
            else:
                self.spend_usd += cost
            self._warn_once_over_budget()
            return cost
        except Exception:  # noqa: BLE001 — учёт расхода не ломает генерацию
            LOGGER.warning("KORGAN cost meter skipped a response", exc_info=True)
            return None

    @property
    def over_budget(self) -> bool:
        return self.budget_usd > 0 and self.spend_usd >= self.budget_usd

    def _warn_once_over_budget(self) -> None:
        """Предупредить о превышении один раз, а не на каждом вызове.

        Именно предупредить, а не отказать. Отказ в генерации на середине
        оплаченного документа — это потеря денег клиента, а не экономия: он уже
        заплатил, и обрыв конвейера из-за счётчика оставил бы его без документа
        и с оплатой. Решение о лимите принимает оператор, увидев расход.
        """
        if self._over_budget_warned or not self.over_budget:
            return
        self._over_budget_warned = True
        LOGGER.warning(
            "KORGAN AI budget reached: spend_usd=%.2f budget_usd=%.2f calls=%d searches=%d",
            self.spend_usd,
            self.budget_usd,
            self.calls,
            self.web_searches,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "spend_usd_since_start": round(self.spend_usd, 4),
            "budget_usd_month": round(self.budget_usd, 2),
            "calls": self.calls,
            "unpriced_calls": self.unpriced_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "web_searches": self.web_searches,
            "measuring_since": int(self.started_at),
        }


# Единственный счётчик процесса. Глобальный сознательно: расход измеряется в
# одной точке — обёртке клиента, — а показывается в другой, в /health, и
# протягивать его через двадцать классов цепочки наследования означало бы
# тронуть двадцать конструкторов ради одного числа.
METER = CostMeter()
