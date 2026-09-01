"""Обрыв справочника ставок должен быть слышен до того, как дойдёт до клиента.

Когда таблица базовой ставки кончается, неустойка перестаёт считаться и
помечается как требующая проверки. Отказ правильный — выдумывать ставку нельзя.
Плохо было другое: узнать о нём можно было либо из `/health`, куда без повода
никто не смотрит, либо из документа, уже отданного человеку.

Здесь проверяется, что состояние справочника попадает в лог при каждом старте
процесса — то есть туда, где дежурный видит его раньше клиента.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from korgan import claim_release_entrypoint as entrypoint
from korgan.legal_calc import NB_RATE_TABLE_VALID_THROUGH


def _log_with(monkeypatch, today: date, caplog) -> list[logging.LogRecord]:
    monkeypatch.setattr(
        entrypoint,
        "rates_freshness",
        lambda day=None: {
            "nb_base_rate_days_left": (NB_RATE_TABLE_VALID_THROUGH - today).days,
            "nb_base_rate_stale": today > NB_RATE_TABLE_VALID_THROUGH,
            "mrp_days_left": 300,
            "mrp_stale": False,
        },
    )
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=entrypoint.__name__):
        entrypoint._log_rates_freshness()
    return list(caplog.records)


def test_an_expiring_rate_table_is_a_warning_not_a_quiet_line(monkeypatch, caplog) -> None:
    records = _log_with(monkeypatch, NB_RATE_TABLE_VALID_THROUGH - timedelta(days=2), caplog)

    nb = [r for r in records if "базовая ставка" in r.getMessage()]
    assert len(nb) == 1
    assert nb[0].levelno == logging.WARNING
    assert "осталось 2 дн." in nb[0].getMessage()


def test_an_expired_rate_table_is_an_error(monkeypatch, caplog) -> None:
    records = _log_with(monkeypatch, NB_RATE_TABLE_VALID_THROUGH + timedelta(days=5), caplog)

    nb = [r for r in records if "базовая ставка" in r.getMessage()]
    assert len(nb) == 1
    assert nb[0].levelno == logging.ERROR
    assert "кончился 5 дн. назад" in nb[0].getMessage()


def test_a_healthy_table_does_not_cry_wolf(monkeypatch, caplog) -> None:
    """Предупреждение, которое горит всегда, перестают читать."""
    records = _log_with(monkeypatch, NB_RATE_TABLE_VALID_THROUGH - timedelta(days=90), caplog)

    nb = [r for r in records if "базовая ставка" in r.getMessage()]
    assert len(nb) == 1
    assert nb[0].levelno == logging.INFO


def test_mrp_is_reported_alongside_the_base_rate(monkeypatch, caplog) -> None:
    """Пошлина зависит от МРП так же, как неустойка от ставки."""
    records = _log_with(monkeypatch, NB_RATE_TABLE_VALID_THROUGH - timedelta(days=90), caplog)

    assert any("МРП" in record.getMessage() for record in records)
