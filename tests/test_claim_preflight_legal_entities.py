from __future__ import annotations

from korgan.claim_preflight import inspect_claim_context
from korgan.field_intake import normalize_answer


def test_person_claimant_and_company_defendant_from_telegram_case() -> None:
    context = """
Истец: Ахметова Гульнара Сериковна, ИИН 880512400156,
дата рождения: 12.05.1988,
адрес: г. Алматы, Медеуский район, ул. Абая, 150, кв. 34.

Ответчик: ТОО «КурылысСтройИнвест», БИН 150640012233,
адрес: г. Алматы, Алатауский район, ул. Момышулы, 5.
"""
    missing = inspect_claim_context(context).missing
    assert "ФИО ответчика полностью" not in missing
    assert "полное наименование ответчика" not in missing
    assert "БИН ответчика" not in missing
    assert "место нахождения ответчика" not in missing


def test_company_claimant_uses_bin_not_iin() -> None:
    context = """
Истец: ТОО «Астана Логистик», БИН 123456789012,
место нахождения: г. Астана, ул. Сыганак, 10,
банковские реквизиты: IBAN KZ123456789012345678.
Ответчик: Петров Пётр Петрович,
адрес: г. Астана, ул. Кенесары, 40, кв. 12.
"""
    missing = inspect_claim_context(context).missing
    assert "полное наименование истца" not in missing
    assert "БИН истца" not in missing
    assert "место нахождения истца" not in missing


def test_company_defendant_fields_can_be_collected_without_loop() -> None:
    intake = normalize_answer(
        ["полное наименование ответчика", "БИН ответчика", "место нахождения ответчика"],
        "ТОО «КурылысСтройИнвест»\n150640012233\nг. Алматы, Алатауский район, ул. Момышулы, 5",
    )
    assert intake.progressed
    assert len(intake.recorded) == 3
    assert not intake.errors
