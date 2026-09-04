"""Сквозная проверка на деле, которое ломало сразу четыре детерминированных шага.

Потребитель полностью оплатил изготовление и установку кухонного гарнитура,
исполнитель сорвал конечный срок работ, претензия осталась без ответа. Дело
типовое, а иск по нему выходил негодным: договорная неустойка не считалась,
требование о ней заменялось плейсхолдером, цена иска теряла неустойку, и
государственная пошлина не рассчитывалась.

Набор идёт по тому же слою, который решает судьбу документа в проде:
детерминированные расчёты поверх готового черновика и оценка качества. Сеть и
модель не используются.
"""

from __future__ import annotations

from datetime import date

from korgan.claim_docx import build_claim_docx
from korgan.document_quality import assess_document_quality, docx_text
from korgan.late_interest_hotfix import _apply_verified_penalty
from korgan.claim_state_duty import apply_professional_state_duty
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.provision_check import verified_claim_line

GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"

ARTICLE_272 = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства "
    "и требованиями законодательства, а при отсутствии таких условий и требований - в соответствии "
    "с обычаями делового оборота или иными обычно предъявляемыми требованиями."
)
ARTICLE_293 = (
    "Неустойкой (штрафом, пеней) признается определенная законодательством или договором денежная сумма, "
    "которую должник обязан уплатить кредитору в случае неисполнения или ненадлежащего исполнения обязательства, "
    "в частности, в случае просрочки исполнения."
)
ARTICLE_616 = (
    "По договору подряда одна сторона (подрядчик) обязуется выполнить по заданию другой стороны (заказчика) "
    "определенную работу и сдать ей результат работы в установленный срок, а заказчик обязуется принять "
    "результат работы и оплатить его (уплатить цену работы)."
)

CONTEXT = (
    "Истец: Сериков Арман Нурланович.\n"
    "Статус: физическое лицо.\n"
    "Адрес проживания: город Алматы, Бостандыкский район, улица Тестовая, дом 25, квартира 18.\n"
    "Ответчик: ТОО «Мебель Стандарт», город Алматы, Алмалинский район, улица Условная, дом 50.\n"
    "20 марта 2026 года заключён договор № MS-114/26 на изготовление, доставку и установку "
    "кухонного гарнитура для личных бытовых нужд истца. Цена договора 1 200 000 тенге "
    "оплачена истцом полностью 20 марта 2026 года.\n"
    "Договором установлен окончательный срок выполнения работ: до 15 июня 2026 года включительно.\n"
    "Пунктом 5.2 договора предусмотрено: при нарушении срока выполнения работ исполнитель выплачивает "
    "заказчику неустойку в размере 0,1 % от стоимости невыполненного обязательства за каждый день "
    "просрочки, но не более 10 % стоимости договора.\n"
    "Работы не выполнены, акт выполненных работ не подписан, деньги не возвращены.\n"
    "Истец требует взыскать уплаченную сумму и договорную неустойку.\n"
    "Претензия направлена 10 августа 2026 года, получена ответчиком 12 августа 2026 года, ответа нет.\n"
)


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            verified_claim_line(
                "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства",
                "статья 272 ГК РК", ARTICLE_272, GK_GENERAL_URL,
            ),
            verified_claim_line(
                "Неустойкой признается определенная договором денежная сумма, которую должник обязан "
                "уплатить кредитору в случае просрочки исполнения",
                "статья 293 ГК РК", ARTICLE_293, GK_GENERAL_URL,
            ),
            verified_claim_line(
                "По договору подряда подрядчик обязуется выполнить работу и сдать её результат заказчику "
                "в установленный срок, а заказчик обязуется принять результат работы и оплатить его",
                "статья 616 ГК РК", ARTICLE_616, GK_SPECIAL_URL,
            ),
        ],
        unverified_claims=[],
        source_urls=[GK_GENERAL_URL, GK_SPECIAL_URL],
        notes=[],
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании уплаченной по договору суммы и договорной неустойки",
        court="районный суд № 2 Алмалинского района города Алматы",
        claimant=[
            "Сериков Арман Нурланович",
            "адрес: город Алматы, Бостандыкский район, улица Тестовая, дом 25, квартира 18",
        ],
        defendant=[
            "Товарищество с ограниченной ответственностью «Мебель Стандарт»",
            "юридический адрес: город Алматы, Алмалинский район, улица Условная, дом 50",
        ],
        price_of_claim="1 200 000 тенге",
        facts=[
            "20 марта 2026 года между сторонами заключён договор № MS-114/26 на изготовление, доставку "
            "и установку кухонного гарнитура для личных бытовых нужд истца.",
            "Истец оплатил цену договора 1 200 000 тенге полностью 20 марта 2026 года.",
            "Договором установлен окончательный срок выполнения работ — до 15 июня 2026 года включительно.",
            "Работы не выполнены, акт выполненных работ не подписан, денежные средства не возвращены.",
        ],
        legal_basis=[
            "Обязательство должно исполняться надлежащим образом. Правовое основание: статья 272 ГК РК.",
        ],
        requests=[
            "Взыскать с ТОО «Мебель Стандарт» в пользу Серикова Армана Нурлановича уплаченные по договору "
            "№ MS-114/26 от 20 марта 2026 года денежные средства в размере 1 200 000 тенге.",
            "Взыскать с ТОО «Мебель Стандарт» в пользу Серикова Армана Нурлановича договорную неустойку "
            "за нарушение срока выполнения работ в размере 92 400 тенге.",
        ],
        attachments=[
            "Договор № MS-114/26 от 20 марта 2026 года.",
            "Банковская квитанция об оплате 1 200 000 тенге от 20 марта 2026 года.",
            "Копия досудебной претензии от 10 августа 2026 года.",
            "Подтверждение вручения претензии ответчику от 12 августа 2026 года.",
        ],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL, GK_SPECIAL_URL],
    )


