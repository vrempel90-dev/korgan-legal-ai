"""Отсутствие правового обоснования нельзя ни спрятать, ни замаскировать.

Финальную сверку статей выполняет `claim_filing_accuracy._ground_legal_basis`, и
без собранного локального корпуса Adilet она не пропускает ни одной нормы: иск
уходит клиенту без раздела о праве. Отказ правильный — выдумывать статьи нельзя,
— но он был виден только внутри уже выданного документа. Здесь проверяется, что
это состояние видно заранее и что вёрстка не выдаёт его за заполненный раздел.
"""

from __future__ import annotations

from korgan.claim_corpus_health import legal_grounding_readiness
from korgan.claim_docx import build_claim_docx
from korgan.legal_types import ClaimDraft, VerificationStatus

from tests.test_pro_document_quality import _docx_lines  # noqa: F401  (единый рендер)


def _draft_without_law() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании задолженности",
        court="Специализированный межрайонный экономический суд города Алматы",
        claimant=["ТОО «Алтын Курылыс», БИН 123456789012"],
        defendant=["ТОО «Мега Строй», БИН 210987654321"],
        price_of_claim="4 500 000 тенге",
        facts=["20.01.2025 истец поставил товар на 4 500 000 тенге, оплата не произведена."],
        legal_basis=[],
        requests=["Взыскать с ответчика 4 500 000 тенге основного долга."],
        attachments=["Копия накладной № 44 от 20.01.2025"],
        verification_notes=[],
        source_urls=[],
        jurisdiction_reason="Спор между двумя юридическими лицами, ответчик находится в Алматы.",
        pretrial_compliance="Претензия направлена 03.03.2025, ответ не получен.",
        reconciliation_measures="Истец предлагал переговоры, соглашение не достигнуто.",
        limitation_period="Срок исковой давности не истёк.",
    )


def test_claim_without_law_does_not_show_a_legal_basis_heading() -> None:
    """Подсудность и досудебный порядок — не правовое обоснование требования.

    Пока они делили с нормами один заголовок, иск без единой статьи выглядел
    так, будто право в нём приведено.
    """
    lines = [line for line in _docx_lines(_draft_without_law())]
    body = "\n".join(lines)

    assert "Правовое обоснование" not in body, "заголовок про право стоит без единой нормы права"
    assert "Процессуальные обстоятельства" in body
    assert "Претензия направлена 03.03.2025" in body


def test_claim_with_law_keeps_the_legal_basis_heading() -> None:
    draft = _draft_without_law()
    draft.legal_basis = [
        "Обязательство должно исполняться надлежащим образом. Правовое основание: ст. 272 ГК РК (Общая часть)."
    ]

    body = "\n".join(_docx_lines(draft))

    assert "Правовое обоснование" in body
    assert "ст. 272 ГК РК" in body
    # Процессуальные обстоятельства остаются, но уже не подменяют собой право.
    assert "Процессуальные обстоятельства" in body
    assert body.index("Правовое обоснование") < body.index("Процессуальные обстоятельства")


def test_disabled_legal_grounding_is_reported_before_a_document_is_issued(monkeypatch) -> None:
    """Выключенная сверка — это отказ продукта, и он обязан быть виден заранее."""
    import korgan.claim_corpus_health as health

    monkeypatch.setattr(health, "local_corpus_enabled", lambda: False)
    state = legal_grounding_readiness()

    assert state["ready"] is False
    assert state["enabled"] is False
    assert "KORGAN_LOCAL_CORPUS" in state["reason"]


def test_unbuilt_corpus_is_reported_as_not_ready(monkeypatch) -> None:
    import korgan.claim_corpus_health as health

    monkeypatch.setattr(health, "local_corpus_enabled", lambda: True)
    monkeypatch.setattr(health, "open_corpus", lambda: None)
    state = legal_grounding_readiness()

    assert state["ready"] is False
    assert state["enabled"] is True
    assert "load_corpus" in state["reason"]


def test_health_endpoint_exposes_legal_grounding_state() -> None:
    from fastapi.testclient import TestClient

    from korgan.miniapp_api_recovery_cors import app

    with TestClient(app) as client:
        payload = client.get("/health").json()

    assert "legal_grounding" in payload, "состояние правовой сверки не видно в /health"
    assert set(payload["legal_grounding"]) >= {"enabled", "available", "ready", "reason"}
