from korgan.document_sanitization import (
    sanitize_client_legal_line,
    sanitize_document_draft,
    strip_party_role_labels,
)
from korgan.pretrial import PretrialDraft
from korgan.legal_types import VerificationStatus


def test_renderer_owned_party_labels_are_removed_repeatedly():
    assert strip_party_role_labels("Кому: Кому: ТОО «Вектор Строй»") == "ТОО «Вектор Строй»"
    assert strip_party_role_labels("От: Отправитель: ТОО «Арман Снабжение»") == "ТОО «Арман Снабжение»"
    assert strip_party_role_labels("Истец: ТОО «Арман Снабжение»") == "ТОО «Арман Снабжение»"
    assert strip_party_role_labels("Алушы: Жауапкер: «Вектор» ЖШС") == "«Вектор» ЖШС"


def test_adilet_editorial_metadata_never_reaches_client_legal_basis():
    assert sanitize_client_legal_line("Сноска. В статью 293 внесены изменения Законом РК...") == ""
    assert sanitize_client_legal_line("Статья 293 ГК РК допускает неустойку (по открытому фрагменту).") == "Статья 293 ГК РК допускает неустойку."
    assert sanitize_client_legal_line("Обязательство должно исполняться надлежащим образом. Сноска. Статья изменена...") == "Обязательство должно исполняться надлежащим образом."


def test_pretrial_party_labels_and_technical_law_are_cleaned_before_word_release():
    draft = PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Досудебная претензия",
        sender=["От: ТОО «Арман Снабжение»", "БИН: 000000000001"],
        recipient=["Кому: ТОО «Вектор Строй»", "БИН: 000000000002"],
        facts=["Товар поставлен."],
        legal_basis=[
            "Обязательство должно исполняться надлежащим образом. Сноска. История изменений.",
            "Сноска. В статью внесены изменения.",
        ],
        demands=["Оплатить долг."],
        deadline="10 календарных дней",
        consequences=[],
        attachments=[],
    )

    sanitize_document_draft(draft)

    assert draft.sender[0] == "ТОО «Арман Снабжение»"
    assert draft.recipient[0] == "ТОО «Вектор Строй»"
    assert draft.legal_basis == ["Обязательство должно исполняться надлежащим образом."]
