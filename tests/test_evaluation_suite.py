"""Приёмочный набор: что KORGAN обязан ловить до выпуска документа клиенту.

Каждая проверка — это отдельный способ испортить юридический документ.
Позитивные сценарии закрывают виды споров, с которыми приходят реально; в
негативных документ уже испорчен, и набор фиксирует, что дефект блокирует
выпуск, а не проходит молча.

Сеть и OpenAI не используются: проверяются детерминированные gate поверх
готовых черновиков, то есть ровно тот слой, который решает, уйдёт документ
клиенту как готовый или как предварительный.
"""

from __future__ import annotations

from datetime import date

import pytest

from korgan.claim_docx import build_claim_docx
from korgan.contractual_penalty import ContractualPenaltyTerms, calc_contractual_penalty
from korgan.document_quality import assess_document_quality, docx_text
from korgan.legal_calculation import (
    CalculationGap,
    contractual_penalty_component,
    court_costs_component,
    legal_services_component,
    principal_component,
    render_calculation,
    total_claim_price,
    try_contractual_penalty_component,
)
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.pretrial import PretrialDraft, pretrial_quality_issues
from korgan.pretrial_response import PretrialResponseDraft, pretrial_response_quality_issues
from korgan.provision_check import verified_claim_line
from korgan.response_types import ResponseToClaimDraft

GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
GK_GENERAL_URL = "https://adilet.zan.kz/rus/docs/K940001000_"

ARTICLE_623 = (
    "Заказчик обязан уплатить подрядчику обусловленную цену после окончательной сдачи "
    "результатов работы при условии, что работа выполнена надлежащим образом и в согласованный срок."
)
ARTICLE_293 = (
    "Неустойкой (штрафом, пеней) признается определенная законодательством или договором денежная сумма, "
    "которую должник обязан уплатить кредитору в случае неисполнения или ненадлежащего исполнения обязательства."
)
ARTICLE_272 = "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства."


def _research(*claims: str) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(claims)
        or [verified_claim_line("Обязательство должно исполняться надлежащим образом", "статья 272 ГК РК", ARTICLE_272, GK_GENERAL_URL)],
        unverified_claims=[],
        source_urls=[GK_GENERAL_URL],
        notes=[],
    )


# Контекст качества — это полный набор источников по делу, а не его пересказ.
# Реквизит, даты, суммы и доказательства в документе проверяются против него,
# поэтому фикстура обязана содержать всё, на что опирается черновик.
PARTIES = (
    "Истец: Ахметов Руслан Маратович, ИИН 900101300123, г. Алматы, Медеуский район, ул. Абая, 150.\n"
    "Ответчик: ТОО «Компания», БИН 210987654321, г. Алматы, Алатауский район, ул. Розыбакиева, 10.\n"
    "Иск подаётся в Медеуский районный суд города Алматы."
)
CONTEXT = (
    PARTIES + "\n"
    "Договор № 12 от 15.01.2026. Обязательство не исполнено, задолженность 2 300 000 тенге.\n"
    "Работы приняты по акту от 20.02.2026; в акте зафиксированы замечания к работам "
    "на сумму 900 000 тенге, бесспорная часть составляет 1 400 000 тенге.\n"
    "Срок оплаты по пункту 4.2 договора наступает 20.03.2026, начисление произведено с 01.03.2026.\n"
    "Ответчику направлена претензия от 05.03.2026 № 7, ответа не поступило."
)


def _claim(**overrides) -> ClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности",
        court="Медеуский районный суд города Алматы",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123, г. Алматы, ул. Абая, 150"],
        defendant=['ТОО «Компания», БИН 210987654321, г. Алматы, ул. Розыбакиева, 10'],
        price_of_claim="2 300 000 тенге",
        facts=[
            "Между сторонами заключён договор № 12 от 15.01.2026.",
            "Истец исполнил обязательство, что подтверждается актом от 20.02.2026.",
            "Ответчик оплату не произвёл, задолженность составляет 2 300 000 тенге.",
        ],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        requests=["Взыскать с ответчика 2 300 000 тенге основного долга."],
        # Приложения — опись доказательств, а не формальность: документ, на
        # который опирается фактическая часть, обязан быть приложен к иску.
        attachments=[
            "Копия договора № 12 от 15.01.2026",
            "Копия акта от 20.02.2026",
            "Копия претензии от 05.03.2026 № 7",
            "Квитанция об уплате государственной пошлины",
        ],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
        state_duty="23 000 тенге",
    )
    data.update(overrides)
    return ClaimDraft(**data)


