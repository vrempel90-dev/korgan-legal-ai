"""Незаполненный запасной провайдер не должен ронять приложение — и не должен молчать.

Так выглядела вторая авария подряд. В Railway `OPENAI_API_KEY` объявлена
пустой. `build_legal_client` собирал клиента OpenAI первой же строкой,
безусловно — до того, как выяснится, что отвечать будет Anthropic. SDK на
пустой ключ отвечает отказом, отказ приходился на импорт `korgan.miniapp_api`,
и приложение не поднималось целиком из-за запасного пути, к которому при
работающем основном провайдере не обратились бы ни разу.

Обратная крайность так же опасна. Молча стерпеть отсутствие запасного ключа
значит получить конфигурацию, неотличимую от полной: `/health` отвечает
«anthropic», всё работает, а недостача обнаруживается ровно в момент отказа
Anthropic — то есть на живом клиенте, когда откатываться уже некуда.

Здесь зафиксирована середина: приложение поднимается, запасной провайдер
собирается только когда действительно нужен, а его отсутствие названо вслух —
при старте, в `/health` и в самом отказе, с именем переменной, которую надо
заполнить.
"""

from __future__ import annotations

import logging

import pytest

from korgan.ai_provider import (
    FALLBACK_UNCONFIGURED,
    OPENAI_KEY_VARIABLE,
    build_legal_client,
    build_openai_client,
    openai_configured,
)
from korgan.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "telegram_bot_token": "test-token",
        "openai_api_key": "test-key",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- приложение поднимается без запасного ключа ---


def test_a_missing_fallback_does_not_take_the_application_down() -> None:
    """Ровно то, что падало в Railway: Anthropic есть, OpenAI пуст."""
    client, provider = build_legal_client(
        _settings(anthropic_api_key="anthropic-key", openai_api_key="")
    )

    assert provider == "anthropic"
    assert client is not None


def test_the_fallback_is_not_built_until_it_is_needed() -> None:
    """Клиент запасного провайдера не собирается на старте.

    Если бы собирался, пустой ключ снова превратил бы возможную будущую
    деградацию в гарантированный отказ немедленно — что и произошло.
    """
    client, _ = build_legal_client(
        _settings(anthropic_api_key="anthropic-key", openai_api_key="")
    )

    fallback = client.responses._inner._secondary
    assert fallback._inner is None


def test_the_missing_fallback_is_said_out_loud_at_startup(caplog) -> None:
    """Конфигурация без запасного пути обязана быть слышна до отказа."""
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="korgan.ai_provider"):
        build_legal_client(_settings(anthropic_api_key="anthropic-key", openai_api_key=""))

    warnings = [r.getMessage() for r in caplog.records if OPENAI_KEY_VARIABLE in r.getMessage()]
    assert warnings, "отсутствие запасного провайдера прошло молча"


def test_a_configured_fallback_does_not_cry_wolf(caplog) -> None:
    """Предупреждение, которое горит всегда, перестают читать."""
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="korgan.ai_provider"):
        build_legal_client(_settings(anthropic_api_key="anthropic-key"))

    assert not [r for r in caplog.records if OPENAI_KEY_VARIABLE in r.getMessage()]


# --- где снисходительность заканчивается ---


def test_without_anthropic_the_missing_key_is_a_hard_blocker() -> None:
    """Здесь OpenAI не запасной, а единственный.

    Отсутствие ключа в этом случае — не потеря запасного пути, а невозможность
    ответить вообще. Поднять приложение, которое гарантированно откажет первому
    же клиенту, хуже, чем не подняться.
    """
    with pytest.raises(RuntimeError, match=OPENAI_KEY_VARIABLE):
        build_legal_client(_settings(openai_api_key=""))


def test_the_refusal_names_the_variable_to_fill_in() -> None:
    """SDK говорит про свой аргумент, а не про переменную Railway.

    «Missing credentials. Please pass an api_key…» отправляет читать код, а
    заполнять надо переменную сервиса. Разница стоила одного неверного
    диагноза целиком.
    """
    with pytest.raises(RuntimeError) as failure:
        build_openai_client(_settings(openai_api_key=""))

    assert OPENAI_KEY_VARIABLE in str(failure.value)
    assert "Railway" in str(failure.value)
    assert FALLBACK_UNCONFIGURED in str(failure.value)


def test_the_refusal_never_carries_the_key_itself() -> None:
    """Сообщение об отказе не место для секрета."""
    settings = _settings(openai_api_key="   ")

    with pytest.raises(RuntimeError) as failure:
        build_openai_client(settings)

    assert "test-key" not in str(failure.value)
    assert FALLBACK_UNCONFIGURED == str(failure.value)


def test_a_key_of_spaces_is_not_a_key() -> None:
    """Пробел в поле переменной не виден глазом и ключом не является."""
    assert openai_configured(_settings(openai_api_key="   ")) is False
    assert openai_configured(_settings()) is True


# --- видимость снаружи ---


def test_health_shows_whether_there_is_anywhere_to_fall_back_to() -> None:
    """До первого отказа недостачу видно только здесь."""
    from fastapi.testclient import TestClient

    from korgan.miniapp_api_recovery_cors import app

    with TestClient(app) as client:
        health = client.get("/health").json()

    assert health["ai_fallback_configured"] is True
    # Состояние, а не ключ: сам ключ наружу не отдаётся.
    assert "test-key" not in client.get("/health").text
