from __future__ import annotations

from korgan.claim_exemplar_style import CLAIM_EXEMPLAR_STYLE, exemplar_body_blocks, with_claim_exemplar_style
from korgan.docx_blocks import Prose
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


def test_russian_claim_body_uses_classic_prose_not_ai_section_heading() -> None:
    draft = ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="И С К\nо взыскании суммы задолженности",
        court="Суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="1 000 000 тенге",
        state_duty="30 000 тенге",
        facts=["Между сторонами заключен договор."],
        legal_basis=["Согласно подтвержденной норме обязательство подлежит исполнению."],
        requests=["Взыскать 1 000 000 тенге."],
        attachments=["Договор."],
        verification_notes=[],
        source_urls=[],
    )
    blocks = exemplar_body_blocks(draft, kk=False)
    rendered = "\n".join(str(getattr(block, "text", getattr(block, "items", block))) for block in blocks)
    transition = next(block for block in blocks if getattr(block, "text", "").startswith("Правовое обоснование"))
    assert isinstance(transition, Prose)
    assert "На основании вышеизложенного ПРОШУ СУД:" in rendered
    assert "Приложения:" in rendered