def test_production_ready_threshold_is_ten_out_of_ten() -> None:
    """Боевой порог выпуска — 10.0/10, а не значение по умолчанию 8.5.

    Литерал в document_quality — это значение ДО установки боевых слоёв;
    universal_word_quality_guard поднимает планку. Раньше это нигде не
    проверялось, и набор тестов мерил документ не той линейкой, что production.
    """
    import korgan.strict_bot  # noqa: F401  — тот же импорт, что делает API
    from korgan import document_quality

    assert document_quality.MIN_READY_SCORE == 10.0


# =========================================================================
# Позитивные сценарии: виды споров
# =========================================================================


ARTICLE_722 = (
    "Заемщик обязан возвратить заимодателю предмет займа в срок и в порядке, "
    "которые предусмотрены договором займа."
)
ARTICLE_616_RENT = (
    "Наниматель обязан своевременно вносить плату за пользование имуществом в размере и в сроки, "
    "которые предусмотрены договором имущественного найма."
)
ARTICLE_439_SUPPLY = (
    "Покупатель обязан оплатить товар по цене, предусмотренной договором купли-продажи, "
    "в срок и в порядке, установленные договором."
)
ARTICLE_685_SERVICES = (
    "Заказчик обязан оплатить оказанные ему услуги в сроки и в порядке, "
    "которые указаны в договоре возмездного оказания услуг."
)


