"""Статус потребителя — это факт о цели приобретения, а не ссылка на закон.

Закон РК «О защите прав потребителей» защищает физическое лицо, приобретающее
товар (работу, услугу) для личных, семейных, домашних нужд, не связанных с
предпринимательской деятельностью. Подтверждённая статья закона подтверждает
только текст нормы; она не подтверждает, что истец под неё подпадает.

Разрыв был реальным: физическое лицо заказало корпоративный сайт, цель покупки
в материалах не названа — и иск получал отсрочку госпошлины по потребительскому
основанию и ссылку на ЗПП только потому, что модель написала слово «потребитель»,
а исследование подтвердило существование закона. Суд такую квалификацию не
принимает: он вернёт иск с неуплаченной пошлиной.

Здесь закрепляется обратный порядок: сначала цель приобретения, потом закон.
"""

from __future__ import annotations

from korgan.claim_consistency_guard import claim_consistency_errors
from korgan.claim_state_duty import decide_state_duty
from korgan.consumer_qualification import ConsumerStatus, consumer_status
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import _resolve_court


WEBSITE_CONTEXT = """
Истец: Ахметов Асхат Маратович, ИИН 850101300123
Ответчик: ТОО «WEB STUDIO KZ», БИН 200140012345
10.01.2026 заключен договор на разработку корпоративного сайта.
Оплачено 1 500 000 тенге. Сайт в срок не сдан.
Прошу взыскать уплаченную сумму.
"""

PHONE_CONTEXT = """
Истец: Ахметов Асхат Маратович, ИИН 850101300123
Ответчик: ТОО «TECHNO MARKET», БИН 200140012345
10.01.2026 приобретен смартфон за 450 000 тенге для личных нужд,
не связанных с предпринимательской деятельностью. Товар оказался неисправным.
Прошу взыскать уплаченную сумму.
"""

COMPANY_CONTEXT = """
Истец: ТОО «KAZTECH SOLUTIONS», БИН 230740012345
Ответчик: ТОО «WEB STUDIO KZ», БИН 200140012345
10.01.2026 заключен договор на разработку сайта. Оплачено 1 500 000 тенге.
Прошу взыскать уплаченную сумму.
"""


def _consumer_draft(**overrides: object) -> ClaimDraft:
    payload: dict[str, object] = {
        "status": VerificationStatus.VERIFIED,
        "title": "Исковое заявление о взыскании уплаченной суммы",
        "court": "[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        "claimant": ["Ахметов Асхат Маратович, ИИН 850101300123"],
        "defendant": ["ТОО «WEB STUDIO KZ»"],
        "price_of_claim": "1 500 000 тенге",
        "facts": ["Истец оплатил 1 500 000 тенге, работы не сданы."],
        "legal_basis": [
            "Закон Республики Казахстан «О защите прав потребителей» предоставляет истцу "
            "право требовать возврата уплаченной суммы."
        ],
        "requests": ["Взыскать уплаченную сумму 1 500 000 тенге."],
        "attachments": [],
        "verification_notes": [],
        "source_urls": [],
    }
    payload.update(overrides)
    return ClaimDraft(**payload)  # type: ignore[arg-type]


def _consumer_research() -> LegalResearch:
    url = "https://adilet.zan.kz/rus/docs/Z100000274_"
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=["Закон РК «О защите прав потребителей»"],
        procedural_requirements=[],
        verified_claims=[
            "Потребитель вправе требовать возврата уплаченной суммы "
            f"[основание: Закон РК о защите прав потребителей; источник: {url}]"
        ],
        unverified_claims=[],
        notes=[],
        source_urls=[url],
    )


# --- квалификация ---


def test_corporate_website_with_unknown_purpose_is_not_a_consumer_case() -> None:
    """Корпоративный сайт — признак предпринимательской цели, а не личной нужды."""
    assert consumer_status(WEBSITE_CONTEXT, _consumer_draft()) is ConsumerStatus.EXCLUDED


def test_purpose_left_unstated_is_not_treated_as_personal() -> None:
    """Молчание материалов о цели не означает, что цель личная."""
    context = WEBSITE_CONTEXT.replace("корпоративного сайта", "сайта")

    assert consumer_status(context, _consumer_draft()) is ConsumerStatus.UNKNOWN


def test_stated_personal_purpose_establishes_consumer_status() -> None:
    draft = _consumer_draft(
        defendant=["ТОО «TECHNO MARKET»"],
        price_of_claim="450 000 тенге",
        facts=["Смартфон приобретен для личных нужд, не связанных с предпринимательской деятельностью."],
        requests=["Взыскать уплаченную сумму 450 000 тенге."],
    )

    assert consumer_status(PHONE_CONTEXT, draft) is ConsumerStatus.ESTABLISHED