def _prepared() -> ClaimDraft:
    """Тот же порядок шагов, что и в production: неустойка, затем пошлина."""
    draft = _draft()
    research = _research()
    _apply_verified_penalty(CONTEXT, research, draft, filing_date=date(2026, 8, 31))
    apply_professional_state_duty(CONTEXT, research, draft)
    return draft


def test_contractual_penalty_reaches_the_prayer_with_its_amount() -> None:
    draft = _prepared()
    penalty_requests = [item for item in draft.requests if "неустойк" in item.lower()]

    assert len(penalty_requests) == 1
    assert "92 400 тенге" in penalty_requests[0]
    assert "ТРЕБУЕТ" not in penalty_requests[0]
    assert "16.06.2026" in penalty_requests[0]
    assert "31.08.2026" in penalty_requests[0]


def test_claim_price_includes_the_penalty() -> None:
    price = _prepared().price_of_claim

    assert price.startswith("1 292 400 тенге")
    assert "1 200 000 тенге" in price and "92 400 тенге" in price


def test_state_duty_is_one_percent_of_the_claim_price() -> None:
    """Физическое лицо, 1% от 1 292 400 = 12 924 тенге (статья 665 НК РК)."""
    draft = _prepared()

    assert "12 924 тенге" in draft.state_duty
    assert "1%" in draft.state_duty
    assert any("12 924 тенге" in item and "пошлин" in item.lower() for item in draft.requests)


def test_calculation_section_exposes_every_element() -> None:
    body = "\n".join(_prepared().calculation)

    assert "Основная сумма требования: 1 200 000 тенге" in body
    assert "0,1%" in body
    assert "77" in body
    assert "1 200 000 тенге × 0,1% × 77 дн. = 92 400 тенге" in body
    assert "Итого цена иска: 1 292 400 тенге" in body


def test_penalty_section_is_not_attributed_to_article_353() -> None:
    body = docx_text(build_claim_docx(_prepared()))

    assert "Расчёт договорной неустойки" in body
    assert "353" not in body
    assert "стоимости невыполненного обязательства" in body


def test_unsigned_act_is_not_reported_as_a_lost_attachment() -> None:
    report = assess_document_quality("claim", CONTEXT, _research(), _prepared())

    assert not any("потеряно упомянутое доказательство: акт" in issue for issue in report.issues)


def test_no_internal_marker_leaks_into_the_document() -> None:
    body = docx_text(build_claim_docx(_prepared()))

    for marker in ("NEEDS_VERIFICATION", "SENIOR_PREFLIGHT_SCORE", "FILING_ACTION", "LEGAL_GROUNDING"):
        assert marker not in body
