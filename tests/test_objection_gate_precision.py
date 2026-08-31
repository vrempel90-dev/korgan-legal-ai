"""Шлюз возражений обязан ловить пустые доводы и не блокировать обоснованные.

Три отдельных отказа одного и того же шлюза, каждый со своей ценой:

1. Ложная блокировка. Модель кладёт заголовок довода в ``text``, а даты и
   норму — в ``subclauses``/``prose`` (эта структура и предусмотрена схемой).
   Шлюз проверял только ``text``, опоры не видел и блокировал полностью
   обоснованное возражение.

2. Пропуск пустого довода. Опорой считалась любая из альтернатив, включая
   «N лет». «Истёк срок исковой давности — 3 года» проходило, не называя ни
   дат, из которых срок вычисляется, ни нормы, — ровно тот довод «на всякий
   случай», ради отсечения которого шлюз и существует.

3. Ложное требование к неденежной претензии. Разбор расчёта требовался, как
   только есть возражения, — даже когда контрагент требует устранить
   недостатки и никакого расчёта не предъявлял. Документ уходил вниз за
   отсутствие раздела, которого в нём быть не должно.
"""

from __future__ import annotations

from korgan.document_quality import assess_document_quality, unsupported_objections
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.pretrial_response import PretrialResponseDraft, pretrial_response_quality_issues
from korgan.response_types import ResponseObjection, ResponseToClaimDraft

GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
ARTICLE_272 = "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства."

CONTEXT = (
    "Истец: Ахметов Руслан Маратович, ИИН 900101300123, г. Алматы, ул. Абая, 150.\n"
    "Ответчик: ТОО «Компания», БИН 210987654321, г. Алматы, ул. Розыбакиева, 10.\n"
    "Договор № 12 от 15.01.2026."
)


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[GK_GENERAL_URL],
        notes=[],
    )


# --- 1. структурированное возражение: опора лежит в subclauses/prose --------


def _response(**overrides) -> ResponseToClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Медеуский районный суд города Алматы",
        case_number="2-1234/2026",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123"],
        defendant=['ТОО «Компания», БИН 210987654321'],
        claim_summary=["Истец просит взыскать 2 300 000 тенге."],
        admitted_circumstances=["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
        disputed_circumstances=["Оспаривается объём принятых работ по акту от 20.02.2026."],
        position=["Иск подлежит частичному удовлетворению."],
        objections=[],
        calculation_review=["Начисление произведено с 01.03.2026 при сроке оплаты 20.03.2026."],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        requests=["Отказать в удовлетворении исковых требований в части 900 000 тенге."],
        attachments=["Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
    )
    data.update(overrides)
    return ResponseToClaimDraft(**data)


SUPPORTED_STRUCTURED = ResponseObjection(
    text="Истечение срока исковой давности",
    subclauses=[
        "Течение срока началось 15.01.2023 — со дня наступления срока оплаты по пункту 4.2 договора.",
        "Срок истёк 15.01.2026, иск подан 20.02.2026.",
    ],
    prose=["Срок установлен статьёй 178 ГК РК и составляет три года."],
)


def test_structured_objection_with_anchors_in_subclauses_is_not_blocked() -> None:
    report = assess_document_quality("response_to_claim", CONTEXT, _research(), _response(objections=[SUPPORTED_STRUCTURED]))

    assert not any("без подтверждающих дат" in blocker for blocker in report.hard_blockers), report.hard_blockers


def test_structured_objection_without_any_anchor_is_still_blocked() -> None:
    """Ослабление проверки не должно пропускать по-настоящему пустой довод."""
    empty = ResponseObjection(
        text="Истечение срока исковой давности",
        subclauses=["Полагаем срок пропущенным."],
        prose=["Оснований для удовлетворения иска не усматриваем."],
    )
    report = assess_document_quality("response_to_claim", CONTEXT, _research(), _response(objections=[empty]))

    assert any("без подтверждающих дат" in blocker for blocker in report.hard_blockers), report.hard_blockers


# --- 2. длительность сама по себе опорой не является ------------------------


def test_bare_duration_is_not_an_anchor_for_a_limitation_defence() -> None:
    """«3 года» не называет ни дат, из которых срок вычисляется, ни нормы."""
    assert unsupported_objections(["Истёк срок исковой давности — 3 года."])


def test_dates_remain_a_valid_anchor() -> None:
    assert unsupported_objections(
        ["Срок исковой давности истёк 15.01.2026: течение началось 15.01.2023."]
    ) == []


def test_named_article_remains_a_valid_anchor() -> None:
    assert unsupported_objections(
        ["Срок исковой давности пропущен, что следует из статьи 178 ГК РК и материалов дела."]
    ) == []


def test_objection_without_the_guarded_topic_is_untouched() -> None:
    assert unsupported_objections(["Работы на сумму 900 000 тенге не приняты по акту."]) == []


# --- 3. разбор расчёта требуется только для денежной претензии --------------


def _pretrial_response(**overrides) -> PretrialResponseDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ",
        sender=['ТОО «Компания», БИН 210987654321'],
        recipient=["Ахметов Руслан Маратович, ИИН 900101300123"],
        reference="претензия от 05.03.2026 № 7",
        claim_summary=["Заявлено требование безвозмездно устранить недостатки работ по акту от 20.02.2026."],
        admitted_circumstances=["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
        disputed_circumstances=["Оспаривается наличие недостатков, указанных в пункте 3 акта от 20.02.2026."],
        position=["Требование об устранении недостатков не признаётся."],
        objections=["Недостатки, названные в акте от 20.02.2026, работами подрядчика не вызваны."],
        calculation_review=[],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        settlement_offer="",
        response_terms=["Готовы провести совместный осмотр работ."],
        attachments=["Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
    )
    data.update(overrides)
    return PretrialResponseDraft(**data)


def test_non_monetary_pretension_does_not_require_calculation_review() -> None:
    report = assess_document_quality("pretrial_response", CONTEXT, _research(), _pretrial_response())

    assert not any("расчёт" in item.lower() for item in report.hard_blockers), report.hard_blockers
    assert not any("расчёт" in item.lower() for item in report.issues), report.issues


def test_monetary_pretension_still_requires_calculation_review() -> None:
    """Ослабление не должно снимать требование там, где расчёт есть о чём разбирать."""
    monetary = _pretrial_response(
        claim_summary=["Заявлено требование об оплате 2 300 000 тенге."],
        objections=["Работы на сумму 900 000 тенге не приняты: акт от 20.02.2026 подписан с замечаниями."],
        calculation_review=[],
    )
    issues = pretrial_response_quality_issues(monetary, _research())

    assert any("расчёт" in item.lower() for item in issues), issues
