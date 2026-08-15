from __future__ import annotations

import io
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from korgan.legal_types import ClaimDraft, VerificationStatus


DRAFT_NOTICE = (
    "ПРОЕКТ — сформирован KORGAN Legal AI на основании данных пользователя. "
    "Перед подачей необходимо проверить факты, реквизиты, доказательства, расчёты, подсудность, "
    "госпошлину и все пункты NEEDS_VERIFICATION. Формирование проекта не гарантирует принятие документа или исход дела."
)


def build_claim_docx(draft: ClaimDraft) -> bytes:
    doc = Document()
    styles = doc.styles
    styles["Normal"].font.name = "Times New Roman"
    styles["Normal"].font.size = Pt(12)

    # Keep the court-facing body clean, but preserve an unobtrusive service notice in the footer.
    for section in doc.sections:
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run(DRAFT_NOTICE)
        run.font.name = "Times New Roman"
        run.font.size = Pt(8)

    right = doc.add_paragraph()
    right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    right.add_run(f"В суд: {draft.court or '[ТРЕБУЕТ УТОЧНЕНИЯ: суд]'}\n").bold = True
    right.add_run("Истец:\n")
    for item in draft.claimant or ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные истца]"]:
        right.add_run(f"{item}\n")
    right.add_run("Ответчик:\n")
    for item in draft.defendant or ["[ТРЕБУЕТ УТОЧНЕНИЯ: данные ответчика]"]:
        right.add_run(f"{item}\n")
    right.add_run(f"Цена иска: {draft.price_of_claim or '[ТРЕБУЕТ УТОЧНЕНИЯ]'}")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(draft.title or "ИСКОВОЕ ЗАЯВЛЕНИЕ").bold = True

    doc.add_heading("Обстоятельства дела", level=2)
    for fact in draft.facts:
        doc.add_paragraph(fact)

    doc.add_heading("Правовое обоснование", level=2)
    for basis in draft.legal_basis:
        doc.add_paragraph(basis)

    doc.add_paragraph("На основании изложенного ПРОШУ СУД:").runs[0].bold = True
    for request in draft.requests:
        doc.add_paragraph(request, style="List Number")

    doc.add_heading("Приложения", level=2)
    for attachment in draft.attachments:
        doc.add_paragraph(attachment, style="List Number")

    if draft.verification_notes or draft.status == VerificationStatus.NEEDS_VERIFICATION:
        doc.add_heading("Требует проверки перед подачей", level=2)
        notes = draft.verification_notes or ["Не все обязательные правовые/процессуальные данные удалось подтвердить."]
        for note in notes:
            doc.add_paragraph(note, style="List Bullet")

    if draft.source_urls:
        doc.add_heading("Официальные источники, использованные при подготовке", level=2)
        for url in draft.source_urls:
            doc.add_paragraph(url)

    doc.add_paragraph()
    doc.add_paragraph(f"Дата подготовки проекта: {date.today().isoformat()}")
    doc.add_paragraph("Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
