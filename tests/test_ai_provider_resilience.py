"""Сбой чужого API не должен становиться отказом продукта — и не должен течь к клиенту.

Раньше на каждый вызов модели приходилась ровно одна попытка: 429 у основного
провайдера немедленно уводил к запасному, а если и он был занят, оплаченная
подготовка документа заканчивалась ничем.
"""

from __future__ import annotations

import asyncio

import pytest

from korgan import ai_provider, ai_resilience


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class RateLimitError(_Status):
    pass


class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class InternalServerError(_Status):
    pass


class BadRequestError(_Status):
    pass


async def _no_sleep(_seconds: float) -> None:
    return None


def _run(operation, **kwargs):
    return asyncio.run(
        ai_resilience.call_with_retry(operation, provider="test", sleep=_no_sleep, **kwargs)
    )


# --- классификация ---------------------------------------------------------

@pytest.mark.parametrize(
    "error",
    [
        APITimeoutError(),
        APIConnectionError(),
        RateLimitError(429),
        InternalServerError(500),
        _Status(502),
        _Status(503),
        _Status(504),
        TimeoutError(),
        ConnectionResetError(),
    ],
)
def test_transient_provider_failures_are_retried(error: Exception) -> None:
    assert ai_resilience.is_transient(error) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_permanent_request_errors_are_not_retried(status: int) -> None:
    assert ai_resilience.is_transient(_Status(status)) is False


def test_legal_fail_closed_is_never_treated_as_an_api_failure() -> None:
    """Отказ юридической проверки — результат, а не сбой связи."""
    from korgan.miniapp_generation_jobs import GenerationFailure

    error = GenerationFailure("Документ не прошёл финальную проверку")
    assert ai_resilience.is_domain_failure(error) is True
    assert ai_resilience.is_transient(error) is False


# --- повтор ----------------------------------------------------------------

def test_timeout_on_the_first_attempt_is_retried_and_succeeds() -> None:
    attempts: list[int] = []

    async def operation():
        attempts.append(1)
        if len(attempts) == 1:
            raise APITimeoutError()
        return "ok"

    assert _run(operation, retries=1) == "ok"
    assert len(attempts) == 2


def test_rate_limit_is_retried_within_the_bound() -> None:
    attempts: list[int] = []

    async def operation():
        attempts.append(1)
        raise RateLimitError(429)

    with pytest.raises(RateLimitError):
        _run(operation, retries=2)
    assert len(attempts) == 3, "повторов ровно столько, сколько разрешено — не больше"


def test_server_error_is_retried_but_never_endlessly() -> None:
    attempts: list[int] = []

    async def operation():
        attempts.append(1)
        raise InternalServerError(503)

    with pytest.raises(InternalServerError):
        _run(operation, retries=1)
    assert len(attempts) == 2


def test_permanent_error_is_not_retried_at_all() -> None:
    attempts: list[int] = []

    async def operation():
        attempts.append(1)
        raise BadRequestError(400)

    with pytest.raises(BadRequestError):
        _run(operation, retries=3)
    assert len(attempts) == 1


def test_every_model_call_has_an_explicit_timeout() -> None:
    async def hanging():
        await asyncio.sleep(10)

    with pytest.raises(TimeoutError):
        _run(hanging, retries=0, timeout=0.05)


def test_retry_bound_is_capped_by_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ai_resilience.RETRIES_ENV, "99")
    assert ai_resilience.call_retries() <= 3
    monkeypatch.setenv(ai_resilience.TIMEOUT_ENV, "9999")
    assert ai_resilience.call_timeout_seconds() <= 115.0


# --- откат на запасного провайдера ----------------------------------------

class _Responses:
    def __init__(self, behaviour) -> None:
        self.calls = 0
        self._behaviour = behaviour

    async def create(self, **_kwargs):
        self.calls += 1
        return self._behaviour(self.calls)


class _Client:
    def __init__(self, behaviour) -> None:
        self.responses = _Responses(behaviour)


def _fallback_client(primary_behaviour, secondary_behaviour):
    primary = _Client(primary_behaviour)
    secondary = _Client(secondary_behaviour)
    client = ai_provider.FallbackClient(
        primary,
        secondary,
        primary_name="anthropic",
        secondary_name="openai",
    )
    return client, primary, secondary


def _raise(error):
    def behaviour(_call):
        raise error
    return behaviour


def test_primary_failure_falls_back_to_the_secondary_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ai_resilience.RETRIES_ENV, "0")
    client, primary, secondary = _fallback_client(
        _raise(RateLimitError(429)),
        lambda _call: "secondary",
    )
    assert asyncio.run(client.responses.create(model="m")) == "secondary"
    assert primary.responses.calls == 1
    assert secondary.responses.calls == 1


def test_both_providers_failing_surfaces_a_client_safe_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Клиент видит понятный текст, а не APIError, код состояния и трассировку."""
    from korgan import miniapp_generation_jobs as jobs

    monkeypatch.setenv(ai_resilience.RETRIES_ENV, "0")
    client, _primary, _secondary = _fallback_client(
        _raise(RateLimitError(429)),
        _raise(InternalServerError(500)),
    )
    with pytest.raises(InternalServerError) as failure:
        asyncio.run(client.responses.create(model="secret-model-name"))

    message = jobs._client_detail(failure.value)
    assert message == jobs._TECHNICAL_FAILURE
    lowered = message.lower()
    for leak in ("apierror", "429", "500", "http", "traceback", "secret-model-name", "openai", "anthropic"):
        assert leak not in lowered
    assert "повторная попытка не потребует повторной оплаты" in lowered


def test_legal_fail_closed_never_reaches_the_secondary_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from korgan.miniapp_generation_jobs import GenerationFailure

    monkeypatch.setenv(ai_resilience.RETRIES_ENV, "0")
    client, _primary, secondary = _fallback_client(
        _raise(GenerationFailure("Юридическая проверка не пройдена")),
        lambda _call: "secondary",
    )
    with pytest.raises(GenerationFailure):
        asyncio.run(client.responses.create(model="m"))
    assert secondary.responses.calls == 0


def test_single_provider_setup_also_retries_and_times_out() -> None:
    """Без запасного пути откатываться некуда — повтор обязан быть и здесь."""
    attempts: list[int] = []

    def behaviour(call: int):
        attempts.append(call)
        if call == 1:
            raise APITimeoutError()
        return "ok"

    bounded = ai_provider.BoundedClient(_Client(behaviour), provider="openai")
    assert asyncio.run(bounded.responses.create(model="m")) == "ok"
    assert attempts == [1, 2]


def test_next_attempt_succeeds_after_a_previous_api_failure() -> None:
    """Один упавший вызов не отравляет следующий: состояние не переносится."""
    client, _primary, _secondary = _fallback_client(
        _raise(RateLimitError(429)),
        lambda call: f"secondary-{call}",
    )
    assert asyncio.run(client.responses.create(model="m")) == "secondary-1"
    assert asyncio.run(client.responses.create(model="m")) == "secondary-2"


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("нет файла"), PermissionError("нет прав"), IsADirectoryError("каталог")],
)
def test_local_os_errors_are_not_mistaken_for_network_failures(error: Exception) -> None:
    """OSError бывает и не сетевым: повторять «нет прав» бессмысленно."""
    assert ai_resilience.is_transient(error) is False


def test_cancellation_is_never_retried() -> None:
    """Отмену запросил тот, кто ждал ответа: повтор здесь — работа впустую."""
    attempts: list[int] = []

    async def operation():
        attempts.append(1)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _run(operation, retries=3)
    assert len(attempts) == 1
