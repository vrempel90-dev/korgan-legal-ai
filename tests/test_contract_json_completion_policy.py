from korgan.contract_generation_hotfix import _CONTRACT_OUTPUT_LIMITS


def test_all_contract_retry_budgets_exceed_first_attempt() -> None:
    for first, retry in _CONTRACT_OUTPUT_LIMITS.values():
        assert retry > first