def test_legal_entity_claimant_can_never_be_a_consumer() -> None:
    draft = _consumer_draft(claimant=["ТОО «KAZTECH SOLUTIONS», БИН 230740012345"])

    assert consumer_status(COMPANY_CONTEXT, draft) is ConsumerStatus.EXCLUDED


def test_model_assertion_alone_does_not_establish_consumer_status() -> None:
    """«Истец является потребителем» — вывод модели, а не установленная цель."""
    draft = _consumer_draft(facts=["Истец является потребителем услуг ответчика."])
    context = WEBSITE_CONTEXT.replace("корпоративного сайта", "сайта")

    assert consumer_status(context, draft) is ConsumerStatus.UNKNOWN


# --- государственная пошлина ---


def test_unestablished_consumer_status_does_not_defer_the_state_duty() -> None:
    decision = decide_state_duty(WEBSITE_CONTEXT, _consumer_research(), _consumer_draft())

    assert decision.deferred is False
    assert "отсроч" not in decision.line.lower()


def test_established_consumer_status_still_defers_the_state_duty() -> None:
    draft = _consumer_draft(
        price_of_claim="450 000 тенге",
        facts=["Смартфон приобретен для личных нужд, не связанных с предпринимательской деятельностью."],
        requests=["Взыскать уплаченную сумму 450 000 тенге."],
    )

    decision = decide_state_duty(PHONE_CONTEXT, _consumer_research(), draft)

    assert decision.deferred is True


# --- блокировка утверждения о потребителе ---


def test_consumer_law_reference_without_established_purpose_blocks_the_claim() -> None:
    errors = claim_consistency_errors(WEBSITE_CONTEXT, _consumer_draft())

    assert any("потребител" in error.lower() for error in errors)


def test_consumer_law_reference_with_established_purpose_is_not_blocked() -> None:
    draft = _consumer_draft(
        price_of_claim="450 000 тенге",
        facts=["Смартфон приобретен для личных нужд, не связанных с предпринимательской деятельностью."],
        requests=["Взыскать уплаченную сумму 450 000 тенге."],
    )

    errors = claim_consistency_errors(PHONE_CONTEXT, draft)

    assert not any("потребител" in error.lower() for error in errors)


# --- подсудность ---


ALMATY_CONSUMER_VENUE = (
    "Иски о защите прав потребителей могут быть предъявлены по месту жительства истца "
    "[основание: часть 9 статьи 30 ГПК РК; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
)


def _venue_draft(**overrides: object) -> ClaimDraft:
    return _consumer_draft(
        claimant=["Ахметов Асхат Маратович, ИИН 850101300123, г. Алматы, Медеуский район"],
        defendant=["ТОО «WEB STUDIO KZ», БИН 200140012345, г. Алматы, Алатауский район"],
        **overrides,
    )


def _venue_research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[ALMATY_CONSUMER_VENUE],
        unverified_claims=[],
        notes=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
    )


def test_consumer_venue_requires_established_consumer_status() -> None:
    """Подсудность по месту жительства истца — тоже последствие квалификации."""
    draft = _venue_draft()
    context = WEBSITE_CONTEXT.replace("Истец: Ахметов", "г. Алматы. Истец: Ахметов")

    _resolve_court(context, _venue_research(), draft)

    assert "Медеуский" not in draft.court


def test_established_consumer_status_keeps_the_claimant_venue() -> None:
    draft = _venue_draft(
        facts=["Услуга приобреталась для личных нужд, не связанных с предпринимательской деятельностью."],
    )
    context = WEBSITE_CONTEXT.replace("Истец: Ахметов", "г. Алматы. Истец: Ахметов").replace(
        "корпоративного сайта", "сайта"
    )

    _resolve_court(context, _venue_research(), draft)

    assert draft.court == "Медеуский районный суд"


def test_claim_without_a_consumer_assertion_is_not_blocked() -> None:
    """Иск по общим нормам ГК РК не обязан доказывать статус потребителя."""
    draft = _consumer_draft(
        legal_basis=["Заказчик вправе требовать возврата уплаченного при нарушении срока выполнения работ."],
    )

    errors = claim_consistency_errors(WEBSITE_CONTEXT, draft)

    assert not any("потребител" in error.lower() for error in errors)


def test_named_document_mentioning_a_consumer_is_not_an_assertion() -> None:
    """Название приложенного документа не превращает иск в потребительский."""
    draft = _consumer_draft(
        legal_basis=["Заказчик вправе требовать возврата уплаченного при нарушении срока выполнения работ."],
        attachments=["Претензия потребителя от 10.02.2026 с отметкой о вручении."],
    )

    errors = claim_consistency_errors(WEBSITE_CONTEXT, draft)

    assert not any("потребител" in error.lower() for error in errors)
