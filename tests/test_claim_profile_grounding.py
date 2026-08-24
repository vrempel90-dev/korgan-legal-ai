from korgan import claim_profile_grounding as grounding
from korgan.claim_profile_grounding import PROFILE_GROUNDING_PREFIX, ground_claim_profile_from_corpus
from korgan.legal.corpus import ACT_GK_GENERAL, ACT_GK_SPECIAL, LegalCorpus
from korgan.legal_types import LegalResearch, VerificationStatus


SUPPLY_CASE = """
Подготовить иск ТОО поставщика к ТОО покупателю по договору поставки.
Товар поставлен и не оплачен. Требуется взыскать основной долг и договорную
неустойку 0,1% за каждый день просрочки.
"""


def _research() -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=[],
        unverified_claims=[],
        source_urls=[],
        notes=[],
    )


def _corpus(*, include_payment: bool = True) -> LegalCorpus:
    corpus = LegalCorpus(":memory:")
    corpus.create_schema()
    corpus.upsert_act(
        ACT_GK_SPECIAL,
        "K990000409_",
        "Гражданский кодекс Республики Казахстан (Особенная часть)",
        "https://adilet.zan.kz/rus/docs/K990000409_",
        "2026-08-24",
        "2026-08-24",
    )
    corpus.upsert_act(
        ACT_GK_GENERAL,
        "K940001000_",
        "Гражданский кодекс Республики Казахстан (Общая часть)",
        "https://adilet.zan.kz/rus/docs/K940001000_",
        "2026-08-24",
        "2026-08-24",
    )
    corpus.upsert_provision(
        act_id=ACT_GK_SPECIAL,
        article_no="458",
        item_no=None,
        heading="Договор поставки",
        body=(
            "По договору поставки продавец (поставщик), являющийся предпринимателем, "
            "обязуется передать товары покупателю для использования в предпринимательской деятельности."
        ),
        edition_date="2026-08-24",
        url="https://adilet.zan.kz/rus/docs/K990000409_#z458",
        sort_key=458,
    )
    if include_payment:
        corpus.upsert_provision(
            act_id=ACT_GK_SPECIAL,
            article_no="469",
            item_no="1",
            heading="Расчеты за поставляемые товары",
            body=(
                "Покупатель оплачивает поставляемые товары с соблюдением порядка и формы расчетов, "
                "предусмотренных договором."
            ),
            edition_date="2026-08-24",
            url="https://adilet.zan.kz/rus/docs/K990000409_#z469",
            sort_key=469,
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
        edition_date="2026-08-24",
        url="https://adilet.zan.kz/rus/docs/K940001000_#z272",
        sort_key=272,
    )
    corpus.upsert_provision(
        act_id=ACT_GK_GENERAL,
        article_no="293",
        item_no=None,
        heading="Понятие неустойки",
        body=(
            "Неустойкой признается определенная законодательством или договором денежная сумма, "
            "которую должник обязан уплатить кредитору в случае неисполнения или ненадлежащего исполнения обязательства."
        ),
        edition_date="2026-08-24",
        url="https://adilet.zan.kz/rus/docs/K940001000_#z293",
        sort_key=293,
    )
    return corpus


def test_supply_profile_gets_exact_current_corpus_backbone(monkeypatch):
    corpus = _corpus()
    monkeypatch.setattr(grounding, "local_corpus_enabled", lambda: True)
    monkeypatch.setattr(grounding, "open_corpus", lambda: corpus)
    research = _research()

    result = ground_claim_profile_from_corpus(SUPPLY_CASE, research)

    joined = "\n".join(result.verified_claims)
    assert "ст. 458 ГК РК (Особенная часть)" in joined
    assert "ст. 469 ГК РК (Особенная часть), п. 1" in joined
    assert "ст. 272 ГК РК (Общая часть)" in joined
    assert "ст. 293 ГК РК (Общая часть)" in joined
    assert "https://adilet.zan.kz/rus/docs/K990000409_#z469" in joined
    assert not any(note.startswith(PROFILE_GROUNDING_PREFIX) for note in result.notes)
    assert result.status is VerificationStatus.VERIFIED


def test_supply_profile_fails_closed_when_required_payment_norm_missing(monkeypatch):
    corpus = _corpus(include_payment=False)
    monkeypatch.setattr(grounding, "local_corpus_enabled", lambda: True)
    monkeypatch.setattr(grounding, "open_corpus", lambda: corpus)
    research = _research()

    result = ground_claim_profile_from_corpus(SUPPLY_CASE, research)

    assert result.status is VerificationStatus.NEEDS_VERIFICATION
    assert any("GK_RK_OSOBENNAYA:469:1" in note for note in result.notes)
    assert any(note.startswith(PROFILE_GROUNDING_PREFIX) for note in result.unverified_claims)


def test_profile_grounding_does_not_duplicate_existing_same_article(monkeypatch):
    corpus = _corpus()
    monkeypatch.setattr(grounding, "local_corpus_enabled", lambda: True)
    monkeypatch.setattr(grounding, "open_corpus", lambda: corpus)
    research = _research()
    research.verified_claims.append(
        "Покупатель оплачивает поставляемые товары "
        "[основание: ст. 469 ГК РК (Особенная часть), п. 1; текст нормы: «Покупатель оплачивает поставляемые товары с соблюдением порядка и формы расчетов, предусмотренных договором.»; источник: https://adilet.zan.kz/rus/docs/K990000409_#z469]"
    )

    result = ground_claim_profile_from_corpus(SUPPLY_CASE, research)

    assert sum("ст. 469 ГК РК (Особенная часть), п. 1" in line for line in result.verified_claims) == 1
