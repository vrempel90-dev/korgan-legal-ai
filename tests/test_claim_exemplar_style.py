from __future__ import annotations

from korgan.claim_exemplar_style import CLAIM_EXEMPLAR_STYLE, exemplar_body_blocks, with_claim_exemplar_style
from korgan.docx_blocks import AutoNumberedList, Prose
from korgan.legal_types import ClaimDraft, VerificationStatus


def test_style_is_anonymized_and_preserves_fact_lock() -> None:
    enriched = with_claim_exemplar_style("Между истцом и ответчиком заключен договор поставки.")
    assert "И С К" in enriched
    assert "не копируй" in enriched.lower()
    assert "персональные данные" in enriched.lower()
    assert "source-bound" in enriched
    assert "Магия детства" not in CLAIM_EXEMPLAR_STYLE
    assert "SYMAN" not in CLAIM_EXEMPLAR_STYLE


def test_style_context_is_idempotent() -> None:
    first = with_claim_exemplar_style("Факты")
    second = with_claim_exemplar_style(first)
    assert first == second


def _draft(**overrides) -> ClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="И С К\nо взыскании суммы задолженности",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="1 000 000 тенге",
        state_duty="30 000 тенге",
        facts=["Между сторонами заключен договор."],
        legal_basis=["Статья 623 ГК РК предусматривает обязанность оплатить принятый результат работ."],
        requests=["Взыскать 1 000 000 тенге."],
        attachments=["Договор."],
        verification_notes=[],
        source_urls=[],
    )
    data.update(overrides)
    return ClaimDraft(**data)


def test_russian_claim_body_uses_classic_prose_not_ai_section_heading() -> None:
    blocks = exemplar_body_blocks(_draft(), kk=False)
    rendered = "\n".join(str(getattr(block, "text", getattr(block, "items", block))) for block in blocks)
    transition = next(block for block in blocks if getattr(block, "text", "").startswith("Правовое обоснование"))
    assert isinstance(transition, Prose)
    assert "На основании вышеизложенного ПРОШУ СУД:" in rendered
    assert "Приложения:" in rendered


def test_renderer_emits_exactly_one_prayer_transition() -> None:
    draft = _draft(
        facts=[
            "Между сторонами заключен договор.",
            "На основании вышеизложенного ПРОШУ СУД:",
        ],
        legal_basis=[
            "Статья 623 ГК РК предусматривает обязанность оплатить результат работ.",
            "На основании вышеизложенного и руководствуясь нормами закона ПРОШУ СУД:",
        ],
    )
    blocks = exemplar_body_blocks(draft, kk=False)
    transitions = [
        getattr(block, "text", "")
        for block in blocks
        if "ПРОШУ СУД" in getattr(block, "text", "").upper()
    ]
    assert transitions == ["На основании вышеизложенного ПРОШУ СУД:"]


def test_renderer_owns_numbering_for_petitum_and_attachments() -> None:
    blocks = exemplar_body_blocks(
        _draft(
            requests=["1. Взыскать основной долг.", "2. Взыскать неустойку."],
            attachments=["1. Договор.", "2. Акт."],
        ),
        kk=False,
    )
    lists = [block for block in blocks if isinstance(block, AutoNumberedList)]
    assert len(lists) == 2
    assert lists[0].items == ["Взыскать основной долг.", "Взыскать неустойку."]
    assert lists[1].items == ["Договор.", "Акт."]
