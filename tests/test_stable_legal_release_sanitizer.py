from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.stable_legal_release import sanitize_research_sources


def test_sanitizer_removes_ru_and_kk_article_148_but_keeps_material_law() -> None:
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Форма иска определяется законом. [основание: статья 148 ГПК РК; текст нормы: форма; источник: https://adilet.zan.kz/rus/docs/K1500000377]",
            "Талап нысаны заңмен белгіленеді. [основание: 148-бап АПК РК; текст нормы: нысан; источник: https://adilet.zan.kz/rus/docs/K1500000377]",
            "Обязательство исполняется надлежащим образом. [основание: статья 272 ГК РК; текст нормы: исполнение; источник: https://adilet.zan.kz/rus/docs/K940001000_]",
        ],
        unverified_claims=[],
        source_urls=[
            "https://adilet.zan.kz/rus/docs/K1500000377",
            "https://adilet.zan.kz/rus/docs/K940001000_",
        ],
        notes=[],
    )

    result = sanitize_research_sources(research)
    joined = "\n".join(result.verified_claims)

    assert "148 ГПК" not in joined
    assert "148-бап АПК" not in joined
    assert "272 ГК" in joined
    assert result.status is VerificationStatus.VERIFIED


def test_sanitizer_downgrades_when_only_form_article_remains() -> None:
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Иск должен соответствовать форме. [основание: ст. 148 ГПК РК; текст нормы: форма; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
        notes=[],
    )

    result = sanitize_research_sources(research)

    assert result.verified_claims == []
    assert result.status is VerificationStatus.NEEDS_VERIFICATION
