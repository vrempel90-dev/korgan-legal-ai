from korgan.civil_claim_hotfix import _core_profile_supported, _sanitize_civil_research
from korgan.legal_types import LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[
            "ГК РК, статья 715",
            "Налоговый кодекс РК, статья 610 о госпошлине",
        ],
        procedural_requirements=[
            "ГПК РК, статья 148",
            "Государственная пошлина по статье 610 НК РК",
        ],
        verified_claims=[
            "Передача денег может образовывать заем [основание: статья 715; источник: https://adilet.zan.kz/rus/docs/K990000409_]",
            "Заемщик обязан возвратить сумму займа [основание: статья 722; источник: https://adilet.zan.kz/rus/docs/K990000409_]",
            "Госпошлина по статье 610 [основание: статья 610; источник: https://adilet.zan.kz/rus/docs/K1700000120]",
        ],
        unverified_claims=[
            "Размер госпошлины требует проверки по Налоговому кодексу",
        ],
        source_urls=[
            "https://adilet.zan.kz/rus/docs/K990000409_",
            "https://adilet.zan.kz/rus/docs/K1700000120",
        ],
        notes=[],
    )


def test_state_duty_research_is_removed_from_civil_qualification() -> None:
    result = _sanitize_civil_research(_research())

    assert all("610" not in item for item in result.verified_claims)
    assert all("госпошлин" not in item.lower() for item in result.unverified_claims)
    assert any("715" in item for item in result.verified_claims)
    assert any("722" in item for item in result.verified_claims)


def test_loan_core_does_not_require_article_716_for_second_search() -> None:
    result = _sanitize_civil_research(_research())
    assert _core_profile_supported("loan_debt", result) is True
