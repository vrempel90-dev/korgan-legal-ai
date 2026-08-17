from docx import Document
from docx.oxml.ns import qn

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

    list_paragraphs = [p for p in doc.paragraphs if p.style.name == "List Number"]
    annexes = list_paragraphs[-2:]
    ids = []
    for paragraph in annexes:
        found = paragraph._p.find(f'{qn("w:pPr")}/{qn("w:numPr")}/{qn("w:numId")}')
        assert found is not None
        ids.append(found.get(qn("w:val")))
    assert len(set(ids)) == 1

    annex_num_id = ids[0]
    numbering = doc.part.numbering_part.element
    matching = [
        num for num in numbering.findall(qn("w:num"))
        if num.get(qn("w:numId")) == annex_num_id
        and num.find(f'{qn("w:lvlOverride")}/{qn("w:startOverride")}') is not None
    ]
    assert len(matching) == 1
    start = matching[0].find(f'{qn("w:lvlOverride")}/{qn("w:startOverride")}')
    assert start.get(qn("w:val")) == "1"
