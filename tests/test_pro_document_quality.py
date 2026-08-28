"""Политика качества генерации и профессиональные разделы иска.

Эти тесты закрывают ровно те два места, из-за которых документы выходили
конспектами: отключённое рассуждение с обрезающим лимитом вывода и отсутствие
в схеме полей под процессуальный слой иска.
"""

from __future__ import annotations

import io

import pytest
from docx import Document

from korgan.claim_docx import build_claim_docx
from korgan.legal_types import ClaimDraft, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.pro_claim_sections import PRO_CLAIM_FIELDS, pro_payload, pro_text
from korgan.pro_document_quality import (
    DEFAULT_DRAFT_EFFORT,
    DRAFTING_SCHEMAS,
    apply,
    is_drafting,
    output_limit_for,
    reasoning_for,
)


# ---------------------------------------------------------------------------
# Политика reasoning и лимитов
# ---------------------------------------------------------------------------


def test_drafting_call_gets_reasoning():
    """Составление иска — задача, ради которой reasoning и существует."""
    assert reasoning_for("korgan_court_ready_claim", "gpt-5.1") == {"effort": DEFAULT_DRAFT_EFFORT}
    assert reasoning_for("korgan_fast_professional_claim", "gpt-5.1") == {"effort": DEFAULT_DRAFT_EFFORT}
    assert reasoning_for("korgan_contract_draft", "gpt-5.1") == {"effort": DEFAULT_DRAFT_EFFORT}


def test_service_calls_keep_effort_none():
    """Экономия сохраняется там, где она ничего не портит."""
    for schema in (
        "korgan_verified_legal_research",
        "korgan_court_ready_validation",
        "korgan_claim_v2_facts",
        "korgan_document_extract",
    ):
        assert reasoning_for(schema, "gpt-5.1") == {"effort": "none"}, schema


def test_reasoning_is_gpt51_only():
    """Параметр reasoning не отправляется моделям, которые его не принимают."""
    assert reasoning_for("korgan_court_ready_claim", "gpt-4.1") is None
    assert reasoning_for("korgan_verified_legal_research", "gpt-4o") is None


def test_repair_schemas_are_drafting():
    """Правка иска — то же составление и требует того же рассуждения."""
    for schema in ("korgan_repaired_claim", "korgan_fast_professional_repair", "korgan_contract_repair"):
        assert is_drafting(schema), schema


def test_claim_output_limit_leaves_room_for_a_full_pleading():
    """Прежние 4300 токенов обрывали иск на середине."""
    assert output_limit_for("korgan_court_ready_claim", 4300) >= 12000
    assert output_limit_for("korgan_contract_draft", 5200) >= 14000


def test_output_limit_never_lowers_an_existing_larger_budget():
    """Вызывающий мог уже поднять лимит — понижать его нельзя."""
    assert output_limit_for("korgan_contract_draft", 24000) == 24000


def test_service_schema_limit_is_untouched():
    """Служебные схемы сохраняют свои прежние компактные лимиты."""
    assert output_limit_for("korgan_verified_legal_research", 2300) == 2300
    assert output_limit_for("korgan_unknown_schema", None) is None


def test_effort_is_configurable_without_a_deploy(monkeypatch):
    monkeypatch.setenv("KORGAN_DRAFT_REASONING_EFFORT", "high")
    assert reasoning_for("korgan_court_ready_claim", "gpt-5.1") == {"effort": "high"}


def test_unknown_effort_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("KORGAN_DRAFT_REASONING_EFFORT", "максимальный")
    assert reasoning_for("korgan_court_ready_claim", "gpt-5.1") == {"effort": DEFAULT_DRAFT_EFFORT}


def test_output_scale_is_bounded(monkeypatch):
    """Ниже половины лимит снова режет документ, выше двух — жжёт бюджет."""
    monkeypatch.setenv("KORGAN_DRAFT_OUTPUT_SCALE", "99")
    assert output_limit_for("korgan_court_ready_claim", 4300) == 24000
    monkeypatch.setenv("KORGAN_DRAFT_OUTPUT_SCALE", "0.01")
    assert output_limit_for("korgan_court_ready_claim", 4300) == 6000


def test_apply_fills_call_kwargs():
    kwargs = apply({}, schema_name="korgan_court_ready_claim", model="gpt-5.1")
    assert kwargs["reasoning"] == {"effort": DEFAULT_DRAFT_EFFORT}
    assert kwargs["max_output_tokens"] >= 12000


def test_every_drafting_schema_has_a_budget():
    """Схема составления без расширенного лимита — обрезанный документ."""
    from korgan.pro_document_quality import DRAFT_OUTPUT_LIMITS

    assert set(DRAFTING_SCHEMAS) == set(DRAFT_OUTPUT_LIMITS)


# ---------------------------------------------------------------------------
# Профессиональные разделы иска
# ---------------------------------------------------------------------------


def test_claim_schema_carries_professional_sections():
    for name in PRO_CLAIM_FIELDS:
        assert name in _CLAIM_SCHEMA["properties"], name


def test_claim_schema_stays_strict():
    """Responses API в strict-режиме требует required == properties."""
    assert set(_CLAIM_SCHEMA["required"]) == set(_CLAIM_SCHEMA["properties"])
    assert _CLAIM_SCHEMA["additionalProperties"] is False


