"""Production startup must fail closed and must never leak secrets into logs."""
from __future__ import annotations

import io
import logging

import httpx
import pytest

from korgan_legal_ai.telegram.client import TelegramAPIError, TelegramBotAPI
from korgan_legal_ai.telegram.main import configure_logging, main
from korgan_legal_ai.telegram.runtime import TelegramRuntime

BOT_TOKEN = "123456:SUPERSECRETBOTTOKEN"


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Run with no .env file and no inherited Telegram/database configuration."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_SESSION_MASTER_KEY",
        "DATABASE_URL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_startup_requires_a_bot_token(isolated_env) -> None:
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        main()


def test_startup_refuses_to_run_without_a_database(isolated_env) -> None:
    isolated_env.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)

    # No silent downgrade to in-memory sessions when secure persistence is unavailable.
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        main()


def test_startup_refuses_to_run_without_a_session_master_key(isolated_env) -> None:
    isolated_env.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    isolated_env.setenv("DATABASE_URL", "postgresql+psycopg://postgres@localhost/korgan")

    with pytest.raises(RuntimeError, match="TELEGRAM_SESSION_MASTER_KEY"):
        main()


def test_runtime_has_no_default_session_backend() -> None:
    # An omitted store is a configuration error, not a quiet fallback to process memory.
    with pytest.raises(TypeError):
        TelegramRuntime(api=object(), engine=object())  # type: ignore[call-arg]


def test_configure_logging_keeps_the_bot_token_out_of_application_logs() -> None:
    configure_logging()

    # HTTP clients log full request URLs at INFO, and the Telegram URL embeds the bot token.
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING

    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True, "result": {"id": 1}})
        )
        api = TelegramBotAPI(BOT_TOKEN, client=httpx.Client(transport=transport))
        api.get_me()
        api.close()
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    assert "SUPERSECRETBOTTOKEN" not in captured.getvalue()


def test_transport_errors_never_carry_the_bot_token() -> None:
    def failing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    api = TelegramBotAPI(BOT_TOKEN, client=httpx.Client(transport=httpx.MockTransport(failing)))
    try:
        with pytest.raises(TelegramAPIError) as excinfo:
            api.get_me()
    finally:
        api.close()

    rendered = f"{excinfo.value}{excinfo.value.__cause__}{excinfo.value.__context__}"
    assert "SUPERSECRETBOTTOKEN" not in rendered


def test_api_rejection_messages_never_carry_the_bot_token() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"ok": False, "description": "Unauthorized"})
    )
    api = TelegramBotAPI(BOT_TOKEN, client=httpx.Client(transport=transport))
    try:
        with pytest.raises(TelegramAPIError) as excinfo:
            api.get_me()
    finally:
        api.close()

    assert "SUPERSECRETBOTTOKEN" not in str(excinfo.value)
