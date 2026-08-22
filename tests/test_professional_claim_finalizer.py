from pathlib import Path

import pytest

from korgan.legal import pipeline
from korgan.legal.corpus import ACT_GK_SPECIAL, ACT_GPK, LegalCorpus
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.professional_claim_finalizer import finalize_professional_claim
from korgan.provision_check import verified_claim_line

GPK_URL = "https://adilet.zan.kz/rus/docs/K1500000377"
GK_SPECIAL_URL = "https://adilet.zan.kz/rus/docs/K990000409_"
ARTICLE_30_PART_9 = (
    "Иски о защите прав потребителей могут быть предъявлены по месту жительства истца "
    "либо по месту заключения или исполнения договора."
)
ARTICLE_627 = (
    "Если подрядчик не приступает своевременно к исполнению договора подряда или выполняет работу настолько медленно, "
    "что окончание ее к сроку становится явно невозможным, заказчик вправе отказаться от договора и потребовать возмещения убытков."
)


@pytest.fixture()
def grounded_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(path) as db:
        db.upsert_act(
            ACT_GPK,
            "K1500000377",
            "Гражданский процессуальный кодекс Республики Казахстан",
            GPK_URL,
            "2026-08-22",
            "2026-08-22",
        )
        db.upsert_act(
            ACT_GK_SPECIAL,
            "K990000409_",
            "Гражданский кодекс Республики Казахстан (Особенная часть)",
            GK_SPECIAL_URL,
            "2026-08-22",
            "2026-08-22",
        )
        db.upsert_provision(
            act_id=ACT_GPK,
            article_no="30",
            item_no="9",
            heading="Подсудность по выбору истца",
            body=ARTICLE_30_PART_9,
            edition_date="2026-08-22",
            url=GPK_URL,
            sort_key=30,
        )
        db.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="627",
            item_no=None,
            heading="Права заказчика во время выполнения работы подрядчиком",
            body=ARTICLE_627,
            edition_date="2026-08-22",
            url=GK_SPECIAL_URL,
            sort_key=627,
        )

    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    monkeypatch.setattr(pipeline, "DEFAULT_DB_PATH", path)
    return path


def _research() -> LegalResearch:
    venue = verified_claim_line(
        "Иски о защите прав потребителей могут быть предъявлены по месту жительства истца.",
        "часть 9 статьи 30 ГПК РК",
        ARTICLE_30_PART_9,
        GPK_URL,
    )
    substantive = verified_claim_line(
        "Заказчик вправе отказаться от договора подряда при нарушении подрядчиком сроков в предусмотренных законом случаях.",
        "статья 627 ГК РК",
        ARTICLE_627,
        GK_SPECIAL_URL,
    )
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[venue, substantive],
        unverified_claims=[],
        source_urls=[GPK_URL, GK_SPECIAL_URL],
        notes=["REMEDY: EXCLUDE | судебное расторжение | внесудебный отказ уже совершен"],
    )


def test_finalizer_turns_model_draft_into_fact_locked_filing_structure(grounded_corpus: Path):
    context = (
        "Истец: Ахметова Гульнара Сериковна, дата рождения 12.05.1988, ИИН 000000000001, "
        "адрес: г. Алматы, Медеуский район, ул. Абая, 150.\n"
        "Ответчик: ТОО «Компания», БИН 000000000002, адрес: г. Алматы, Алатауский район.\n"
        "Договор подряда на ремонт квартиры для личных бытовых нужд. "
        "Предоплата 2 300 000 тенге. Работы не выполнены. "
        "Истец направила письменное уведомление об отказе от договора и требует вернуть 2 300 000 тенге."
    )
    draft = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск о возврате предоплаты, компенсации морального вреда и судебных расходов",
        court="Суд общей юрисдикции города Алматы (уточнить)",
        claimant=["Ахметова Гульнара Сериковна, ИИН 000000000001, Медеуский район"],
        defendant=["ТОО «Компания», БИН 000000000002, Алатауский район"],
        price_of_claim="2 500 000 тенге",
        facts=[
            "Ответчик не выполнил работы и не возвратил 2 300 000 тенге.",
            "Истцу причинены переживания и моральные страдания из-за необходимости обращаться в суд.",
        ],
        legal_basis=["Гражданское законодательство регулирует договор подряда."],
        requests=[
            "Взыскать 2 300 000 тенге предоплаты.",
            "Взыскать компенсацию морального вреда 200 000 тенге.",
            "В порядке альтернативного требования расторгнуть договор и взыскать 2 300 000 тенге.",
            "Вызвать представителя ответчика в судебное заседание.",
        ],
        attachments=["Договор", "Банковская квитанция"],
        verification_notes=["Точное наименование суда требует уточнения."],
        source_urls=[],
    )

    research = _research()
    finalize_professional_claim(context, research, draft)

    assert draft.court == "Медеуский районный суд"
    assert any(note == "VERIFIED_COURT: Медеуский районный суд" for note in research.notes)
    assert all("мораль" not in item.lower() for item in [draft.title, *draft.facts, *draft.requests, *draft.legal_basis])
    assert all("расторг" not in item.lower() for item in draft.requests)
    assert all(not item.lower().startswith("вызвать") for item in draft.requests)
    assert draft.price_of_claim == "2 300 000 тенге"
    assert any("статья 627" in item.lower() for item in draft.legal_basis)
    assert not draft.verification_notes


def test_finalizer_does_not_invent_court_without_verified_venue_rule():
    context = (
        "Истец: Иванов Иван Иванович, ИИН 900101300001, адрес: г. Алматы, Медеуский район.\n"
        "Ответчик: Петров Петр Петрович, ИИН 900101300002, адрес: г. Алматы, Алатауский район."
    )
    research = LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=["Подсудность не подтверждена."],
        source_urls=[],
        notes=[],
    )
    draft = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="Иск",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: суд]",
        claimant=["Иванов Иван Иванович, ИИН 900101300001, Медеуский район"],
        defendant=["Петров Петр Петрович, ИИН 900101300002, Алатауский район"],
        price_of_claim="1 000 000 тенге",
        facts=["Факт 1"],
        legal_basis=[],
        requests=["Взыскать 1 000 000 тенге."],
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )

    finalize_professional_claim(context, research, draft)
    assert "ТРЕБУЕТ УТОЧНЕНИЯ" in draft.court
