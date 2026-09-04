"""Проверка приложений не требует документа, которого по материалам не существует.

Гейт сравнивает упомянутые в материалах доказательства с перечнем приложений и
отмечает потерянные. Он делал это по вхождению подстроки, поэтому:

1. «акт выполненных работ не подписан» — то есть акта нет и приложить его
   нельзя — читалось как потерянное приложение. В деле о невыполненных работах
   отсутствие акта само является основанием иска;
2. подстрока «акт» находилась внутри слов «факт», «фактически», «контакты», и
   иск получал замечание из-за собственной фактической части.

Оба случая понижали оценку исправного документа и уводили его в PRELIMINARY.
"""

from __future__ import annotations

from korgan.document_quality import assess_document_quality
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line

GK_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
ARTICLE_272 = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства "
    "и требованиями законодательства, а при отсутствии таких условий и требований - в соответствии "
    "с обычаями делового оборота или иными обычно предъявляемыми требованиями."
)

CONTEXT = (
    "Истец: Сериков Арман Нурланович, физическое лицо, город Алматы, улица Тестовая, 25.\n"
    "Ответчик: ТОО «Мебель Стандарт», город Алматы, Алмалинский район, улица Условная, 50.\n"
    "Договор № MS-114/26 от 20.03.2026, цена 1 200 000 тенге, оплачена полностью 20.03.2026.\n"
    "Срок выполнения работ до 15.06.2026. Работы не выполнены, акт выполненных работ не подписан.\n"
    "Претензия направлена 10.08.2026, получена 12.08.2026, ответа нет.\n"
    "Контакты сторон указаны в договоре; фактические обстоятельства подтверждаются перепиской.\n"
)


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании уплаченной по договору суммы",
        court="районный суд № 2 Алмалинского района города Алматы",
        claimant=["Сериков Арман Нурланович, город Алматы, улица Тестовая, 25"],
        defendant=["ТОО «Мебель Стандарт», город Алматы, улица Условная, 50"],
        price_of_claim="1 200 000 тенге",
        facts=["Работы по договору № MS-114/26 от 20.03.2026 не выполнены."],
        legal_basis=["Обязательство должно исполняться надлежащим образом. Правовое основание: статья 272 ГК РК."],
        requests=["Взыскать с ответчика уплаченные по договору денежные средства в размере 1 200 000 тенге."],
        attachments=[
            "Договор № MS-114/26 от 20 марта 2026 года.",
            "Банковская квитанция об оплате 1 200 000 тенге.",
            "Копия досудебной претензии от 10 августа 2026 года.",
        ],
        verification_notes=[],
        source_urls=[GK_URL],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            verified_claim_line(
                "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства",
                "статья 272 ГК РК",
                ARTICLE_272,
                GK_URL,
            )
        ],
        unverified_claims=[],
        source_urls=[GK_URL],
        notes=[],
    )


def _attachment_issues(context: str) -> list[str]:
    report = assess_document_quality("claim", context, _research(), _draft())
    return [issue for issue in report.issues if "потеряно упомянутое доказательство" in issue]


def test_unsigned_act_is_not_demanded_as_an_attachment() -> None:
    assert _attachment_issues(CONTEXT) == []


def test_the_word_fact_is_not_read_as_an_act() -> None:
    context = "Договор № 1, квитанция об оплате, претензия направлена. Фактические обстоятельства изложены выше."
    assert not any("акт" in issue for issue in _attachment_issues(context))


def test_a_genuinely_missing_attachment_is_still_reported() -> None:
    """Названный в материалах существующий документ по-прежнему требуется в приложениях."""
    context = CONTEXT + "Сторонами подписан акт приёма-передачи от 01.07.2026.\n"

    assert any("акт" in issue for issue in _attachment_issues(context))