def _draft(**overrides) -> ClaimDraft:
    base = dict(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности по договору займа",
        court="Специализированный межрайонный экономический суд города Астаны",
        claimant=["Ахметов Данияр Серикович, ИИН 870514300123, г. Алматы, мкр. Коктем-2, д. 12, кв. 45"],
        defendant=["ТОО «Астана Строй Групп», БИН 180340000456, г. Астана, ул. Кунаева, д. 8"],
        price_of_claim="5 302 900 тенге",
        facts=["15 января 2026 года между сторонами заключён договор займа № 03/2026 (приложение № 4)."],
        legal_basis=["Статьи 715, 722 ГК РК (Особенная часть): заёмщик обязан возвратить сумму займа в срок (обстоятельство 1)."],
        requests=["Взыскать с ответчика в пользу истца 4 700 000 тенге основного долга."],
        attachments=["Договор займа № 03/2026 от 15.01.2026 — копия, 3 л."],
        verification_notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
    )
    base.update(overrides)
    return ClaimDraft(**base)


def test_claim_draft_defaults_keep_old_payloads_valid():
    """Сохранённые черновики без новых полей должны продолжать работать."""
    draft = _draft()
    assert draft.calculation == []
    assert draft.jurisdiction_reason == ""
    assert draft.motions == []


def test_pro_payload_round_trips_through_a_repair_round():
    """Раунд правки не должен терять расчёт, подсудность и ходатайства."""
    draft = _draft(
        calculation=["Основной долг: 5 000 000 − 300 000 = 4 700 000 тенге."],
        jurisdiction_reason="Иск предъявляется по месту нахождения ответчика.",
        motions=["Наложить арест на счета ответчика в пределах цены иска."],
    )
    payload = pro_payload(draft)
    assert set(payload) == set(PRO_CLAIM_FIELDS)

    restored = ClaimDraft(
        status=draft.status,
        title=draft.title,
        court=draft.court,
        claimant=draft.claimant,
        defendant=draft.defendant,
        price_of_claim=draft.price_of_claim,
        facts=draft.facts,
        legal_basis=draft.legal_basis,
        requests=draft.requests,
        attachments=draft.attachments,
        verification_notes=draft.verification_notes,
        source_urls=draft.source_urls,
        **payload,
    )
    assert restored.calculation == draft.calculation
    assert restored.jurisdiction_reason == draft.jurisdiction_reason
    assert restored.motions == draft.motions


def test_pro_text_is_scanned_for_placeholder_markers():
    draft = _draft(calculation=["[ТРЕБУЕТ УТОЧНЕНИЯ: период начисления]"])
    assert any("ТРЕБУЕТ УТОЧНЕНИЯ" in line for line in pro_text(draft))


def _docx_lines(draft: ClaimDraft) -> list[str]:
    document = Document(io.BytesIO(build_claim_docx(draft)))
    return [p.text.strip() for p in document.paragraphs if p.text.strip()]


def test_word_export_renders_professional_sections_in_order():
    draft = _draft(
        calculation=["Основной долг: 5 000 000 − 300 000 = 4 700 000 тенге."],
        jurisdiction_reason="Иск предъявляется по месту нахождения ответчика — юридического лица.",
        pretrial_compliance="Претензия от 20.05.2026 вручена ответчику 26.05.2026, ответ не поступил.",
        reconciliation_measures="03.06.2026 истец предложил рассрочку; ответ не получен.",
        limitation_period="Течение срока прервалось 05.05.2026 частичной оплатой.",
        anticipated_defenses=["Ответчик может утверждать, что заём не передан — однако передача подтверждена платёжным поручением № 117."],
        motions=["Наложить арест на счета ответчика в пределах цены иска."],
    )
    lines = _docx_lines(draft)
    body = "\n".join(lines)

    for fragment in (
        "Расчёт взыскиваемых сумм",
        "4 700 000 тенге",
        "по месту нахождения ответчика",
        "Претензия от 20.05.2026",
        "рассрочку",
        "прервалось 05.05.2026",
        "заём не передан",
        "Ходатайства",
        "арест на счета ответчика",
    ):
        assert fragment in body, fragment

    def at(fragment: str) -> int:
        return next(i for i, line in enumerate(lines) if fragment in line)

    # Расчёт идёт после фактов и до правового обоснования; ходатайства — после
    # просительной части и до приложений. Порядок для суда не косметика.
    assert at("договор займа № 03/2026") < at("Расчёт взыскиваемых сумм")
    assert at("Расчёт взыскиваемых сумм") < at("Правовое обоснование")
    assert at("Правовое обоснование") < at("ПРОШУ СУД")
    assert at("ПРОШУ СУД") < at("Ходатайства")
    assert at("Ходатайства") < at("Приложения")


def test_word_export_skips_empty_professional_sections():
    """Пустой раздел хуже отсутствующего: заголовка без содержания быть не должно."""
    lines = _docx_lines(_draft())
    body = "\n".join(lines)
    assert "Расчёт взыскиваемых сумм" not in body
    assert "Ходатайства" not in body
    assert "Возможные возражения" not in body
    # Документ при этом остаётся полноценным иском.
    assert "ПРОШУ СУД" in body
    assert "Приложения" in body


@pytest.mark.parametrize("field_name", PRO_CLAIM_FIELDS)
def test_every_professional_field_exists_on_the_draft(field_name):
    assert hasattr(_draft(), field_name), field_name
