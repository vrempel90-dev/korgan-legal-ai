from korgan.text_integrity import integrity_findings, is_intact


def test_internal_serialization_field_is_blocked() -> None:
    findings = integrity_findings("Имеется подтверждение. claim_amount: 360 000 тенге")
    assert any(item.code == "internal_serialization_field" for item in findings)


def test_glued_currency_index_is_blocked() -> None:
    findings = integrity_findings("Неустойка составляет 360 000 тенге2")
    assert any(item.code == "glued_currency_index" for item in findings)


def test_alternative_placeholder_is_blocked() -> None:
    findings = integrity_findings("[НУЖНО ДОПОЛНИТЬ: подписант и его полномочия]")
    assert any(item.code == "unresolved_alt_placeholder" for item in findings)


def test_normal_legal_text_remains_intact() -> None:
    assert is_intact("Взыскать 360 000 тенге. ТОО «Ответчик», БИН 210540009999.")
