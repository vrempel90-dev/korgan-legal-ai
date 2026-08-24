from korgan.contract_generation_hotfix import (
    _SPECIAL_PART_NOTE,
    _inject_verified_special_part,
)
from korgan.legal_types import ContractDraft, ContractSection, LegalResearch, VerificationStatus


SERVICES_CONTEXT = "Подготовить договор возмездного оказания юридических услуг между Исполнителем и Заказчиком."


def _draft() -> ContractDraft:
    return ContractDraft(
        status=VerificationStatus.VERIFIED,
        contract_type="Договор возмездного оказания услуг",
        title="Договор возмездного оказания услуг",
        place_and_date="г. Алматы, 24.08.2026",
        party_a=["ТОО «Исполнитель»"],
        party_b=["ТОО «Заказчик»"],
        preamble=["ТОО «Исполнитель» и ТОО «Заказчик» заключили настоящий Договор."],
        sections=[ContractSection(heading="Предмет договора", clauses=[])],
        requisites_a=["ТОО «Исполнитель»"],
        requisites_b=["ТОО «Заказчик»"],
        verification_notes=[],
        source_urls=[],
    )


def _research(lines: list[str]) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=lines,
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[],
    )


def test_services_contract_injects_only_verified_special_part_articles():
    research = _research([
        "По договору возмездного оказания услуг исполнитель оказывает услуги, а заказчик их оплачивает "
        "[основание: статья 683 ГК РК (Особенная часть); текст нормы: исполнитель обязуется оказать услуги, а заказчик обязуется оплатить эти услуги; источник: https://adilet.zan.kz/rus/docs/K990000409_]",
        "Заказчик оплачивает услуги в сроки и порядке, установленные договором "
        "[основание: статья 685 ГК РК (Особенная часть); текст нормы: заказчик обязан оплатить оказанные услуги в сроки и в порядке, указанные в договоре; источник: https://adilet.zan.kz/rus/docs/K990000409_]",
    ])
    draft = _draft()

    _inject_verified_special_part(SERVICES_CONTEXT, research, draft, language="ru")

    legal_sections = [section for section in draft.sections if "законодатель" in section.heading.lower()]
    assert len(legal_sections) == 1
    text = "\n".join(legal_sections[0].text_lines())
    assert "статья 683" in text
    assert "статья 685" in text
    assert "Сноска" not in text
    assert "http" not in text
    assert draft.status is VerificationStatus.VERIFIED
    assert _SPECIAL_PART_NOTE not in draft.verification_notes


def test_services_contract_cannot_be_ready_without_verified_special_part():
    draft = _draft()
    research = _research([])

    _inject_verified_special_part(SERVICES_CONTEXT, research, draft, language="ru")

    assert draft.status is VerificationStatus.NEEDS_VERIFICATION
    assert _SPECIAL_PART_NOTE in draft.verification_notes
