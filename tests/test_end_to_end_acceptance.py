"""END-TO-END приёмка: два боевых дела от материалов до готового Word.

Документ собирается боевыми детерминированными слоями — расчётом, проверкой
ссылок, финалайзером, линтером и экспортёром Word. Место модели занимает
фиксированный черновик с ошибками: так проверяется не то, насколько удачно
модель угадала, а то, что её ошибки не доживают до документа.

Проверяет результат отдельный модуль ``tests/acceptance/independent_checks``,
который ничего из кода генерации не импортирует: у него свой разбор сумм, свой
разбор ссылок на нормы и свой расчёт неустойки по интервалам. Совпадение двух
независимо написанных реализаций и есть то, что подтверждает число; сверка
кода с самим собой не подтверждает ничего.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from korgan.article_lookup import source_hash
from korgan.claim_docx import build_claim_docx
from korgan.document_linter import LintStatus, lint_claim_document
from korgan.late_interest_hotfix import _apply_verified_penalty
from korgan.legal import pipeline
from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_GPK, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import apply_article_authority
from tests.acceptance.independent_checks import (
    Payment,
    amounts_in,
    check_cleanliness,
    citations_in,
    contradictory_motions,
    document_text,
    expected_penalty,
    expected_state_duty,
)

GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
GPK_URL = "https://adilet.zan.kz/rus/docs/K1500000377"
CHECKED_ON = date.today().isoformat()

ARTICLE_439 = (
    "Покупатель обязан оплатить товар непосредственно до или после передачи ему продавцом товара, "
    "если иное не предусмотрено законодательными актами или договором купли-продажи."
)
ARTICLE_293 = (
    "Неустойкой (штрафом, пеней) признается определенная законодательством или договором денежная сумма, "
    "которую должник обязан уплатить кредитору в случае неисполнения или ненадлежащего исполнения обязательства."
)
ARTICLE_GPK_27 = (
    "Специализированные межрайонные экономические суды рассматривают имущественные и неимущественные споры, "
    "сторонами которых являются юридические лица, индивидуальные предприниматели."
)


# --------------------------------------------------------------------------
# Два боевых дела
# --------------------------------------------------------------------------

CASE_A = {
    "id": "KAZ INDUSTRY TRADE",
    "context": """Файл: KAZ_INDUSTRY_TRADE_postavka.docx
Истец: ТОО «KAZ INDUSTRY TRADE», БИН 010140001230, г. Алматы, ул. Абая, 150, офис 12
Ответчик: ТОО «АлматыСтройСнаб», БИН 020240005675, г. Алматы, пр. Райымбека, 208
Договор поставки № 14/2026 от 02.02.2026. Стоимость поставки составила 8 750 000 тенге.
Товар поставлен в полном объёме 20.02.2026, накладная № 77 от 20.02.2026.
Срок оплаты по договору — до 10.03.2026 включительно.
07.04.2026 ответчик частично оплатил 2 000 000 тенге в счёт погашения задолженности.
Остаток основного долга составляет 6 750 000 тенге.
Пунктом 5.2 договора предусмотрена неустойка в размере 0,1% от суммы задолженности за каждый день просрочки.
Прошу взыскать основной долг и неустойку. Расчёт неустойки произвести по 01.09.2026 включительно.
""",
    "contract_value": 8_750_000,
    "payments": (Payment(date(2026, 4, 7), 2_000_000),),
    "rate": "0.1",
    "cap_amount": None,
    "start": date(2026, 3, 11),
    "end": date(2026, 9, 1),
    "principal": 6_750_000,
    "contract": "№ 14/2026 от 02.02.2026",
    "claimant": ["ТОО «KAZ INDUSTRY TRADE», БИН 010140001230, г. Алматы, ул. Абая, 150, офис 12"],
    "defendant": ["ТОО «АлматыСтройСнаб», БИН 020240005675, г. Алматы, пр. Райымбека, 208"],
}

CASE_B = {
    "id": "ASTANA SUPPLY GROUP",
    "context": """Файл: ASTANA_SUPPLY_GROUP_postavka.docx
