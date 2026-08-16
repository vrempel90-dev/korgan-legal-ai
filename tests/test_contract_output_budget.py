from korgan.contract_generation_hotfix import _CONTRACT_OUTPUT_LIMITS


def test_contract_draft_budget_is_large_enough_for_full_docx_payload() -> None:
    first, retry = _CONTRACT_OUTPUT_LIMITS["korgan_contract_draft"]
    assert first >= 12000
    assert retry > first


def test_contract_research_budget_avoids_previous_2200_token_cutoff() -> None:
    first, retry = _CONTRACT_OUTPUT_LIMITS["korgan_contract_research"]
    assert first >= 5000
    assert retry > first
