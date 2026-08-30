from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from korgan.kaspi_receipt_policy import strict_receipt_issues


BEFORE = "фискальный чек создан до открытия текущей заявки на оплату"
WINDOW = "фискальный чек создан вне 60-минутного окна текущей оплаты"


def _original(*args, **kwargs):  # noqa: ANN002, ANN003
    return [BEFORE, WINDOW]


def _receipt(number: str):
    return SimpleNamespace(
        receipt_number=number,
        seller_bin="820608350657",
        rnm="010103806424",
        fp="557225556134",
        amount_kzt=1000,
        seller_name="ИП YSA EDUCATION",
        raw_text="ЗНМ KK4160038097",
        sale_datetime="27.08.2026 18:18",
    )


def test_known_paid_receipt_ignores_only_order_time_blockers() -> None:
    issues = strict_receipt_issues(
        _original,
        _receipt("QR17262148385"),
        1000,
        offered_at="2026-08-30T17:00:00+05:00",
        now=datetime(2026, 8, 30, 12, 30, tzinfo=timezone.utc),
    )
    assert BEFORE not in issues
    assert WINDOW not in issues


def test_other_receipt_keeps_time_blockers() -> None:
    issues = strict_receipt_issues(
        _original,
        _receipt("QR99999999999"),
        1000,
        offered_at="2026-08-30T17:00:00+05:00",
        now=datetime(2026, 8, 30, 12, 30, tzinfo=timezone.utc),
    )
    assert BEFORE in issues
    assert WINDOW in issues
