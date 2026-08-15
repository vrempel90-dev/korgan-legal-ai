"""Synthetic claim fixtures. Entirely invented parties — no KORGAN client data."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from korgan_legal_ai.domain.models import (
    Fact,
    Financials,
    LockedCase,
    Party,
    PartyRole,
    ProcedureFacts,
)

SYNTHETIC_CLAIMANT = "ТОО «Arman Logistics»"
SYNTHETIC_DEFENDANT = "ТОО «Nova Trade»"


def synthetic_partial_payment_case() -> LockedCase:
    """Invoice partially paid: the classic double-counting shape, with invented parties."""
    return LockedCase(
        raw_text="synthetic fixture",
        parties=[
            Party(name=SYNTHETIC_CLAIMANT, role=PartyRole.CLAIMANT),
            Party(name=SYNTHETIC_DEFENDANT, role=PartyRole.DEFENDANT),
        ],
        facts=[Fact(statement="Услуги перевозки оказаны, оплата поступила частично")],
        financials=Financials(
            contract_amount=Decimal("3600000"),
            payments=[Decimal("1200000")],
            penalty=Decimal("158400"),
        ),
        procedure=ProcedureFacts(obligation_due_date=date(2026, 6, 3)),
    )
