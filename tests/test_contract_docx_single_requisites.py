from __future__ import annotations

import io

from docx import Document

from korgan.contract_docx import build_contract_docx
from korgan.legal_types import ContractClause, ContractDraft, ContractSection, VerificationStatus


def _all_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    parts = [paragraph.text for paragraph in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(paragraph.text for paragraph in cell.paragraphs)
    return "\n".join(parts)


def test_contract_renderer_outputs_requisites_and_signatures_once() -> None:
    draft = ContractDraft(
        status=VerificationStatus.VERIFIED,
        contract_type="договор оказания услуг",
        title="Договор оказания услуг",
        place_and_date="г. Алматы, 24.08.2026",
        party_a=["ТОО «Исполнитель», БИН 230740012345"],
        party_b=["ТОО «Заказчик», БИН 210540009999"],
        preamble=[
            "ТОО «Исполнитель», именуемое в дальнейшем «Исполнитель», в лице директора А.А. Алимова, действующего на основании Устава, с одной стороны, и ТОО «Заказчик», именуемое в дальнейшем «Заказчик», в лице директора Б.Б. Берикова, действующего на основании Устава, с другой стороны, совместно именуемые «Стороны», заключили настоящий Договор."
        ],
        sections=[
            ContractSection(
                heading="Предмет Договора",
                clauses=[ContractClause("Исполнитель оказывает услуги, а Заказчик принимает результат.")],
            ),
            ContractSection(
                heading="Реквизиты и подписи сторон",
                clauses=[ContractClause("НЕ ДОЛЖНО ПОПАСТЬ В ОСНОВНОЕ ТЕЛО")],
            ),
        ],
        requisites_a=[
            "ТОО «Исполнитель»",
            "БИН 230740012345",
            "Подпись: ____________________",
        ],
        requisites_b=[
            "ТОО «Заказчик»",
            "БИН 210540009999",
            "Подпись: ____________________",
        ],
        verification_notes=[],
        source_urls=[],
    )

    text = _all_text(build_contract_docx(draft))
    lowered = text.casefold()

    assert lowered.count("реквизиты и подписи сторон") == 1
    assert "не должно попасть в основное тело" not in lowered
    assert text.count("Подпись: ____________________") == 2
    assert text.count("БИН 230740012345") == 1
    assert text.count("БИН 210540009999") == 1
