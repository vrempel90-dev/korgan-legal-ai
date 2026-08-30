from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from korgan.kaspi_receipt_policy import strict_receipt_issues


def _receipt(*, sale_datetime: str = "2026-08-30 10:05:00", seller_name: str = "ИП YSA EDUCATION", raw_text: str | None = None):
    return SimpleNamespace(
        sale_datetime=sale_datetime,
        seller_name=seller_name,
        raw_text=raw_text
        or """Фискальный чек
Оплата совершена
ИП YSA EDUCATION
Адрес г. Астана, Кунаева, 29/1
ИИН/БИН продавца 820608350657
ФИО покупателя Другой Плательщик
РНМ 010103806424
ЗНМ KK4160038097
ФП 557225556134
ОФД Kaspi ОФД
""",
    )


def _base(*args, **kwargs):
    return []


def test_fresh_receipt_accepts_merchant_and_ignores_address_and_payer():
    issues = strict_receipt_issues(
        _base,
        _receipt(),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        expected_bin="820608350657",
        offered_at="2026-08-30T10:00:00+05:00",
        now=datetime(2026, 8, 30, 5, 10, tzinfo=timezone.utc),
    )
    assert issues == []


def test_existing_pre_migration_order_accepts_recent_already_paid_receipt():
    def base(*args, **kwargs):
        return ["фискальный чек создан до открытия текущей заявки на оплату"]

    issues = strict_receipt_issues(
        base,
        _receipt(sale_datetime="2026-08-27 18:18:22"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        expected_bin="820608350657",
        offered_at="2026-08-30T11:00:00+00:00",
        now=datetime(2026, 8, 30, 11, 10, tzinfo=timezone.utc),
    )
    assert "фискальный чек создан до открытия текущей заявки на оплату" not in issues


def test_new_order_keeps_strict_before_order_rejection():
    def base(*args, **kwargs):
        return ["фискальный чек создан до открытия текущей заявки на оплату"]

    issues = strict_receipt_issues(
        base,
        _receipt(sale_datetime="2026-08-27 18:18:22"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        expected_bin="820608350657",
        offered_at="2026-08-30T11:16:00+00:00",
        now=datetime(2026, 8, 30, 11, 20, tzinfo=timezone.utc),
    )
    assert "фискальный чек создан до открытия текущей заявки на оплату" in issues


def test_pre_migration_order_does_not_accept_arbitrarily_old_receipt():
    def base(*args, **kwargs):
        return ["фискальный чек создан до открытия текущей заявки на оплату"]

    issues = strict_receipt_issues(
        base,
        _receipt(sale_datetime="2026-08-20 18:18:22"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        expected_bin="820608350657",
        offered_at="2026-08-30T11:00:00+00:00",
        now=datetime(2026, 8, 30, 11, 10, tzinfo=timezone.utc),
    )
    assert "фискальный чек создан до открытия текущей заявки на оплату" in issues


def test_receipt_before_current_order_is_rejected_by_base_policy():
    def base(*args, **kwargs):
        return ["фискальный чек создан до открытия текущей заявки на оплату"]

    issues = strict_receipt_issues(
        base,
        _receipt(sale_datetime="2026-08-30 09:40:00"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        offered_at="2026-08-30T10:00:00+05:00",
        now=datetime(2026, 8, 30, 5, 10, tzinfo=timezone.utc),
    )
    assert "фискальный чек создан до открытия текущей заявки на оплату" in issues


def test_receipt_outside_sixty_minute_payment_window_is_rejected():
    issues = strict_receipt_issues(
        _base,
        _receipt(sale_datetime="2026-08-30 11:01:00"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        offered_at="2026-08-30T10:00:00+05:00",
        now=datetime(2026, 8, 30, 6, 2, tzinfo=timezone.utc),
    )
    assert "фискальный чек создан вне 60-минутного окна текущей оплаты" in issues


def test_receipt_more_than_five_minutes_in_future_is_rejected():
    issues = strict_receipt_issues(
        _base,
        _receipt(sale_datetime="2026-08-30 10:16:00"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        offered_at="2026-08-30T10:00:00+05:00",
        now=datetime(2026, 8, 30, 5, 10, tzinfo=timezone.utc),
    )
    assert "дата/время фискального чека находятся недопустимо в будущем" in issues


def test_wrong_merchant_is_rejected_even_when_address_is_present():
    issues = strict_receipt_issues(
        _base,
        _receipt(seller_name="ИП ЧУЖОЙ ПРОДАВЕЦ", raw_text="ИП ЧУЖОЙ ПРОДАВЕЦ\nЗНМ KK4160038097\nАдрес любой"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        offered_at="2026-08-30T10:00:00+05:00",
        now=datetime(2026, 8, 30, 5, 10, tzinfo=timezone.utc),
    )
    assert "ИП/продавец в фискальном чеке не соответствует KORGAN" in issues


def test_missing_znm_is_rejected():
    issues = strict_receipt_issues(
        _base,
        _receipt(raw_text="ИП YSA EDUCATION\nРНМ 010103806424\nФП 557225556134\nОФД Kaspi ОФД"),
        1000,
        expected_recipient="ИП YSA EDUCATION",
        offered_at="2026-08-30T10:00:00+05:00",
        now=datetime(2026, 8, 30, 5, 10, tzinfo=timezone.utc),
    )
    assert "в фискальном чеке не найден ЗНМ" in issues