@pytest.mark.parametrize(
    ("dispute", "materials", "attachments", "facts", "prayer", "statement", "article", "text", "url"),
    [
        (
            "подряд",
            "Договор подряда № 12 от 15.01.2026 на 2 300 000 тенге. "
            "Работы приняты по акту от 20.02.2026. Претензия направлена 05.03.2026.",
            (
                "Копия договора подряда № 12 от 15.01.2026",
                "Копия акта от 20.02.2026",
                "Копия претензии от 05.03.2026",
            ),
            "По договору подряда № 12 от 15.01.2026 работы выполнены и приняты по акту от 20.02.2026, оплата не произведена.",
            "Взыскать с ответчика 2 300 000 тенге задолженности по договору подряда.",
            "Заказчик обязан оплатить принятые работы",
            "статья 623 ГК РК",
            ARTICLE_623,
            GK_SPECIAL_URL,
        ),
        (
            "услуги",
            "Договор возмездного оказания услуг № 5 от 10.01.2026 на 2 300 000 тенге. "
            "Акт оказанных услуг подписан 01.02.2026. Претензия направлена 05.03.2026.",
            (
                "Копия договора возмездного оказания услуг № 5 от 10.01.2026",
                "Копия акта оказанных услуг от 01.02.2026",
                "Копия претензии от 05.03.2026",
            ),
            "По договору возмездного оказания услуг № 5 от 10.01.2026 услуги оказаны, акт подписан 01.02.2026, оплата не поступила.",
            "Взыскать с ответчика 2 300 000 тенге задолженности по договору оказания услуг.",
            "Заказчик обязан оплатить оказанные услуги",
            "статья 685 ГК РК",
            ARTICLE_685_SERVICES,
            GK_SPECIAL_URL,
        ),
        (
            "поставка",
            "Договор поставки № 9 от 12.01.2026 на 2 300 000 тенге. "
            "Товар передан по накладной от 20.01.2026. Претензия направлена 05.03.2026.",
            (
                "Копия договора поставки № 9 от 12.01.2026",
                "Копия накладной от 20.01.2026",
                "Копия претензии от 05.03.2026",
            ),
            "По договору поставки № 9 от 12.01.2026 товар поставлен по накладной от 20.01.2026, оплата не произведена.",
            "Взыскать с ответчика 2 300 000 тенге задолженности по договору поставки.",
            "Покупатель обязан оплатить поставленный товар",
            "статья 439 ГК РК",
            ARTICLE_439_SUPPLY,
            GK_SPECIAL_URL,
        ),
        (
            "аренда",
            "Договор аренды № 3 от 01.01.2026, задолженность по арендной плате 2 300 000 тенге. "
            "Помещение передано по акту приёма-передачи от 05.01.2026. Претензия направлена 05.03.2026.",
            (
                "Копия договора аренды № 3 от 01.01.2026",
                "Копия акта приёма-передачи от 05.01.2026",
                "Копия претензии от 05.03.2026",
            ),
            "По договору аренды № 3 от 01.01.2026 помещение передано по акту от 05.01.2026, арендная плата не внесена.",
            "Взыскать с ответчика 2 300 000 тенге задолженности по арендной плате.",
            "Наниматель обязан своевременно вносить плату за пользование имуществом",
            "статья 616 ГК РК",
            ARTICLE_616_RENT,
            GK_SPECIAL_URL,
        ),
        (
            "заём",
            "Договор займа № 7 от 20.01.2026 на 2 300 000 тенге. "
            "Средства перечислены платёжным поручением от 21.01.2026. Претензия направлена 05.03.2026.",
            (
                "Копия договора займа № 7 от 20.01.2026",
                "Копия платёжного поручения от 21.01.2026",
                "Копия претензии от 05.03.2026",
            ),
            "По договору займа № 7 от 20.01.2026 денежные средства переданы платёжным поручением от 21.01.2026 и не возвращены.",
            "Взыскать с ответчика 2 300 000 тенге основного долга по договору займа.",
            "Заёмщик обязан возвратить предмет займа в срок, предусмотренный договором",
            "статья 722 ГК РК",
            ARTICLE_722,
            GK_SPECIAL_URL,
        ),
    ],
)
def test_ordinary_money_dispute_reaches_the_ready_score(
    dispute: str,
    materials: str,
    attachments: tuple[str, ...],
    facts: str,
    prayer: str,
    statement: str,
    article: str,
    text: str,
    url: str,
) -> None:
    """Каждый вид спора обоснован нормой ИМЕННО об этом обязательстве.

    Норма об общем принципе исполнения обязательств не заменяет специальную:
    applicability-аудит обязан это ловить, поэтому у сценария своя статья.
    Фактическая часть раскрывает хронологию: заключение, исполнение, нарушение,
    и каждый её реквизит существует в материалах именно этого сценария —
    договор чужого дела не подтверждает договор этого.
    """
    verified = verified_claim_line(statement, article, text, url)
    context = f"{PARTIES}\n{materials}\nЗадолженность составляет 2 300 000 тенге."
    draft = _claim(
        facts=[
            facts,
            "Ответчик задолженность не погасил, на претензию от 05.03.2026 не ответил.",
            "По состоянию на дату подачи иска задолженность составляет 2 300 000 тенге.",
        ],
        legal_basis=[f"{text} Правовое основание: {article}."],
        requests=[prayer],
        attachments=[*attachments, "Квитанция об уплате государственной пошлины"],
    )
    report = assess_document_quality("claim", context, _research(verified), draft)
    assert report.ready is True, f"{dispute}: {report.hard_blockers}"


def test_general_obligation_norm_does_not_support_a_specific_contract_claim() -> None:
    """Общая норма об исполнении обязательств не заменяет специальную."""
    draft = _claim(
        facts=["По договору займа № 7 от 20.01.2026 денежные средства не возвращены."],
        requests=["Взыскать с ответчика 2 300 000 тенге основного долга по договору займа."],
    )
    report = assess_document_quality("claim", CONTEXT, _research(), draft)
    assert report.ready is False


