"""Контактные реквизиты сторон не читаются как повреждённый текст.

Детектор склеек ищет точку между словами без пробела: в юридическом русском
такого не бывает, и это верный признак склеенного экспорта. Но адрес
электронной почты и доменное имя устроены ровно так — «test.claimant@example.com»,
«mebel-standart.kz», — а статья 148 ГПК РК прямо требует указывать в иске
сведения о сторонах, включая контактные данные.

Цена ложного срабатывания — не замечание: готовый документ с e-mail стороны
не проходил финальную проверку целостности, и оплативший клиент получал отказ
вместо иска.
"""

from __future__ import annotations

from korgan.text_integrity import integrity_findings

CLAIM_HEADER = (
    "Истец:\n"
    "Сериков Арман Нурланович\n"
    "адрес: город Алматы, Бостандыкский район, улица Тестовая, дом 25, квартира 18\n"
    "телефон: +7 700 000 00 01\n"
    "e-mail: test.claimant@example.com\n"
    "Ответчик:\n"
    "Товарищество с ограниченной ответственностью «Мебель Стандарт»\n"
    "e-mail: test.company@example.com\n"
    "сайт: mebel-standart.kz\n"
)


def test_contact_details_are_not_reported_as_glued_text() -> None:
    assert integrity_findings(CLAIM_HEADER) == []


def test_official_source_url_is_not_reported_as_glued_text() -> None:
    text = "Правовое основание: статья 272 ГК РК; источник: https://adilet.zan.kz/rus/docs/K940001000_"

    assert integrity_findings(text) == []


def test_real_glued_export_is_still_reported() -> None:
    text = "Работы не выполнены.Ответчик денежные средства не возвратил."

    findings = integrity_findings(text)

    assert [finding.code for finding in findings] == ["sentence_glued"]
