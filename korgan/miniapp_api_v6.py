from __future__ import annotations

import re
from typing import Any

from korgan import miniapp_api_v5 as v5

app = v5.app
core = v5.core
settings = v5.settings
PARITY_REVISION = "2026-08-27.auto-payment-v6-recipient-aliases"

_original_strict_receipt_issues = v5._strict_receipt_issues


def _recipient_aliases(value: str) -> list[str]:
    """Allow one or more merchant aliases separated by | or ;.

    Kaspi fiscal receipts may show the legal merchant name, a branch suffix,
    or the IP/LLP prefix instead of the KORGAN product brand.
    """
    return [part.strip() for part in re.split(r"[|;]+", str(value or "")) if part.strip()]


def _recipient_matches(actual_recipient: str, configured_recipient: str) -> bool:
    actual = v5._normalize_recipient(actual_recipient)
    if not actual:
        return False

    for alias in _recipient_aliases(configured_recipient):
        expected = v5._normalize_recipient(alias)
        if not expected:
            continue
        if actual == expected:
            return True
        # Accept stable legal-name variants such as
        # "YSA EDUCATION" vs "YSA education на Кунаева" or "ИП YSA EDUCATION".
        # Keep the minimum length high enough to avoid matching generic words.
        if len(expected) >= 6 and (expected in actual or actual in expected):
            return True
    return False


def _strict_receipt_issues(check: Any, expected_amount: int, *, offered_at: Any) -> list[str]:
    issues = _original_strict_receipt_issues(check, expected_amount, offered_at=offered_at)
    mismatch = "получатель платежа не соответствует KORGAN"
    if mismatch not in issues:
        return issues

    recipient = str(v5._check_value(check, "merchant_or_recipient", "") or "").strip()
    configured = str(settings.kaspi_payment_recipient or "").strip()
    if configured and _recipient_matches(recipient, configured):
        issues = [issue for issue in issues if issue != mismatch]
    return issues


# v5 route handlers resolve these globals at request time, so patching the
# Mini App payment module changes only receipt validation. The legal AI runtime,
# prompts, document generation and quality gates are untouched.
v5._strict_receipt_issues = _strict_receipt_issues
v5.PARITY_REVISION = PARITY_REVISION