def test_contractual_penalty_uses_the_agreed_rate_not_article_353() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=None, clause="6.3")
    penalty = calc_contractual_penalty(2_300_000, terms, date(2026, 3, 1), date(2026, 3, 31))
    component = contractual_penalty_component(penalty)

    assert component.amount == 71_300
    assert "0,1%" in component.penalty_rate
    assert "353" not in component.render()
    assert "пункт 6.3 договора" in component.basis


def test_partial_payment_splits_the_period_by_payment_dates() -> None:
    """Частичная оплата — два периода с разной базой, а не одна усреднённая сумма."""
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=None, clause="6.3")
    before = calc_contractual_penalty(2_300_000, terms, date(2026, 3, 1), date(2026, 3, 15))
    after = calc_contractual_penalty(1_400_000, terms, date(2026, 3, 16), date(2026, 3, 31))

    lines = render_calculation([
        contractual_penalty_component(before),
        contractual_penalty_component(after),
    ])
    body = "\n".join(lines)

    assert "с 01.03.2026 по 15.03.2026" in body
    assert "с 16.03.2026 по 31.03.2026" in body
    assert "база: 2 300 000 тенге" in body
    assert "база: 1 400 000 тенге" in body


def test_several_claims_reconcile_with_the_claim_price() -> None:
    terms = ContractualPenaltyTerms(rate_percent_per_day=0.1, cap_percent=None, clause="6.3")
    penalty = calc_contractual_penalty(2_300_000, terms, date(2026, 3, 1), date(2026, 3, 31))
    components = [
        principal_component(2_300_000, basis="договор № 12 от 15.01.2026"),
        contractual_penalty_component(penalty),
        legal_services_component(150_000, basis="договор об оказании юридических услуг от 01.02.2026"),
        court_costs_component(24_000, basis="платёжное поручение об уплате госпошлины"),
    ]

    assert total_claim_price(components) == 2_371_300
    body = "\n".join(render_calculation(components))
    assert "Итого цена иска: 2 371 300 тенге" in body
    # Юридические и судебные расходы показаны, но в цену иска не включены.
    assert body.count("не входит в цену иска") == 2


def test_missing_data_produces_a_gap_not_a_number() -> None:
    result = try_contractual_penalty_component(
        principal=2_300_000,
        rate_percent_per_day=0.1,
        cap_percent=None,
        clause="6.3",
        start=None,
        end=date(2026, 3, 31),
    )
    assert isinstance(result, CalculationGap)
    assert result.amount is None


# =========================================================================
# Негативные проверки: испорченный документ не должен выйти как готовый
# =========================================================================


def test_hallucinated_law_is_blocked() -> None:
    """Статья, которой нет ни в source-bound VERIFIED, ни в корпусе."""
    draft = _claim(legal_basis=["Требование основано на статье 9999 ГК РК."])
    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False
    assert report.hard_blockers


def test_outdated_citation_text_is_blocked() -> None:
    """Номер статьи верен, но приведённый текст нормы не совпадает с источником."""
    stale = verified_claim_line(
        "Заказчик обязан оплатить работы в течение трёх банковских дней",
        "статья 623 ГК РК",
        ARTICLE_623,
        GK_SPECIAL_URL,
    )
    draft = _claim(
        legal_basis=["Заказчик обязан оплатить работы в течение трёх банковских дней. Правовое основание: статья 623 ГК РК."],
    )
    report = assess_document_quality("claim", CONTEXT, _research(stale), draft)

    assert report.ready is False


def test_non_applicable_citation_is_blocked() -> None:
    """Норма существует и подтверждена, но регулирует не то отношение."""
    verified = verified_claim_line(
        "Неустойкой признается определенная договором денежная сумма",
        "статья 293 ГК РК",
        ARTICLE_293,
        GK_GENERAL_URL,
    )
    draft = _claim(
        facts=["Ответчик не возвратил 2 300 000 тенге основного долга по договору займа."],
        legal_basis=[f"{ARTICLE_293} Правовое основание: статья 293 ГК РК."],
        requests=["Взыскать с ответчика 2 300 000 тенге основного долга."],
    )
    report = assess_document_quality("claim", CONTEXT, _research(verified), draft)

    assert report.ready is False


