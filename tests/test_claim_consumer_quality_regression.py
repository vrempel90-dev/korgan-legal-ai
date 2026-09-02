from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from korgan.claim_current_law_guard import prune_noncurrent_verified_claims
from korgan.claim_material_law_rescue import enrich_material_law_from_corpus
from korgan.legal import pipeline
from korgan.legal.corpus import ACT_CONSUMER, ACT_GK_GENERAL, ACT_GPK, LegalCorpus
from korgan.legal_calc import NEEDS_CALCULATION_MARKER
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim
from korgan.provision_check import verified_claim_line

GPK_URL = "https://adilet.zan.kz/rus/docs/K1500000377"
GK_URL = "https://adilet.zan.kz/rus/docs/K940001000_"
ZPP_URL = "https://adilet.zan.kz/rus/docs/Z100000274_"

VENUE = (
    "Иски о защите прав потребителей могут быть предъявлены по месту жительства истца "
    "либо по месту заключения или исполнения договора."
)
PROPER = (
    "Обязательство должно исполняться надлежащим образом в соответствии с условиями "
    "обязательства и требованиями законодательства."
)
DELAY = (
    "При нарушении исполнителем сроков выполнения работы потребитель вправе отказаться "
    "от договора и потребовать возмещения убытков."
)
DEFECTS = (
    "При обнаружении недостатков выполненной работы потребитель вправе потребовать "
    "безвозмездного устранения недостатков, соразмерного уменьшения цены либо в предусмотренных "
    "законом случаях расторжения договора."
)
PENALTY = (
    "За нарушение сроков начала и окончания выполнения работы исполнитель обязан уплатить "
    "потребителю неустойку в размере одного процента стоимости работы за каждый день просрочки."
)
MORAL = (
    "Моральный вред, причиненный потребителю вследствие нарушения его прав, подлежит компенсации."
)
PRETRIAL = (
    "На претензию потребителя исполнитель обязан представить мотивированный письменный ответ "
    "в течение десяти календарных дней со дня получения претензии."
)
CURRENT_DUTY = (
    "По искам о защите прав потребителей, поданным гражданами, суд производит отсрочку уплаты "
    "государственной пошлины до принятия соответствующего решения."
)


def _seed_current_corpus(path: Path) -> None:
    today = date.today().isoformat()
    with LegalCorpus(path) as db:
        for act_id, adilet_id, title, url in (
            (ACT_GK_GENERAL, "K940001000_", "Гражданский кодекс Республики Казахстан (Общая часть)", GK_URL),
            (ACT_GPK, "K1500000377", "Гражданский процессуальный кодекс Республики Казахстан", GPK_URL),
            (ACT_CONSUMER, "Z100000274_", "Закон Республики Казахстан «О защите прав потребителей»", ZPP_URL),
        ):
            db.upsert_act(act_id, adilet_id, title, url, today, today)

        db.upsert_provision(
            act_id=ACT_GK_GENERAL,
            article_no="272",
            item_no=None,
            heading="Надлежащее исполнение обязательства",
            body=PROPER,
            edition_date=today,
            url=GK_URL,
            sort_key=272,
        )
        db.upsert_provision(
            act_id=ACT_GPK,
            article_no="30",
            item_no="9",
            heading="Подсудность по выбору истца",
            body=VENUE,
            edition_date=today,
            url=GPK_URL,
            sort_key=3009,
        )
        db.upsert_provision(
            act_id=ACT_GPK,
            article_no="106",
            item_no="3",
            heading="Отсрочка уплаты государственной пошлины",
            body=CURRENT_DUTY,
            edition_date=today,
            url=GPK_URL,
            sort_key=10603,
        )
        db.upsert_provision(
            act_id=ACT_CONSUMER,
            article_no="34",
            item_no=None,
            heading="Последствия нарушения сроков выполнения работы",
            body=DELAY,
            edition_date=today,
            url=ZPP_URL,
            sort_key=34,
        )
        db.upsert_provision(
            act_id=ACT_CONSUMER,
            article_no="35",
            item_no="1",
            heading="Права потребителя при обнаружении недостатков выполненной работы",
            body=DEFECTS,
            edition_date=today,
            url=ZPP_URL,
            sort_key=3501,
        )
        db.upsert_provision(
            act_id=ACT_CONSUMER,
            article_no="35",
            item_no="5",
            heading="Неустойка за нарушение сроков выполнения работы",
            body=PENALTY,
            edition_date=today,
            url=ZPP_URL,
            sort_key=3505,
        )
        db.upsert_provision(
            act_id=ACT_CONSUMER,
            article_no="21",
            item_no=None,
            heading="Компенсация морального вреда",
            body=MORAL,
            edition_date=today,
            url=ZPP_URL,
            sort_key=21,
        )
        db.upsert_provision(
            act_id=ACT_CONSUMER,
            article_no="42-4",
            item_no=None,
            heading="Претензия потребителя",
            body=PRETRIAL,
            edition_date=today,
            url=ZPP_URL,
            sort_key=4204,
        )


@pytest.fixture()
def current_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "corpus.sqlite3"
    _seed_current_corpus(path)
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    return path


def _base_research(*, stale_duty: bool = False) -> LegalResearch:
    claims = [verified_claim_line(VENUE, "часть 9 статьи 30 ГПК РК", VENUE, GPK_URL)]
    if stale_duty:
        claims.append(
            verified_claim_line(
                "Суд предоставляет отсрочку государственной пошлины потребителю.",
                "статья 105-1 ГПК РК",
                "Суд предоставляет отсрочку государственной пошлины потребителю.",
                GPK_URL,
            )
        )
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=claims,
        unverified_claims=[],
        source_urls=[GPK_URL],
        notes=[],
    )


