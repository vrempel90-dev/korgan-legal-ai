"""Регрессия фазы 4: правила STYLE_GUIDE.md как детерминированные проверки.

Каждое правило нарушается намеренно и обязано быть заблокировано. Отдельно
проверяется, что соблюдающий правило документ проходит: правило, которое
блокирует и корректный документ тоже, не отличает соблюдение от нарушения.

Отдельная проверка сверяет, что текст STYLE_GUIDE.md и его машинное
представление не разошлись. Расхождение здесь тише всех остальных ошибок:
документ описывает правило, которого нет в коде, и читатель считает его
выполняемым.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from korgan import style_guide
from korgan.document_linter import LintStatus, lint_claim_document
from tests.test_phase3_document_linter import _clean_draft, _rules, _trace

STYLE_GUIDE_PATH = Path(__file__).resolve().parent.parent / "STYLE_GUIDE.md"


def _style_rules(result) -> set[str]:
    return {rule for rule in _rules(result) if rule.startswith("style_guide:")}


# --------------------------------------------------------------------------
# SG-06. Документ и код не расходятся
# --------------------------------------------------------------------------


def test_style_guide_file_exists() -> None:
    assert STYLE_GUIDE_PATH.is_file()


def test_documented_version_matches_the_code() -> None:
    text = STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    match = re.search(r"\*\*Версия:\s*(?P<version>\d+\.\d+\.\d+)\*\*", text)

    assert match is not None, "в STYLE_GUIDE.md не указана версия"
    assert match.group("version") == style_guide.STYLE_GUIDE_VERSION


def test_every_documented_rule_has_an_implementation() -> None:
    text = STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    documented = set(re.findall(r"###\s+(SG-\d+)\.", text))

    assert documented == set(style_guide.RULE_IDS)


def test_every_rule_carries_a_title_and_a_fix() -> None:
    for rule in style_guide.RULES:
        assert rule.title.strip()
        assert len(rule.fix.strip()) > 20


# --------------------------------------------------------------------------
# SG-01. Статья 8 ГПК РК
# --------------------------------------------------------------------------


def test_unverified_article_8_reference_is_blocked() -> None:
    draft = _clean_draft(
        facts=[
            "В соответствии со статьёй 8 ГПК РК каждый вправе обратиться в суд "
            "за защитой нарушенного права.",
        ]
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "style_guide:SG-01" in _style_rules(result)


def test_verified_article_8_reference_passes() -> None:
    draft = _clean_draft(
        facts=[
            "В соответствии со статьёй 8 ГПК РК каждый вправе обратиться в суд "
            "за защитой нарушенного права.",
        ],
        citation_authority=_trace(("ГК РК", "439"), ("ГПК РК", "8")),
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


def test_a_claim_without_article_8_is_not_required_to_cite_it() -> None:
    """Правило про подтверждение ссылки, а не про обязанность её ставить."""
    assert lint_claim_document(_clean_draft()).status is LintStatus.PASS


# --------------------------------------------------------------------------
# SG-02. Судебные расходы отдельным пунктом
# --------------------------------------------------------------------------


def _with_duty(**overrides):
    base = dict(
        calculation_result={
            "state_duty": {"status": "calculated", "value": 30_000, "missing": []},
        }
    )
    base.update(overrides)
    return _clean_draft(**base)


def test_missing_court_costs_request_is_blocked() -> None:
    draft = _with_duty(
        requests=["Взыскать с ответчика в пользу истца основной долг в размере 1 000 000 тенге."]
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "style_guide:SG-02" in _style_rules(result)


def test_court_costs_folded_into_a_money_request_is_blocked() -> None:
    """Расходы внутри денежного пункта — не самостоятельное требование."""
    draft = _with_duty(
        requests=[
            "Взыскать с ответчика основной долг в размере 1 000 000 тенге, "
            "а также расходы по уплате государственной пошлины.",
        ]
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "style_guide:SG-02" in _style_rules(result)


def test_separate_court_costs_request_passes() -> None:
    draft = _with_duty(
        requests=[
            "Взыскать с ответчика в пользу истца основной долг в размере 1 000 000 тенге.",
            "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины.",
        ]
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


def test_rule_does_not_apply_when_the_duty_is_not_calculated() -> None:
    draft = _clean_draft(
        requests=["Взыскать с ответчика в пользу истца основной долг в размере 1 000 000 тенге."]
    )

    assert "style_guide:SG-02" not in _style_rules(lint_claim_document(draft))


# --------------------------------------------------------------------------
# SG-03. Родовая и территориальная подсудность
# --------------------------------------------------------------------------


def test_venue_rules_mixed_in_one_sentence_are_blocked() -> None:
    draft = _clean_draft(
        jurisdiction_reason=(
            "Дело подсудно данному суду в соответствии со статьями 27 и 29 ГПК РК."
        ),
        citation_authority=_trace(("ГК РК", "439"), ("ГПК РК", "27"), ("ГПК РК", "29")),
    )

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "style_guide:SG-03" in _style_rules(result)


def test_venue_rules_split_into_separate_sentences_pass() -> None:
    draft = _clean_draft(
        jurisdiction_reason=(
            "Родовая подсудность определена статьёй 27 ГПК РК: спор между юридическими "
            "лицами рассматривает специализированный межрайонный экономический суд. "
            "Территориальная подсудность определена статьёй 29 ГПК РК — по месту "
            "нахождения ответчика."
        ),
        citation_authority=_trace(("ГК РК", "439"), ("ГПК РК", "27"), ("ГПК РК", "29")),
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


def test_one_venue_rule_alone_is_not_a_violation() -> None:
    draft = _clean_draft(
        jurisdiction_reason="Иск предъявлен по месту нахождения ответчика — статья 29 ГПК РК.",
        citation_authority=_trace(("ГК РК", "439"), ("ГПК РК", "29")),
    )

    assert "style_guide:SG-03" not in _style_rules(lint_claim_document(draft))


def test_both_rules_named_with_their_roles_in_one_sentence_pass() -> None:
    draft = _clean_draft(
        jurisdiction_reason=(
            "Родовая подсудность следует из статьи 27 ГПК РК, территориальная "
            "подсудность по месту нахождения ответчика — из статьи 29 ГПК РК."
        ),
        citation_authority=_trace(("ГК РК", "439"), ("ГПК РК", "27"), ("ГПК РК", "29")),
    )

    assert "style_guide:SG-03" not in _style_rules(lint_claim_document(draft))


# --------------------------------------------------------------------------
# SG-04. Реквизиты сторон
# --------------------------------------------------------------------------


def test_invented_bin_that_fails_the_checksum_is_blocked() -> None:
    """Номер, не проходящий контрольную сумму, суд отклоняет первым действием."""
    draft = _clean_draft(claimant=["ТОО «Альфа», БИН 190440012345, г. Алматы, ул. Абая, 10"])

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    assert "style_guide:SG-04" in _style_rules(result)


def test_valid_checksum_passes() -> None:
    assert lint_claim_document(_clean_draft()).status is LintStatus.PASS


def test_requisite_absent_from_the_case_materials_is_blocked() -> None:
    """Номер, которого нет в материалах, в документ попал только от модели."""
    context = "Истец: ТОО «Альфа», БИН 190440012341. Ответчик: ТОО «Бета», БИН 200540067892."
    draft = _clean_draft(
        claimant=["ТОО «Альфа», БИН 030340009019, г. Алматы, ул. Абая, 10"],
    )

    result = lint_claim_document(draft, case_context=context)

    assert result.status is LintStatus.BLOCKED
    findings = [item for item in result.findings if item.rule == "style_guide:SG-04"]
    assert any("отсутствует в материалах дела" in item.message for item in findings)


def test_requisite_present_in_the_case_materials_passes() -> None:
    context = "Истец: ТОО «Альфа», БИН 190440012341. Ответчик: ТОО «Бета», БИН 200540067892."

    assert lint_claim_document(_clean_draft(), case_context=context).status is LintStatus.PASS


def test_party_without_an_address_is_blocked() -> None:
    draft = _clean_draft(defendant=["ТОО «Бета», БИН 200540067892"])

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    findings = [item for item in result.findings if item.rule == "style_guide:SG-04"]
    assert any("нет адреса" in item.message for item in findings)


def test_legal_entity_without_a_bin_is_blocked() -> None:
    draft = _clean_draft(defendant=["ТОО «Бета», г. Алматы, ул. Толе би, 55"])

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    findings = [item for item in result.findings if item.rule == "style_guide:SG-04"]
    assert any("без БИН" in item.message for item in findings)


def test_individual_party_needs_an_address_but_not_a_bin() -> None:
    draft = _clean_draft(
        defendant=["Ахметов Данияр Серикович, ИИН 870514300123, г. Алматы, мкр. Коктем-2, д. 12"],
    )

    assert lint_claim_document(draft).status is LintStatus.PASS


@pytest.mark.parametrize(
    ("number", "valid"),
    [
        ("870514300123", True),
        ("190440012341", True),
        ("200540067892", True),
        ("190440012345", False),
        ("000000000000", True),   # вырожденный, но арифметически корректный
        ("12345", False),
        ("abcdefghijkl", False),
    ],
)
def test_checksum_algorithm(number, valid) -> None:
    assert style_guide.id_number_is_valid(number) is valid


# --------------------------------------------------------------------------
# SG-05. Обязательные разделы по структуре
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "label"),
    [
        ("facts", "обстоятельства дела"),
        ("legal_basis", "правовое обоснование"),
        ("requests", "просительная часть"),
        ("attachments", "приложения"),
    ],
)
def test_empty_mandatory_section_is_blocked(section, label) -> None:
    draft = _clean_draft(**{section: []})

    result = lint_claim_document(draft)

    assert result.status is LintStatus.BLOCKED
    findings = [item for item in result.findings if item.rule == "style_guide:SG-05"]
    assert any(label in item.message for item in findings)


def test_calculation_section_is_required_only_for_a_monetary_claim() -> None:
    without_money = _clean_draft(calculation=[])
    assert "style_guide:SG-05" not in _style_rules(lint_claim_document(without_money))

    monetary = _clean_draft(
        calculation=[],
        calculation_result={"claim_price": {"status": "calculated", "value": 1_000_000, "missing": []}},
    )
    result = lint_claim_document(monetary)
    findings = [item for item in result.findings if item.rule == "style_guide:SG-05"]
    assert any("расчёт" in item.message for item in findings)


def test_sections_are_detected_by_structure_not_by_heading_text() -> None:
    """Раздел не исчезает от того, что заголовок написан на казахском."""
    draft = _clean_draft(
        facts=["Тауар 20.02.2026 жеткізілді, төлем жүргізілмеді."],
        title="ТАЛАП АРЫЗ",
    )

    assert "style_guide:SG-05" not in _style_rules(lint_claim_document(draft))
