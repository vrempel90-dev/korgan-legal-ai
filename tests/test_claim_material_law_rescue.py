from __future__ import annotations

from datetime import date

from korgan.claim_material_law_rescue import enrich_material_law_from_corpus
from korgan.legal.corpus import (
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    LegalCorpus,
)
from korgan.legal_types import LegalResearch, VerificationStatus


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[
            "Иск должен соответствовать форме. [основание: ст. 148 ГПК РК; текст нормы: «служебная форма»; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
        ],
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
        notes=[],
    )


def test_supply_debt_gets_material_law_from_current_corpus(monkeypatch) -> None:
    corpus = LegalCorpus(":memory:")
    corpus.create_schema()
    today = date.today().isoformat()

    corpus.upsert_act(
        ACT_GK_GENERAL,
        "K940001000_",
        "Гражданский кодекс Республики Казахстан (Общая часть)",
        "https://adilet.zan.kz/rus/docs/K940001000_",
        today,
        today,
    )
    corpus.upsert_provision(
        act_id=ACT_GK_GENERAL,
        article_no="272",
        item_no=None,
        heading="Надлежащее исполнение обязательства",
        body=(
            "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства "
            "и требованиями законодательства."
        ),
        edition_date=today,
        url="https://adilet.zan.kz/rus/docs/K940001000_",
        sort_key=272,
    )
    corpus.upsert_provision(
        act_id=ACT_GK_GENERAL,
        article_no="293",
        item_no=None,
        heading="Понятие неустойки",
        body=(
            "Неустойкой (штрафом, пеней) признается определенная законодательством или договором денежная сумма, "
            "которую должник обязан уплатить кредитору в случае неисполнения или ненадлежащего исполнения обязательства, "
            "в частности в случае просрочки исполнения."
        ),
        edition_date=today,
        url="https://adilet.zan.kz/rus/docs/K940001000_",
        sort_key=293,
    )

    corpus.upsert_act(
        ACT_GK_SPECIAL,
        "K990000409_",
        "Гражданский кодекс Республики Казахстан (Особенная часть)",
        "https://adilet.zan.kz/rus/docs/K990000409_",
        today,
        today,
    )
    corpus.upsert_provision(
        act_id=ACT_GK_SPECIAL,
        article_no="469",
        item_no="3",
        heading="Расчеты за поставляемые товары",
        body=(
            "Если оплата товара осуществляется получателем и последний не произвел оплату товара в установленный договором срок, "
            "поставщик вправе потребовать оплаты поставленного товара от покупателя."
        ),
        edition_date=today,
        url="https://adilet.zan.kz/rus/docs/K990000409_",
        sort_key=46903,
    )

    import korgan.claim_material_law_rescue as rescue

    monkeypatch.setattr(rescue, "local_corpus_enabled", lambda: True)
    monkeypatch.setattr(rescue, "open_corpus", lambda: corpus)

    research = _research()
    context = (
        "Договор поставки. Поставщик передал товар покупателю. Покупатель не оплатил задолженность 12 000 000 тенге. "
        "Требуем взыскать основной долг и договорную неустойку 996 000 тенге."
    )

    result = enrich_material_law_from_corpus(context, research)
    joined = "\n".join(result.verified_claims)

    assert "ст. 272" in joined
    assert "ст. 469" in joined
    assert "ст. 293" in joined
    assert "https://adilet.zan.kz/rus/docs/K940001000_" in result.source_urls
    assert "https://adilet.zan.kz/rus/docs/K990000409_" in result.source_urls