Истец: ТОО «ASTANA SUPPLY GROUP», БИН 030340009019, г. Астана, ул. Кунаева, 12
Ответчик: ТОО «Сарыарка Логистик», БИН 040440003451, г. Астана, ул. Сейфуллина, 3
Договор поставки № 7 от 01.02.2026. Стоимость поставки составила 7 200 000 тенге.
Срок оплаты по договору — до 10.03.2026 включительно.
20.03.2026 ответчик частично оплатил 1 200 000 тенге в счёт погашения задолженности.
15.04.2026 ответчик частично оплатил 1 000 000 тенге в счёт погашения задолженности.
Остаток основного долга составляет 5 000 000 тенге.
Пунктом 6.3 договора предусмотрена неустойка в размере 0,1% от фактической просроченной задолженности за каждый день просрочки, но не более 10% первоначальной стоимости поставленного товара.
Прошу взыскать основной долг и неустойку. Расчёт неустойки произвести по 02.09.2026 включительно.
""",
    "contract_value": 7_200_000,
    "payments": (Payment(date(2026, 3, 20), 1_200_000), Payment(date(2026, 4, 15), 1_000_000)),
    "rate": "0.1",
    "cap_amount": 720_000,
    "start": date(2026, 3, 11),
    "end": date(2026, 9, 2),
    "principal": 5_000_000,
    "contract": "№ 7 от 01.02.2026",
    "claimant": ["ТОО «ASTANA SUPPLY GROUP», БИН 030340009019, г. Астана, ул. Кунаева, 12"],
    "defendant": ["ТОО «Сарыарка Логистик», БИН 040440003451, г. Астана, ул. Сейфуллина, 3"],
}

CASES = [pytest.param(CASE_A, id="kaz-industry-trade"), pytest.param(CASE_B, id="astana-supply-group")]


@pytest.fixture(scope="function")
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Корпус НПА с нормами, которые реально нужны иску о поставке."""
    path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(path) as db:
        db.upsert_act(ACT_GK_SPECIAL, "K990000409_", "ГК РК (Особенная часть)", GK_SPECIAL_URL, CHECKED_ON, CHECKED_ON)
        db.upsert_act(ACT_GPK, "K1500000377", "ГПК РК", GPK_URL, CHECKED_ON, CHECKED_ON)
        for act, article, heading, body, url in (
            (ACT_GK_SPECIAL, "439", "Оплата товара", ARTICLE_439, GK_SPECIAL_URL),
            (ACT_GK_SPECIAL, "293", "Понятие неустойки", ARTICLE_293, GK_SPECIAL_URL),
            (ACT_GPK, "27", "Подсудность дел экономическим судам", ARTICLE_GPK_27, GPK_URL),
        ):
            db.upsert_provision(
                act_id=act, article_no=article, item_no=None, heading=heading, body=body,
                edition_date=CHECKED_ON, url=url, sort_key=int(article),
            )
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    return path


def _model_output(case: dict) -> ClaimDraft:
    """Черновик в том виде, в каком его отдаёт модель.

    Числа неверные, ссылка на статью 180 ГК РК не подтверждена, в фактах —
    служебная заметка, а в ходатайствах — просьба истребовать у истца документ,
    который истец сам приложил. Каждая из этих ошибок встречалась в боевых
    документах.
    """
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании задолженности по договору поставки",
        court="Специализированный межрайонный экономический суд",
        claimant=list(case["claimant"]),
        defendant=list(case["defendant"]),
        price_of_claim="9 999 999 тенге",
        facts=[
            "Товар поставлен в полном объёме, оплата в установленный срок не произведена.",
            "Ответчик признал задолженность частичной оплатой.",
        ],
        legal_basis=[
            "На основании статьи 439 ГК РК покупатель обязан оплатить товар непосредственно "
            "до или после передачи ему продавцом товара.",
            "В соответствии со ст. 178, 180 ГК РК срок исковой давности составляет три года.",
        ],
        requests=[
            "Взыскать с ответчика основной долг в размере 8 000 000 тенге.",
            "Взыскать с ответчика неустойку в размере 1 500 000 тенге.",
            "Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины.",
        ],
        attachments=[
            f"Копия договора поставки {case['contract']}",
            "Копия накладной о поставке товара",
        ],
        motions=[f"Истребовать у истца договор поставки {case['contract']}."],
        jurisdiction_reason=(
            "Родовая подсудность определена статьёй 27 ГПК РК: спор между юридическими лицами "
            "рассматривает специализированный межрайонный экономический суд."
        ),
        verification_notes=[],
        source_urls=[GK_SPECIAL_URL],
    )


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[GK_SPECIAL_URL],
        notes=[],
    )


def _produce(case: dict) -> tuple[ClaimDraft, bytes, object]:
    """Провести дело через боевые слои и получить настоящий Word."""
    draft = _model_output(case)

    # Фаза 1: числа берёт детерминированный расчёт.
    _apply_verified_penalty(case["context"], _research(), draft, filing_date=case["end"])
    # Фаза 2: номера статей — только подтверждённые.
    apply_article_authority(draft)
    # Ходатайство против собственных приложений линтер обязан увидеть.
    lint = lint_claim_document(draft, case_context=case["context"])
    payload = build_claim_docx(draft)
    return draft, payload, lint


@pytest.fixture()
def produced(request, corpus):
    return _produce(request.param)


