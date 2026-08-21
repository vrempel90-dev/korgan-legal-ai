from __future__ import annotations

import io
from pathlib import Path

from docx import Document

from korgan.legal_types import VerificationStatus
from korgan.pretrial import PretrialDraft, build_pretrial_docx
from korgan.pretrial_response import PretrialResponseDraft, build_pretrial_response_docx


def _paragraphs(payload: bytes) -> list[str]:
    doc = Document(io.BytesIO(payload))
    return [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]


def test_pretrial_renderer_is_continuous_business_letter_not_ai_memo() -> None:
    draft = PretrialDraft(
        status=VerificationStatus.VERIFIED,
        title="Досудебная претензия",
        sender=["ТОО «Заказчик»", "г. Астана"],
        recipient=["ТОО «Подрядчик»", "г. Алматы"],
        facts=[
            "Между сторонами заключен договор подряда № 15 от 01.06.2026 года.",
            "В нарушение условий договора работы в согласованный срок не завершены.",
        ],
        legal_basis=["В соответствии с подтвержденной нормой обязательство подлежит надлежащему исполнению."],
        demands=["В этой связи просим погасить подтвержденную задолженность в размере 300 000 тенге."],
        deadline="5 банковских дней",
        consequences=["В случае неисполнения требований оставляем за собой право обратиться в суд в установленном порядке."],
        attachments=["Копия договора"],
    )

    lines = _paragraphs(build_pretrial_docx(draft))

    assert "Досудебная претензия" in lines
    assert "Между сторонами заключен договор подряда № 15 от 01.06.2026 года." in lines
    assert "В соответствии с подтвержденной нормой обязательство подлежит надлежащему исполнению." in lines
    assert "В этой связи просим погасить подтвержденную задолженность в размере 300 000 тенге." in lines
    assert "Просим исполнить указанные требования в течение 5 банковских дней." in lines
    assert "Правовое обоснование" not in lines
    assert "ТРЕБУЮ:" not in lines
    assert "Требования" not in lines
    assert "Последствия" not in lines


def test_pretrial_response_renderer_follows_reference_letter_flow() -> None:
    draft = PretrialResponseDraft(
        status=VerificationStatus.VERIFIED,
        title="Ответ на досудебную претензию",
        sender=["ТОО «Получатель претензии»", "г. Астана"],
        recipient=["ТОО «Отправитель претензии»", "г. Астана"],
        reference="исх. № 42 от 15.07.2026",
        claim_summary=["В претензии заявлено требование об оплате 950 000 тенге."],
        position=["Не признаём требование в заявленном размере по следующим основаниям."],
        objections=["Товар на сумму 650 000 тенге по представленным материалам не передавался."],
        legal_basis=["Условия договора подлежат применению в подтвержденной материалами части."],
        response_terms=["Предлагаем провести сверку взаиморасчетов по имеющимся первичным документам."],
        attachments=["Копия подписанной накладной"],
    )

    lines = _paragraphs(build_pretrial_response_docx(draft))

    assert "На исх. № 42 от 15.07.2026" in lines
    assert "Не признаём требование в заявленном размере по следующим основаниям." in lines
    assert "Товар на сумму 650 000 тенге по представленным материалам не передавался." in lines
    assert "Предлагаем провести сверку взаиморасчетов по имеющимся первичным документам." in lines
    assert "Содержание претензии" not in lines
    assert "Позиция" not in lines
    assert "Возражения и пояснения" not in lines
    assert "Правовое обоснование" not in lines
    assert "Ответ на требования" not in lines


def test_prompts_use_reference_only_for_form_not_case_facts() -> None:
    pretrial_source = Path("korgan/pretrial.py").read_text(encoding="utf-8")
    response_source = Path("korgan/pretrial_response.py").read_text(encoding="utf-8")

    assert "ЭТАЛОН ПОДАЧИ И СТРУКТУРЫ" in pretrial_source
    assert "Не копируй никакие факты, суммы, даты" in pretrial_source
    assert "искусственными разделами «Фактические обстоятельства»" in pretrial_source

    assert "ЭТАЛОН ПОДАЧИ И СТРУКТУРЫ" in response_source
    assert "Не копируй никакие факты, суммы, даты" in response_source
    assert "Пиши от имени адресата напрямую" in response_source
    assert "искусственными разделами «Содержание претензии»" in response_source
