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
from korgan.legal_calc import (
    NB_RATE_TABLE_VALID_THROUGH,
    late_penalty_line,
    needs_rate_marker,
    next_rate_decision_on,
)


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


# --- отказ считать неустойку называет причину и срок ---


def test_the_refusal_names_the_day_the_rate_becomes_knowable() -> None:
    """Маркер должен отличать «сломалось» от «ставки ещё не существует».

    После обрыва справочника в документ вместо суммы уходит маркер. Голый
    маркер выглядит как неисправность и посылает юриста искать ставку — а
    искать нечего: до заседания Нацбанка её не назовёт никто. Дата заседания
    публикуется заранее, поэтому отказ обязан её называть.
    """
    marker = needs_rate_marker(date(2026, 11, 1))

    assert "01.11.2026" in marker
    assert "04.12.2026" in marker
    # Значение ставки при этом по-прежнему не подставляется ни в каком виде.
    assert "%" not in marker


def test_the_refusal_does_not_contradict_itself_on_the_meeting_day() -> None:
    """Заседание может прийтись ровно на спорную дату.

    Формулировка «на эту дату не объявлено, ближайшее объявление 04.09.2026»
    для 04.09.2026 читается как противоречие и подрывает доверие ко всему
    остальному, что написано в том же абзаце документа.
    """
    marker = needs_rate_marker(date(2026, 9, 4))

    assert "объявляется 04.09.2026" in marker
    assert "не объявлено" not in marker


def test_beyond_the_published_schedule_the_refusal_says_so_plainly() -> None:
    """График заседаний тоже конечен, и выдумывать его продолжение нельзя."""
    marker = needs_rate_marker(date(2027, 3, 1))

    assert "не опубликован" in marker
    assert next_rate_decision_on(date(2027, 3, 1)) is None


def test_the_published_schedule_starts_after_the_confirmed_table() -> None:
    """График и таблица ставок должны стыковаться, а не перекрываться.

    Если ближайшее заседание попадает внутрь подтверждённого периода, значит
    одно из двух устарело: либо решение уже принято и не внесено в таблицу,
    либо `valid_through` продлён дальше, чем подтверждено источником. И то и
    другое молча даёт неверную ставку в расчёте.
    """
    first = next_rate_decision_on(date(1999, 1, 1))

    assert first is not None
    assert first > NB_RATE_TABLE_VALID_THROUGH


def test_a_document_without_a_rate_never_shows_a_number_instead(monkeypatch) -> None:
    """Ни при каких условиях отказ не превращается в подставленную ставку."""
    monkeypatch.setattr("korgan.legal_calc.base_rate_on", lambda *a, **k: None)

    line = late_penalty_line(None, rate_date=date(2026, 11, 1))

    assert line.startswith("[ТРЕБУЕТ ПРОВЕРКИ")
    assert "тенге" not in line