# ==========================================================================
# A. Числа
# ==========================================================================


@pytest.mark.parametrize("case", CASES)
def test_a_numbers_match_an_independent_calculation(case, corpus) -> None:
    draft, payload, _ = _produce(case)
    text = document_text(payload)

    penalty = expected_penalty(
        contract_value=case["contract_value"],
        payments=case["payments"],
        rate_percent_per_day=case["rate"],
        start=case["start"],
        end=case["end"],
        cap_amount=case["cap_amount"],
    )
    claim_price = case["principal"] + penalty.total
    duty = expected_state_duty(claim_price, legal_entity=True)
    total = claim_price + duty

    result = draft.calculation_result
    assert result["principal"]["value"] == case["principal"]
    assert result["penalty"]["value"] == penalty.total
    assert result["claim_price"]["value"] == claim_price
    assert result["state_duty"]["value"] == duty
    assert result["total_claim"]["value"] == total

    # Те же числа обязаны стоять в самом документе.
    printed = set(amounts_in(text))
    for expected in (case["principal"], penalty.total, claim_price, duty, total):
        assert expected in printed, f"{expected} отсутствует в документе"


@pytest.mark.parametrize("case", CASES)
def test_a_partial_payments_shape_the_penalty_periods(case, corpus) -> None:
    """Периоды и базы каждого интервала совпадают с независимым расчётом."""
    draft, _, _ = _produce(case)
    penalty = expected_penalty(
        contract_value=case["contract_value"],
        payments=case["payments"],
        rate_percent_per_day=case["rate"],
        start=case["start"],
        end=case["end"],
        cap_amount=case["cap_amount"],
    )

    breakdown = "\n".join(draft.calculation_result["penalty"]["breakdown"])
    for period_from, period_to, days, balance, subtotal in penalty.intervals:
        assert f"{period_from:%d.%m.%Y}—{period_to:%d.%m.%Y}" in breakdown
        assert f"{days} дн." in breakdown
        assert f"{balance:,}".replace(",", " ") in breakdown
        assert f"{subtotal:,}".replace(",", " ") in breakdown


@pytest.mark.parametrize("case", CASES)
def test_a_model_written_amounts_are_gone(case, corpus) -> None:
    _, payload, _ = _produce(case)
    text = document_text(payload)

    for invented in ("9 999 999", "8 000 000", "1 500 000"):
        assert invented not in text, f"число модели {invented} осталось в документе"


@pytest.mark.parametrize("case", CASES)
def test_a_sections_agree_on_every_amount(case, corpus) -> None:
    """Описательная, расчётная и просительная части говорят одно число."""
    draft, payload, _ = _produce(case)
    penalty = expected_penalty(
        contract_value=case["contract_value"], payments=case["payments"],
        rate_percent_per_day=case["rate"], start=case["start"], end=case["end"],
        cap_amount=case["cap_amount"],
    )
    claim_price = case["principal"] + penalty.total

    header = amounts_in(draft.price_of_claim)
    calculation = amounts_in("\n".join(draft.calculation))
    prayer = amounts_in("\n".join(draft.requests))

    assert header == [claim_price]
    assert claim_price in calculation
    assert case["principal"] in prayer and penalty.total in prayer
    assert claim_price in prayer or claim_price in calculation


def test_a_contractual_cap_is_applied_only_where_the_contract_sets_one(corpus) -> None:
    draft_a, _, _ = _produce(CASE_A)
    draft_b, _, _ = _produce(CASE_B)

    penalty_b = expected_penalty(
        contract_value=CASE_B["contract_value"], payments=CASE_B["payments"],
        rate_percent_per_day=CASE_B["rate"], start=CASE_B["start"], end=CASE_B["end"],
        cap_amount=CASE_B["cap_amount"],
    )
    assert penalty_b.capped is True
    assert penalty_b.raw_total > penalty_b.total
    assert draft_b.calculation_result["penalty"]["value"] == CASE_B["cap_amount"]

    penalty_a = expected_penalty(
        contract_value=CASE_A["contract_value"], payments=CASE_A["payments"],
        rate_percent_per_day=CASE_A["rate"], start=CASE_A["start"], end=CASE_A["end"],
    )
    assert penalty_a.capped is False
    assert draft_a.calculation_result["penalty"]["value"] == penalty_a.raw_total


# ==========================================================================
# B. Право
# ==========================================================================


@pytest.mark.parametrize("case", CASES)
def test_b_every_printed_article_has_a_verified_lookup(case, corpus) -> None:
    draft, payload, _ = _produce(case)
    printed = citations_in(document_text(payload))
    trace = {
        (str(row["code"]), str(row["article"]))
        for row in draft.citation_authority["traceability"]
    }

    assert printed, "в документе не осталось ни одной ссылки на норму — проверять нечего"
    unverified = [item for item in printed if item not in trace]
    assert unverified == [], f"непроверенные ссылки: {unverified}"


