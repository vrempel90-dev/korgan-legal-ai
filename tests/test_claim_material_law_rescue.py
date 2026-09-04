from __future__ import annotations

from datetime import date

from korgan.claim_material_law_rescue import enrich_material_law_from_corpus
from korgan.legal.corpus import (
    ACT_GK_GENERAL,
    ACT_GK_SPECIAL,
    LegalCorpus,
)
from korgan.legal_types import LegalResearch, VerificationStatus


def _research(*, unverified: list[str] | None = None, verified: list[str] | None = None) -> LegalResearch:
    default_verified = [
        "Иск должен соответствовать форме. [основание: ст. 148 ГПК РК; текст нормы: «служебная форма»; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
    ]
    return LegalResearch(
        status=VerificationStatus.NEEDS_VERIFICATION,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=list(default_verified if verified is None else verified),
        unverified_claims=list(unverified or []),
        source_urls=["https://adilet.zan.kz/rus/docs/K1500000377"],
        notes=[],
    )


def _fresh_corpus() -> LegalCorpus:
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
    return corpus


def _install_corpus(monkeypatch, corpus: LegalCorpus) -> None:
    import korgan.claim_material_law_rescue as rescue

    monkeypatch.setattr(rescue, "local_corpus_enabled", lambda: True)
    monkeypatch.setattr(rescue, "open_corpus", lambda: corpus)


def test_supply_debt_prefers_specific_supply_law_over_generic_article_272(monkeypatch) -> None:
    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)

    research = _research()
    context = (
        "Договор поставки. Поставщик передал товар покупателю. Покупатель не оплатил задолженность 12 000 000 тенге. "
        "Требуем взыскать основной долг и договорную неустойку 996 000 тенге."
    )

    result = enrich_material_law_from_corpus(context, research)
    joined = "\n".join(result.verified_claims)

    assert "ст. 469" in joined
    assert "ст. 293" in joined
    assert "ст. 272" not in joined
    assert "https://adilet.zan.kz/rus/docs/K990000409_" in result.source_urls


def test_kazakh_supply_debt_prefers_specific_supply_law(monkeypatch) -> None:
    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)
    research = _research()
    context = (
        "Жеткізу шарты бойынша сатушы тауарды берді. Сатып алушының 12 000 000 теңге берешегі бар. "
        "Шарттың 6.3-тармағына сәйкес тұрақсыздық айыбын және негізгі қарызды өндіріп алуды сұраймын."
    )

    result = enrich_material_law_from_corpus(context, research)
    joined = "\n".join(result.verified_claims)

    assert "ст. 469" in joined
    assert "ст. 293" in joined
    assert "ст. 272" not in joined


def test_generic_contract_debt_still_gets_article_272_as_fallback(monkeypatch) -> None:
    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)
    research = _research()

    result = enrich_material_law_from_corpus(
        "Договор оказания услуг. Заказчик услуги принял, но задолженность 900 000 тенге не оплатил.",
        research,
    )
    joined = "\n".join(result.verified_claims)

    assert "ст. 272" in joined
    assert "ст. 469" not in joined


def test_existing_specific_consumer_law_prevents_generic_article_272(monkeypatch) -> None:
    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)
    research = _research(
        verified=[
            "Потребитель вправе требовать возврата денег. "
            "[основание: ст. 35 Закона РК «О защите прав потребителей»; "
            "текст нормы: «потребитель вправе предъявить требование»; "
            "источник: https://adilet.zan.kz/rus/docs/Z100000274_]"
        ]
    )

    result = enrich_material_law_from_corpus(
        "Договор с потребителем. Исполнитель не оказал услугу и не вернул задолженность 150 000 тенге.",
        research,
    )
    joined = "\n".join(result.verified_claims)

    assert "ст. 35 Закона" in joined
    assert "ст. 272" not in joined


def test_existing_penalty_specific_law_prevents_generic_article_293(monkeypatch) -> None:
    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)
    research = _research(
        verified=[
            "За просрочку предусмотрена законная неустойка. "
            "[основание: ст. 42 Закона РК «О специальной ответственности»; "
            "текст нормы: «за просрочку уплачивается неустойка»; "
            "источник: https://adilet.zan.kz/rus/docs/Z000000001_]"
        ]
    )

    result = enrich_material_law_from_corpus(
        "Договор услуг: долг 500 000 тенге и неустойка за просрочку по закону.",
        research,
    )
    joined = "\n".join(result.verified_claims)

    assert "ст. 42 Закона" in joined
    assert "ст. 293" not in joined


def test_employment_statutory_penalty_does_not_inject_civil_contract_penalty(monkeypatch) -> None:
    import korgan.claim_material_law_rescue as rescue

    monkeypatch.setattr(rescue, "local_corpus_enabled", lambda: True)
    opened = False

    def should_not_open():
        nonlocal opened
        opened = True
        return _fresh_corpus()

    monkeypatch.setattr(rescue, "open_corpus", should_not_open)
    research = _research()
    context = (
        "Трудовой договор. Работодатель имеет задолженность по заработной плате. "
        "Прошу взыскать заработную плату и предусмотренную законом пеню за задержку выплаты."
    )

    result = enrich_material_law_from_corpus(context, research)

    assert result.verified_claims == research.verified_claims
    assert not any("ст. 293" in line for line in result.verified_claims)
    assert opened is False


def test_disabled_local_corpus_leaves_research_unchanged(monkeypatch) -> None:
    import korgan.claim_material_law_rescue as rescue

    monkeypatch.setattr(rescue, "local_corpus_enabled", lambda: False)
    research = _research()
    before = list(research.verified_claims)

    result = enrich_material_law_from_corpus(
        "Договор поставки, долг и договорная неустойка.",
        research,
    )

    assert result.verified_claims == before
    assert result.status is VerificationStatus.NEEDS_VERIFICATION


def test_stale_snapshot_does_not_add_material_law(monkeypatch) -> None:
    import korgan.claim_material_law_rescue as rescue

    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)
    monkeypatch.setattr(rescue, "_snapshot_issue", lambda *args, **kwargs: "stale snapshot")
    research = _research()
    before = list(research.verified_claims)

    result = enrich_material_law_from_corpus(
        "Договор поставки: задолженность и договорная неустойка.",
        research,
    )

    assert result.verified_claims == before
    assert result.status is VerificationStatus.NEEDS_VERIFICATION


def test_unrelated_context_does_not_activate_claim_material_rescue(monkeypatch) -> None:
    import korgan.claim_material_law_rescue as rescue

    monkeypatch.setattr(rescue, "local_corpus_enabled", lambda: True)
    opened = False

    def should_not_open():
        nonlocal opened
        opened = True
        return _fresh_corpus()

    monkeypatch.setattr(rescue, "open_corpus", should_not_open)
    research = _research()
    before = list(research.verified_claims)

    result = enrich_material_law_from_corpus(
        "Подготовить ответ на обращение и проверить реквизиты документа без денежного требования.",
        research,
    )

    assert result.verified_claims == before
    assert opened is False


def test_unverified_claims_keep_needs_verification_after_successful_rescue(monkeypatch) -> None:
    corpus = _fresh_corpus()
    _install_corpus(monkeypatch, corpus)
    research = _research(unverified=["Не подтверждено дополнительное требование."])

    result = enrich_material_law_from_corpus(
        "Договор поставки: покупатель не оплатил задолженность 12 000 000 тенге.",
        research,
    )

    assert any("ст. 469" in line for line in result.verified_claims)
    assert result.status is VerificationStatus.NEEDS_VERIFICATION
