from korgan.professional_service import (
    _PROFESSIONAL_RESEARCH_SCHEMA,
    _claim_strategy_block,
    _professional_research_prompt,
    _strategy_notes,
)
from korgan.legal_types import LegalResearch, VerificationStatus


def test_professional_research_prompt_is_issue_driven_not_article_patched():
    prompt = _professional_research_prompt(
        "Истец просит взыскать деньги по спору из договора.",
        max_chars=60000,
        checked_on="2026-08-16",
    )

    assert "юридические отношения" in prompt
    assert "юридически значимые элементы" in prompt
    assert "evidence_map" in prompt
    assert "основной способ защиты" in prompt
    assert "adilet.zan.kz" in prompt

    # The generic core must not hard-code one old test case or a fixed set of
    # article numbers. Exact provisions are discovered source-bound per matter.
    assert "статьи 715" not in prompt
    assert "статьи 716" not in prompt
    assert "статьи 722" not in prompt
    assert "возврат предоплаты" not in prompt.lower()


def test_strategy_notes_preserve_case_theory_remedies_evidence_and_risks():
    payload = {
        "notes": ["VERIFIED_COURT: Районный суд"],
        "case_theory": ["Основное основание требования"],
        "remedies": ["Взыскание основного долга"],
        "evidence_map": ["Факт передачи -> банковская квитанция"],
        "risks": ["Не подтверждено получение претензии"],
    }

    notes = _strategy_notes(payload)
    assert "CASE_THEORY: Основное основание требования" in notes
    assert "REMEDY: Взыскание основного долга" in notes
    assert "EVIDENCE_MAP: Факт передачи -> банковская квитанция" in notes
    assert "RISK: Не подтверждено получение претензии" in notes


def test_claim_strategy_block_uses_research_strategy_without_changing_runtime_types():
    research = LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=["Подтвержденная норма"],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/example"],
        notes=[
            "CASE_THEORY: Договорное требование",
            "REMEDY: Взыскание задолженности",
            "EVIDENCE_MAP: Обязательство -> договор",
        ],
    )

    block = _claim_strategy_block(research)
    assert "CASE_THEORY: Договорное требование" in block
    assert "REMEDY: Взыскание задолженности" in block
    assert "EVIDENCE_MAP: Обязательство -> договор" in block


def test_professional_research_schema_is_bounded_for_interactive_generation() -> None:
    properties = _PROFESSIONAL_RESEARCH_SCHEMA["properties"]
    assert properties["verified_points"]["maxItems"] == 10
    for name in (
        "applicable_law",
        "procedural_requirements",
        "case_theory",
        "remedies",
        "evidence_map",
        "risks",
        "unverified_claims",
        "notes",
    ):
        assert 1 <= properties[name]["maxItems"] <= 8
