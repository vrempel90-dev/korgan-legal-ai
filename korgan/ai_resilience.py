"""Отказ чужого API не должен становиться отказом продукта.

Что происходило
---------------
Один вызов модели — одна попытка. Провайдер отвечал 429 или закрывал
соединение, обёртка немедленно уходила к запасному, а если и он был занят,
подготовка документа падала целиком. Оплаченная работа заканчивалась ничем
из-за секундной перегрузки на стороне поставщика.

Границы
-------
Повтор осмыслен ровно тогда, когда следующая попытка может дать другой ответ:
сеть не ответила, соединение оборвалось, вернулись 429 или 5xx. Ошибка запроса
(400, 401, 403, 404, 422) при повторе даст тот же ответ, и повторять её —
значит тратить бюджет времени клиента на заведомо известный отказ.

Отдельно и намеренно: отказ юридической проверки провайдерским сбоем не
является. Fail-closed остаётся fail-closed — иначе сознательный отказ выдать
документ без источников превратился бы в ещё одну попытку получить его любой
ценой. Такие исключения проходят через этот слой нетронутыми.

Число попыток ограничено сверху: подготовка документа живёт в бюджете около
двух минут, и бесконечный повтор оставил бы клиента ждать вечно вместо
честного «не получилось, повтор бесплатный».
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any, Awaitable, Callable

LOGGER = logging.getLogger(__name__)

TIMEOUT_ENV = "KORGAN_MODEL_CALL_TIMEOUT_SECONDS"
RETRIES_ENV = "KORGAN_MODEL_CALL_RETRIES"

#: Один вызов модели не вправе занять весь бюджет подготовки документа: за ним
#: ещё идут черновик, проверка и рендер Word.
_DEFAULT_TIMEOUT_SECONDS = 75.0
_MIN_TIMEOUT_SECONDS = 5.0
_MAX_TIMEOUT_SECONDS = 110.0

#: Повторов у одного провайдера, не считая первой попытки. Двух хватает, чтобы
#: пережить всплеск 429; больше — это уже ожидание, которого клиент не заказывал.
_DEFAULT_RETRIES = 1
_MAX_RETRIES = 3
_BASE_DELAY_SECONDS = 0.5
_MAX_DELAY_SECONDS = 4.0

#: Коды, при которых следующая попытка может дать другой ответ.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})

#: Имена классов исключений провайдеров. Сравнение по имени намеренно: SDK
#: обоих поставщиков не обязаны быть установлены одновременно, а импорт
#: отсутствующего пакета ради проверки типа уронил бы приложение.
_RETRYABLE_EXCEPTION_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
        "ServiceUnavailableError",
        "OverloadedError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
        "TimeoutException",
    }
)

#: Исключения продукта: юридический отказ, отказ выпуска, превышение бюджета.
#: Повторять их нельзя — они и есть результат, а не сбой связи.
_DOMAIN_EXCEPTION_NAMES = frozenset(
    {
        "GenerationFailure",
        "ReleaseBlocked",
        "ContractQualityBlocked",
        "DocumentGenerationTimeout",
        "HTTPException",
    }
)


def call_timeout_seconds() -> float:
    raw = str(os.getenv(TIMEOUT_ENV, "") or "").strip()
    try:
        configured = float(raw) if raw else _DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        configured = _DEFAULT_TIMEOUT_SECONDS
    return min(_MAX_TIMEOUT_SECONDS, max(_MIN_TIMEOUT_SECONDS, configured))


def call_retries() -> int:
    raw = str(os.getenv(RETRIES_ENV, "") or "").strip()
    try:
        configured = int(raw) if raw else _DEFAULT_RETRIES
    except ValueError:
        configured = _DEFAULT_RETRIES
    return min(_MAX_RETRIES, max(0, configured))


def _status_code(error: BaseException) -> int | None:
    for attribute in ("status_code", "http_status", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_domain_failure(error: BaseException) -> bool:
    """Отказ самого продукта, а не поставщика модели."""
    names = {type(item).__name__ for item in (error, *_causes(error))}
    return bool(names & _DOMAIN_EXCEPTION_NAMES)


def _causes(error: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.__cause__ or current.__context__
        if current is not None:
            chain.append(current)
        if len(chain) >= 4:
            break
    return tuple(chain)


def is_transient(error: BaseException) -> bool:
    """Может ли следующая попытка дать другой ответ."""
    if is_domain_failure(error):
        return False
    if isinstance(error, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return True

    for item in (error, *_causes(error)):
        if type(item).__name__ in _RETRYABLE_EXCEPTION_NAMES:
            return True
        status = _status_code(item)
        if status is not None and status in _RETRYABLE_STATUS:
            return True
        if status is not None and status >= 500:
            return True
    return False


def _delay_seconds(attempt: int) -> float:
    """Экспоненциальная пауза с разбросом.

    Разброс нужен не для красоты: без него все задачи, попавшие в одну волну
    429, повторяются синхронно и воспроизводят ту же перегрузку.
    """
    base = min(_MAX_DELAY_SECONDS, _BASE_DELAY_SECONDS * (2 ** max(0, attempt)))
    return base * (0.5 + random.random() / 2)


async def call_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    provider: str,
    timeout: float | None = None,
    retries: int | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Один вызов модели: с таймаутом и ограниченным числом повторов.

    Таймаут обязателен на каждой попытке. Без него зависшее соединение держит
    задачу до конца общего бюджета, а клиент всё это время видит работу,
    которой уже нет.
    """
    budget = call_timeout_seconds() if timeout is None else float(timeout)
    attempts = call_retries() if retries is None else max(0, int(retries))

    last_error: BaseException | None = None
    for attempt in range(attempts + 1):
        try:
            async with asyncio.timeout(budget):
                return await operation()
        except asyncio.CancelledError:
            # Отмену задачи повторять нельзя: её запросил тот, кто ждал ответа.
            raise
        except BaseException as error:  # noqa: BLE001 — решение принимается ниже по типу
            if not isinstance(error, Exception) and not isinstance(error, asyncio.TimeoutError):
                raise
            last_error = error
            if attempt >= attempts or not is_transient(error):
                raise
            pause = _delay_seconds(attempt)
            LOGGER.warning(
                "KORGAN model call retry provider=%s attempt=%d/%d reason=%s after=%.1fs",
                provider,
                attempt + 1,
                attempts,
                type(error).__name__,
                pause,
            )
            await sleep(pause)

    assert last_error is not None
    raise last_error
