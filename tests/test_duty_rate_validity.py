from datetime import date

import pytest

from korgan.legal.calc import RateUnavailable, load_rates, state_duty


def test_configured_state_duty_rejects_date_after_verified_period() -> None:
    rates = load_rates()
    with pytest.raises(RateUnavailable):
        state_duty(1_000_000, rates=rates, day=date(2027, 1, 1))
