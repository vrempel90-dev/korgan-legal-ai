from docx import Document

from korgan.docx_blocks import AutoNumberedList, Heading, render_blocks


def test_attachments_restart_from_one_after_prior_numbered_list() -> None:
    doc = Document()
    render_blocks(
        doc,
        [
            Heading("ПРОШУ СУД:"),
            AutoNumberedList(["Требование один", "Требование два", "Требование три", "Требование четыре"]),
            Heading("Приложения:"),
            AutoNumberedList(["Первое приложение", "Второе приложение"], restart=True),
        ],
    )

    texts = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
    attachments_index = texts.index("Приложения:")
    assert texts[attachments_index + 1] == "1. Первое приложение"
    assert texts[attachments_index + 2] == "2. Второе приложение"
    assert not texts[attachments_index + 1].startswith("5.")
