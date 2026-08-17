from __future__ import annotations

from aiogram.types import BufferedInputFile

from korgan.consultation_cta import _document_label


def test_document_type_labels_are_specific_and_do_not_overlap_claim_words() -> None:
    assert _document_label(BufferedInputFile(b"x", filename="KORGAN_iskovoe_zayavlenie.docx"), "ru") == "Исковое заявление"
    assert _document_label(BufferedInputFile(b"x", filename="KORGAN_otzyv_na_isk.docx"), "ru") == "Отзыв на иск"
    assert _document_label(BufferedInputFile(b"x", filename="KORGAN_dosudebnaya_pretenziya.docx"), "ru") == "Досудебная претензия"
    assert _document_label(BufferedInputFile(b"x", filename="KORGAN_dogovor.docx"), "ru") == "Договор"