def test_hallucinated_identifier_is_blocked() -> None:
    """ИИН из материалов не должен потеряться и не должен подменяться другим."""
    draft = _claim(claimant=["Ахметов Руслан Маратович, ИИН 111111111111"])
    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False
    assert any("900101300123" in blocker for blocker in report.hard_blockers)


def test_wrong_party_direction_is_blocked() -> None:
    """Истец и ответчик не могут совпадать: роль стороны — не косметика."""
    same = ["ТОО «Компания», БИН 210987654321"]
    draft = _claim(claimant=same, defendant=list(same))
    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False


def test_placeholder_amount_never_ships_as_ready() -> None:
    draft = _claim(
        price_of_claim="[ТРЕБУЕТ УТОЧНЕНИЯ: цена иска]",
        state_duty="[ТРЕБУЕТ РАСЧЁТА ГОСПОШЛИНЫ]",
    )
    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False


def test_leaked_internal_reasoning_is_blocked() -> None:
    draft = _claim(facts=["KORGAN QUALITY 8.4/10: фактическая часть требует доработки."])
    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False
    assert any("служебная фраза" in blocker for blocker in report.hard_blockers)


@pytest.mark.parametrize(
    "leaked",
    [
        "NEEDS_VERIFICATION по статье 272 ГК РК.",
        "SENIOR_PREFLIGHT_SCORE: 7.2/10 — не достигнут порог.",
        "FILING_ACTION: указать банковские реквизиты истца.",
        "LEGAL_GROUNDING: акт не сверялся с официальным источником.",
    ],
)
def test_every_internal_marker_is_blocked_in_the_body(leaked: str) -> None:
    draft = _claim(facts=[leaked])
    report = assess_document_quality("claim", CONTEXT, _research(), draft)

    assert report.ready is False


def test_plaintiff_claim_never_carries_a_defendant_objection_section() -> None:
    """Прогноз возражений ответчика — внутренняя стратегия, не текст иска."""
    draft = _claim(
        anticipated_defenses=[
            "Ответчик может утверждать, что заём не передан — однако передача подтверждена платёжным поручением № 117.",
        ]
    )
    body = docx_text(build_claim_docx(draft))

    assert "Возражения ответчика" not in body
    assert "может утверждать" not in body
    assert "заём не передан" not in body


# --- претензия ------------------------------------------------------------


def _pretrial(**overrides) -> PretrialDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ДОСУДЕБНАЯ ПРЕТЕНЗИЯ",
        sender=["Ахметов Руслан Маратович, ИИН 900101300123"],
        recipient=['ТОО «Компания», БИН 210987654321'],
        facts=["Задолженность по договору № 12 от 15.01.2026 составляет 2 300 000 тенге."],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        demands=["Оплатить задолженность в размере 2 300 000 тенге."],
        deadline="10 календарных дней с даты получения настоящей претензии",
        consequences=["При неисполнении требований спор будет передан на разрешение суда."],
        attachments=["Копия договора № 12 от 15.01.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
        calculation=["Основной долг: 2 300 000 тенге; основание: договор № 12 от 15.01.2026."],
    )
    data.update(overrides)
    return PretrialDraft(**data)


def test_pretrial_scenario_is_ready_when_complete() -> None:
    report = assess_document_quality("pretrial", CONTEXT, _research(), _pretrial())
    assert report.ready is True, report.hard_blockers


def test_pretrial_money_demand_without_calculation_is_blocked() -> None:
    issues = pretrial_quality_issues(_pretrial(calculation=[]), _research())
    assert any("расчёт" in issue.lower() for issue in issues)


def test_pretrial_invented_deadline_is_blocked_when_absent() -> None:
    issues = pretrial_quality_issues(_pretrial(deadline=""), _research())
    assert any("срок" in issue.lower() for issue in issues)


# --- ответ на претензию ---------------------------------------------------