@pytest.mark.parametrize("case", CASES)
def test_b_every_traced_article_carries_a_source_hash(case, corpus) -> None:
    draft, _, _ = _produce(case)

    for row in draft.citation_authority["traceability"]:
        assert row["source_hash"], f"нет source_hash у {row['reference']}"
        assert row["source_url"]
        assert row["edition_date"]


def test_b_source_hash_matches_the_corpus_text(corpus) -> None:
    """Отпечаток берётся от текста нормы, а не от её номера."""
    draft, _, _ = _produce(CASE_A)

    by_article = {row["article"]: row for row in draft.citation_authority["traceability"]}
    # Заголовок статьи входит в норму наравне с телом: без него текст статьи 27
    # ГПК РК не содержит слова «подсудность», и пересказ раздела о подсудности
    # объявлялся дрейфом.
    assert by_article["439"]["source_hash"] == source_hash(f"Оплата товара. {ARTICLE_439}")


@pytest.mark.parametrize("case", CASES)
def test_b_unverified_article_180_never_reaches_the_document(case, corpus) -> None:
    """Модель писала «ст. 178, 180 ГК РК»; в корпусе нет ни одной из них."""
    _, payload, _ = _produce(case)
    printed = citations_in(document_text(payload))

    assert ("ГК РК", "180") not in printed
    assert ("ГК РК", "178") not in printed


# ==========================================================================
# C. Чистота документа
# ==========================================================================


@pytest.mark.parametrize("case", CASES)
def test_c_document_carries_no_internal_traces(case, corpus) -> None:
    _, payload, _ = _produce(case)

    report = check_cleanliness(payload)

    assert report.clean, f"служебные следы в документе: {report.traces[:5]}"


@pytest.mark.parametrize("case", CASES)
def test_c_lawyer_notes_exist_but_stay_out_of_the_document(case, corpus) -> None:
    """Внутренние сообщения не исчезают — они просто не в судебном тексте."""
    draft, payload, _ = _produce(case)
    text = document_text(payload)

    for note in draft.verification_notes:
        assert note not in text


# ==========================================================================
# D. Структура
# ==========================================================================


@pytest.mark.parametrize("case", CASES)
def test_d_contradictory_motion_is_caught(case, corpus) -> None:
    """Ходатайство истребовать у истца его же приложение обязано быть замечено."""
    _, payload, lint = _produce(case)

    assert contradictory_motions(payload), "независимая проверка не нашла противоречия"
    assert lint.status is LintStatus.BLOCKED
    assert any(
        finding.rule == "motion_requests_claimant_own_attachment" for finding in lint.findings
    )


@pytest.mark.parametrize("case", CASES)
def test_d_prayer_states_the_total_amount(case, corpus) -> None:
    draft, _, _ = _produce(case)
    prayer = "\n".join(draft.requests)

    assert "Общая сумма ко взысканию" in prayer
    assert draft.calculation_result["total_claim"]["value"] in amounts_in(prayer)


@pytest.mark.parametrize("case", CASES)
def test_d_a_document_without_the_bad_motion_passes_the_gate(case, corpus) -> None:
    """Убрав единственное противоречие, документ обязан пройти гейт целиком."""
    draft, _, _ = _produce(case)
    draft.motions = []

    result = lint_claim_document(draft, case_context=case["context"])

    assert result.status is LintStatus.PASS, result.summary()


# ==========================================================================
# E. STYLE_GUIDE
# ==========================================================================


@pytest.mark.parametrize("case", CASES)
def test_e_style_guide_rules_pass_on_the_produced_document(case, corpus) -> None:
    draft, _, _ = _produce(case)
    draft.motions = []

    result = lint_claim_document(draft, case_context=case["context"])
    style_findings = [
        finding for finding in result.findings if finding.rule.startswith("style_guide:")
    ]

    assert style_findings == [], f"нарушения оформления: {[f.message for f in style_findings]}"


@pytest.mark.parametrize("case", CASES)
def test_e_court_costs_are_a_separate_request(case, corpus) -> None:
    draft, _, _ = _produce(case)
    cost_requests = [
        request for request in draft.requests
        if "государственной пошлины" in request.lower() and "долг" not in request.lower()
    ]

    assert cost_requests


@pytest.mark.parametrize("case", CASES)
def test_e_party_requisites_come_from_the_case_materials(case, corpus) -> None:
    draft, _, _ = _produce(case)
    context = case["context"]

    for line in draft.claimant + draft.defendant:
        for number in [token for token in line.split() if token.isdigit() and len(token) == 12]:
            assert number in context
