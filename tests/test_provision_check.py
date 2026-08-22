"""Tests for the paraphrase gate.

The provision texts below are SYNTHETIC fixtures written to exercise the
mechanics of the check. They are not reproductions of official Kazakhstan legal
texts and must not be read as such — the real text always comes from the
official source at runtime.
"""

from __future__ import annotations

from korgan.provision_check import (
    is_paraphrase_safe,
    paraphrase_defects,
    quote_is_usable,
    verified_claim_line,
)

# Shape of the provision that produced the shipped defect: the duty to cite
# statutes is attached to a filing signed by a representative, while the general
# requirement concerns evidence.
_REPRESENTATIVE_SCOPED = (
    "Отзыв должен содержать возражения относительно предъявленных требований со ссылкой на "
    "доказательства, подтверждающие возражения. В отзыве, подписанном представителем, указываются "
    "также ссылки на нормативные правовые акты."
)


def test_paraphrase_without_provision_text_can_never_be_verified() -> None:
    defects = paraphrase_defects("Отзыв должен содержать возражения.", "")
    assert defects
    assert "NEEDS_VERIFICATION" in defects[0]


def test_too_short_quote_is_not_a_usable_basis_for_a_paraphrase() -> None:
    assert not quote_is_usable("ст. 166 ГПК РК")
    assert quote_is_usable(_REPRESENTATIVE_SCOPED)
    assert paraphrase_defects("Отзыв содержит возражения.", "ст. 166 ГПК РК")


def test_narrow_condition_generalised_to_a_universal_rule_is_caught() -> None:
    """The exact failure: a representative-only duty stated as a general one."""
    shipped = (
        "Отзыв должен содержать возражения относительно предъявленных требований со ссылками на "
        "законы и иные нормативные правовые акты."
    )
    defects = paraphrase_defects(shipped, _REPRESENTATIVE_SCOPED)
    assert defects
    assert any("представител" in defect for defect in defects)
    assert not is_paraphrase_safe(shipped, _REPRESENTATIVE_SCOPED)


def test_paraphrase_keeping_the_narrow_condition_passes() -> None:
    accurate = (
        "Отзыв должен содержать возражения относительно предъявленных требований со ссылкой на "
        "доказательства; в отзыве, подписанном представителем, указываются также ссылки на "
        "нормативные правовые акты."
    )
    assert is_paraphrase_safe(accurate, _REPRESENTATIVE_SCOPED)


def test_requirement_absent_from_the_provision_is_caught() -> None:
    provision = (
        "Стороны обязаны исполнять обязательства надлежащим образом в соответствии с условиями "
        "обязательства и требованиями законодательства."
    )
    invented = (
        "Стороны обязаны исполнять обязательства надлежащим образом и уплатить неустойку за каждый "
        "день просрочки."
    )
    defects = paraphrase_defects(invented, provision)
    assert any("неустойка" in defect for defect in defects)


def test_right_restated_as_a_duty_is_caught() -> None:
    provision = (
        "Заказчик вправе во всякое время проверять ход и качество оказываемых услуг, не вмешиваясь в "
        "оперативную деятельность исполнителя."
    )
    overstated = (
        "Заказчик обязан во всякое время проверять ход и качество оказываемых услуг исполнителем по "
        "договору."
    )
    assert not is_paraphrase_safe(overstated, provision)


def test_accurate_paraphrase_of_an_ordinary_provision_passes() -> None:
    provision = (
        "Договор возмездного оказания услуг заключается в письменной форме, если иное не установлено "
        "законодательными актами Республики Казахстан."
    )
    faithful = (
        "Договор возмездного оказания услуг заключается в письменной форме, если законодательными "
        "актами не установлено иное."
    )
    assert is_paraphrase_safe(faithful, provision)


def test_accepted_point_carries_the_provision_text_to_the_drafter() -> None:
    line = verified_claim_line(
        "Отзыв содержит возражения со ссылкой на доказательства.",
        "часть 4 статьи 166 ГПК РК",
        _REPRESENTATIVE_SCOPED,
        "https://adilet.zan.kz/rus/docs/K1500000377",
    )
    assert "текст нормы:" in line
    assert "подписанном представителем" in line
    assert "https://adilet.zan.kz/rus/docs/K1500000377" in line