def _pretrial_response(**overrides) -> PretrialResponseDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ОТВЕТ НА ДОСУДЕБНУЮ ПРЕТЕНЗИЮ",
        sender=['ТОО «Компания», БИН 210987654321'],
        recipient=["Ахметов Руслан Маратович, ИИН 900101300123"],
        reference="претензия от 05.03.2026 № 7",
        claim_summary=["Заявлено требование об оплате 2 300 000 тенге."],
        admitted_circumstances=["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
        disputed_circumstances=["Оспаривается объём принятых работ по акту от 20.02.2026."],
        position=["Требование признаётся в части 1 400 000 тенге."],
        objections=["Работы на сумму 900 000 тенге не приняты: акт от 20.02.2026 подписан с замечаниями."],
        calculation_review=["Начисление произведено с 01.03.2026 при сроке оплаты 20.03.2026 по пункту 4.2 договора."],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        settlement_offer="",
        response_terms=["Признанная часть будет оплачена в согласованный сторонами срок."],
        attachments=["Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
    )
    data.update(overrides)
    return PretrialResponseDraft(**data)


def test_pretrial_response_scenario_is_ready_when_complete() -> None:
    report = assess_document_quality("pretrial_response", CONTEXT, _research(), _pretrial_response())
    assert report.ready is True, report.hard_blockers


def test_pretrial_response_template_disagreement_is_blocked() -> None:
    draft = _pretrial_response(
        position=["С требованиями не согласны."],
        objections=["Требования не признаём."],
        disputed_circumstances=[],
        calculation_review=[],
    )
    issues = pretrial_response_quality_issues(draft, _research())
    assert issues


# --- отзыв на иск ---------------------------------------------------------


def _response(**overrides) -> ResponseToClaimDraft:
    data = dict(
        status=VerificationStatus.VERIFIED,
        title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
        court="Медеуский районный суд города Алматы",
        case_number="дело № 2-1234/2026",
        claimant=["Ахметов Руслан Маратович, ИИН 900101300123"],
        defendant=['ТОО «Компания», БИН 210987654321'],
        claim_summary=["Истец просит взыскать 2 300 000 тенге."],
        admitted_circumstances=["Факт заключения договора № 12 от 15.01.2026 не оспаривается."],
        disputed_circumstances=["Оспаривается объём принятых работ по акту от 20.02.2026."],
        position=["Иск подлежит частичному удовлетворению в размере 1 400 000 тенге."],
        objections=["Работы на сумму 900 000 тенге не приняты: акт от 20.02.2026 подписан с замечаниями."],
        calculation_review=["Начисление произведено с 01.03.2026 при сроке оплаты 20.03.2026 по пункту 4.2 договора."],
        legal_basis=[f"{ARTICLE_272} Правовое основание: статья 272 ГК РК."],
        requests=["Отказать в удовлетворении исковых требований в части 900 000 тенге."],
        attachments=["Копия акта от 20.02.2026"],
        verification_notes=[],
        source_urls=[GK_GENERAL_URL],
    )
    data.update(overrides)
    return ResponseToClaimDraft(**data)


def test_response_scenario_is_ready_when_complete() -> None:
    report = assess_document_quality("response_to_claim", CONTEXT, _research(), _response())
    assert report.ready is True, report.hard_blockers


def test_response_limitation_objection_without_dates_is_blocked() -> None:
    draft = _response(objections=["Истёк срок исковой давности."])
    report = assess_document_quality("response_to_claim", CONTEXT, _research(), draft)

    assert report.ready is False
    assert any("без подтверждающих дат" in blocker for blocker in report.hard_blockers)


def test_response_procedural_objection_without_basis_is_blocked() -> None:
    draft = _response(objections=["Истцом нарушен процессуальный порядок подачи иска."])
    report = assess_document_quality("response_to_claim", CONTEXT, _research(), draft)

    assert report.ready is False


def test_response_limitation_objection_with_dates_is_allowed() -> None:
    draft = _response(
        objections=[
            "Срок исковой давности по требованию истёк 15.01.2026: течение началось 15.01.2023, "
            "срок составляет 3 года согласно статье 178 ГК РК.",
        ],
    )
    report = assess_document_quality("response_to_claim", CONTEXT, _research(), draft)

    assert not any("без подтверждающих дат" in blocker for blocker in report.hard_blockers)