def _consumer_context(*, include_penalty: bool = True, include_moral: bool = True) -> str:
    extras: list[str] = []
    if include_penalty:
        extras.append("Определить основания для взыскания неустойки и рассчитать ее на дату подачи иска.")
    if include_moral:
        extras.append("Определить, имеются ли основания для компенсации морального вреда, не придумывая факты.")
    return (
        "Истец: Иванов Артём Сергеевич, дата рождения 15.05.1990, ИИН 900515300123, "
        "адрес: г. Алматы, Бостандыкский район, ул. Жарокова, дом 215, кв. 47.\n"
        "Ответчик: ТОО «СтройКомфорт KZ», БИН 230440012345, юридический адрес: г. Алматы, "
        "Алмалинский район, ул. Толе би, дом 101, офис 12.\n"
        "Физическое лицо заказало ремонт собственной квартиры для личных бытовых нужд, не связанных "
        "с предпринимательской деятельностью. Договор подряда стоимостью 1 500 000 тенге, аванс "
        "1 200 000 тенге. Срок окончания работ 30 апреля 2026 года нарушен, после 20 мая подрядчик "
        "прекратил работы. Имеются существенные недостатки: трещины, некачественная плитка и ламинат. "
        "Независимый специалист определил стоимость невыполненных либо некачественных работ 800 000 тенге, "
        "расходы на специалиста составили 50 000 тенге. Досудебная претензия направлена и получена, ответчик "
        "отказался вернуть деньги. Определить правильную подсудность и взыскать судебные расходы при наличии оснований. "
        + " ".join(extras)
    )


def _draft() -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Исковое заявление о взыскании денежных средств и убытков",
        court="Бостандыкский районный суд",
        claimant=[
            "Иванов Артём Сергеевич, дата рождения 15.05.1990, ИИН 900515300123, "
            "г. Алматы, Бостандыкский район, ул. Жарокова, дом 215, кв. 47"
        ],
        defendant=[
            "ТОО «СтройКомфорт KZ», БИН 230440012345, г. Алматы, Алмалинский район, "
            "ул. Толе би, дом 101, офис 12"
        ],
        price_of_claim="850 000 тенге",
        state_duty="Отсрочка по статье 105-1 ГПК РК",
        facts=["Ответчик нарушил срок и выполнил часть работ с недостатками."],
        legal_basis=["Отсрочка государственной пошлины предоставляется по статье 105-1 ГПК РК."],
        requests=[
            "Взыскать 800 000 тенге за невыполненные и ненадлежащим образом выполненные работы.",
            "Взыскать расходы на специалиста 50 000 тенге.",
            "Отсрочить уплату государственной пошлины по статье 105-1 ГПК РК.",
        ],
        attachments=["Договор", "Чеки Kaspi", "Заключение специалиста", "Досудебная претензия"],
        verification_notes=[],
        source_urls=[],
    )


def test_consumer_repair_rescue_adds_current_material_rules(current_corpus: Path) -> None:
    research = _base_research()
    result = enrich_material_law_from_corpus(_consumer_context(), research)
    joined = "\n".join(result.verified_claims)

    assert "ст. 272" in joined
    assert "ст. 34" in joined
    assert "ст. 35" in joined
    assert "п. 5" in joined
    assert "ст. 21" in joined
    assert "ст. 42-4" in joined
    assert ZPP_URL in result.source_urls


def test_fresh_current_law_guard_prunes_article_missing_from_official_snapshot(current_corpus: Path) -> None:
    research = _base_research(stale_duty=True)
    current = verified_claim_line(CURRENT_DUTY, "часть 3 статьи 106 ГПК РК", CURRENT_DUTY, GPK_URL)
    research.verified_claims.append(current)

    prune_noncurrent_verified_claims(research)
    joined = "\n".join(research.verified_claims)

    assert "105-1" not in joined
    assert "статьи 106" in joined
    assert any("CURRENT_LAW_PRUNED: GPK_RK:105-1" in note for note in research.notes)


def test_finalizer_never_silently_drops_requested_penalty_or_moral_review(current_corpus: Path) -> None:
    research = _base_research(stale_duty=True)
    draft = _draft()

    finalize_professional_claim(_consumer_context(), research, draft)

    filing_text = "\n".join([draft.state_duty, *draft.legal_basis, *draft.requests])
    assert "105-1" not in filing_text
    assert any("ст. 34" in item for item in draft.legal_basis)
    assert any("ст. 35" in item for item in draft.legal_basis)
    assert any("ст. 42-4" in item for item in draft.legal_basis)
    assert any("неустойк" in item.lower() and "ДАННЫЕ" in item for item in draft.requests)
    assert all("моральн" not in item.lower() for item in draft.requests)
    assert any("морального вреда" in note.lower() for note in draft.verification_notes)
    assert any("рассчитать неустойку" in note.lower() for note in draft.verification_notes)
    assert draft.price_of_claim.startswith("[ТРЕБУЕТ РАСЧЁТА")
    assert draft.state_duty == NEEDS_CALCULATION_MARKER
    assert draft.status is VerificationStatus.NEEDS_VERIFICATION


def test_finalizer_uses_current_consumer_state_duty_rule_when_money_is_complete(current_corpus: Path) -> None:
    research = _base_research(stale_duty=True)
    draft = _draft()
    context = _consumer_context(include_penalty=False, include_moral=False)

    finalize_professional_claim(context, research, draft)

    filing_text = "\n".join([draft.state_duty, *draft.legal_basis, *draft.requests])
    assert "105-1" not in filing_text
    assert "части 3 статьи 106 ГПК РК" in draft.state_duty
    # The ledger treats a specialist/expert expense as a cost, not as property
    # claim price, unless the prayer explicitly grounds it as damages.
    assert "800 000" in draft.price_of_claim
