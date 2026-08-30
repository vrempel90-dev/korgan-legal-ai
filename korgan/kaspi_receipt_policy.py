from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from korgan.kaspi_ofd import _normalize, _parse_datetime

_CLOCK_SKEW = timedelta(minutes=2)
_FUTURE_SKEW = timedelta(minutes=5)
_PAYMENT_WINDOW = timedelta(minutes=60)

# One-time migration guard for customers who paid before the strict order-time
# policy was deployed. Only orders opened during the actual transition window
# may use an older (but still recent) fiscal receipt. All merchant/OFD/amount/
# uniqueness checks remain mandatory. Orders outside this window stay strict.
_LEGACY_ORDER_OPENED_NOT_BEFORE_UTC = datetime(2026, 8, 30, 10, 40, tzinfo=timezone.utc)
_LEGACY_ORDER_CUTOFF_UTC = datetime(2026, 8, 30, 11, 15, tzinfo=timezone.utc)
_LEGACY_RECEIPT_LOOKBACK = timedelta(days=7)
_LEGACY_BEFORE_ORDER_ISSUE = "фискальный чек создан до открытия текущей заявки на оплату"

_ZNM_RE = re.compile(r"(?:^|\n)\s*ЗНМ\s*[:№\-—]?\s*([A-Za-zА-Яа-я0-9_-]{4,40})", re.IGNORECASE)


def _merchant_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for raw in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", str(value or "")):
        normalized = _normalize(raw)
        if len(normalized) < 4:
            continue
        # Phone/card-like values are not merchant names. BIN/RNM handle identity
        # in that case, so do not make a numeric recipient string a false blocker.
        if normalized.isdigit():
            continue
        tokens.append(normalized)
    return tokens


def _legacy_existing_order_receipt_allowed(
    *,
    offer_time: datetime | None,
    receipt_time: datetime | None,
    current: datetime,
) -> bool:
    """Allow only a bounded, one-time grace for transition-window orders.

    This never bypasses merchant, amount, BIN, RNM, ZNM, FP, Kaspi OFD or
    duplicate-receipt checks. It removes only the blocker saying that a valid
    receipt predates a payment order recreated after the customer had paid.
    """
    if offer_time is None or receipt_time is None:
        return False
    if not (_LEGACY_ORDER_OPENED_NOT_BEFORE_UTC <= offer_time <= _LEGACY_ORDER_CUTOFF_UTC):
        return False
    if receipt_time > current + _FUTURE_SKEW:
        return False
    return receipt_time >= _LEGACY_ORDER_CUTOFF_UTC - _LEGACY_RECEIPT_LOOKBACK


def strict_receipt_issues(
    original: Callable[..., list[str]],
    receipt: Any,
    expected_amount: int,
    *,
    expected_recipient: str = "",
    expected_bin: str = "",
    offered_at: str | datetime | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Add the MiniApp payment policy on top of the Kaspi OFD verifier.

    Address and payer name are intentionally irrelevant. A third party may pay.
    Merchant identity is determined by the configured BIN/RNM plus merchant name
    when a textual recipient is configured.
    """
    issues = list(
        original(
            receipt,
            expected_amount,
            expected_recipient=expected_recipient,
            expected_bin=expected_bin,
            offered_at=offered_at,
            now=now,
        )
    )

    seller_name = str(getattr(receipt, "seller_name", "") or "").strip()
    raw_text = str(getattr(receipt, "raw_text", "") or "")
    if not seller_name:
        issues.append("в фискальном чеке не найден продавец/ИП")

    tokens = _merchant_tokens(expected_recipient)
    if tokens:
        merchant_haystack = _normalize(f"{seller_name}\n{raw_text}")
        if not any(token in merchant_haystack for token in tokens):
            issues.append("ИП/продавец в фискальном чеке не соответствует KORGAN")

    # ZNM is a stable cash-register attribute shown on Kaspi fiscal receipts.
    # We require its presence but do not compare the receipt address at all.
    if not _ZNM_RE.search(raw_text):
        issues.append("в фискальном чеке не найден ЗНМ")

    receipt_time = _parse_datetime(str(getattr(receipt, "sale_datetime", "") or ""))
    offer_time = _parse_datetime(offered_at) if offered_at is not None else None
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if _legacy_existing_order_receipt_allowed(
        offer_time=offer_time,
        receipt_time=receipt_time,
        current=current,
    ):
        issues = [issue for issue in issues if issue != _LEGACY_BEFORE_ORDER_ISSUE]

    if receipt_time is not None:
        if receipt_time > current + _FUTURE_SKEW:
            issues.append("дата/время фискального чека находятся недопустимо в будущем")
        if offer_time is not None:
            if receipt_time < offer_time - _CLOCK_SKEW:
                # Transition-window orders may use a bounded historical receipt;
                # all orders outside that window keep the base blocker.
                pass
            elif receipt_time > offer_time + _PAYMENT_WINDOW:
                issues.append("фискальный чек создан вне 60-минутного окна текущей оплаты")

    # Preserve order while removing duplicate blockers from layered checks.
    return list(dict.fromkeys(issues))


def install_receipt_policy(ofd_module: Any) -> None:
    original = ofd_module.fiscal_receipt_issues
    if getattr(original, "_korgan_strict_receipt_policy", False):
        return

    def wrapped(
        receipt: Any,
        expected_amount: int,
        *,
        expected_recipient: str = "",
        expected_bin: str = "",
        offered_at: str | datetime | None = None,
        now: datetime | None = None,
    ) -> list[str]:
        return strict_receipt_issues(
            original,
            receipt,
            expected_amount,
            expected_recipient=expected_recipient,
            expected_bin=expected_bin,
            offered_at=offered_at,
            now=now,
        )

    wrapped._korgan_strict_receipt_policy = True  # type: ignore[attr-defined]
    ofd_module.fiscal_receipt_issues = wrapped
