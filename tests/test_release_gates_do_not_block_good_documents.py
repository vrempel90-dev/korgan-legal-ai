"""Корректно составленный документ обязан выпускаться.

Эти тесты закрывают три дефекта, из-за которых профессионально составленный
документ не доходил до пользователя вообще:

1. Гейт цитат искал нормы только в `provisions.json` (одна запись) и не знал
   про загруженный с adilet корпус на 5 627 положений. Любая статья получала
   вердикт UNVERIFIABLE, а он блокирующий.
2. Проверка дрейфа пересказа считала «требованием, которого нет в норме»
   любое слово из фактической части — «срок», «отказ», «возврат». То есть
   ровно за связь нормы с обстоятельствами дела, которой профессиональный
   документ и отличается от набора цитат.
3. Гейт неустойки требовал, чтобы слово «неустойка» и сумма стояли в
   шестнадцати символах друг от друга. Черновое «неустойку 112 000 тенге»
   проходило, профессиональное «неустойку за нарушение срока сдачи работ в
   размере 112 000 (сто двенадцать тысяч) тенге» — нет.
"""

from __future__ import annotations

import pytest

from korgan.claim_consistency_guard import _has_complete_penalty_calculation
from korgan.legal.corpus import LegalCorpus
from korgan.provision_check import paraphrase_defects


# ---------------------------------------------------------------------------
# 1. Мост между гейтом цитат и загруженным корпусом
# ---------------------------------------------------------------------------

_ARTICLE_620 = (
    "Если подрядчик не приступает своевременно к исполнению договора или выполняет работу "
    "настолько медленно, что окончание ее к сроку становится явно невозможным, заказчик вправе "
    "отказаться от договора и потребовать возмещения убытков."
)


@pytest.fixture()
def corpus_with_620(tmp_path, monkeypatch):
    """Корпус с одной нормой — как загруженный с adilet, только маленький."""
    db_path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(db_path) as corpus:
        corpus.create_schema()
        corpus.upsert_act(
            act_id="GK_RK_OSOBENNAYA",
            adilet_id="K990000409_",
            title_ru="Гражданский кодекс Республики Казахстан (Особенная часть)",
            url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="2026-07-01",
            loaded_at="2026-08-28",
        )
        corpus.upsert_provision(
            act_id="GK_RK_OSOBENNAYA",
            article_no="620",
            item_no=None,
            heading="Сроки выполнения работы",
            body=_ARTICLE_620,
            edition_date="2026-07-01",
            url="https://adilet.zan.kz/rus/docs/K990000409_",
            sort_key=1,
        )

    from korgan.legal import pipeline as legal_pipeline
    from korgan import corpus_bridge

    monkeypatch.setattr(legal_pipeline, "open_corpus", lambda path=None: LegalCorpus(db_path))
    corpus_bridge.reset_cache()
    yield
    corpus_bridge.reset_cache()


def test_article_from_loaded_corpus_is_verifiable(corpus_with_620):
    """Статья из SQLite-корпуса больше не считается неподтверждённой."""
    from korgan.provision_corpus import lookup

    record = lookup("ГК РК", "620")
    assert record is not None
    assert record.citable_verbatim, "норма прочитана с официального источника — её можно цитировать"
    assert "adilet.zan.kz" in record.source_url


def test_missing_article_is_still_unverifiable(corpus_with_620):
    """Мост не должен подтверждать то, чего в корпусе нет."""
    from korgan.provision_corpus import lookup

    assert lookup("ГК РК", "99999") is None


def test_citation_audit_accepts_a_corpus_backed_paraphrase(corpus_with_620):
    from korgan.citation_audit import audit_citations

    text = (
        "Заказчик вправе отказаться от договора и потребовать возмещения убытков, если подрядчик "
        "выполняет работу настолько медленно, что окончание её к сроку становится явно невозможным, "
        "— статья 620 ГК РК."
    )
    audit = audit_citations(text, verified_claims=[])
    assert audit.blocking == [], [f.detail for f in audit.blocking]


def test_absent_corpus_does_not_crash_the_gate(monkeypatch):
    """Отсутствие корпуса — не ошибка: гейт просто работает без него."""
    from korgan.legal import pipeline as legal_pipeline
    from korgan import corpus_bridge

    monkeypatch.setattr(legal_pipeline, "open_corpus", lambda path=None: None)
    corpus_bridge.reset_cache()
    try:
        assert corpus_bridge.lookup_in_local_corpus("ГК РК", "620") is None
    finally:
        corpus_bridge.reset_cache()


# ---------------------------------------------------------------------------
# 2. Дрейф пересказа не должен срабатывать на применении нормы к делу
# ---------------------------------------------------------------------------


def test_applying_a_norm_to_the_facts_is_not_drift():
    """Связь нормы с обстоятельством — признак качества, а не дефект."""
    statement = (
        "Заказчик вправе отказаться от договора, если подрядчик выполняет работу настолько медленно, "
        "что окончание её к сроку становится явно невозможным. Ответчик прекратил исполнение с "
        "середины апреля 2026 года и не сдал результат работ в установленный срок (обстоятельство 4)."
    )
    assert paraphrase_defects(statement, _ARTICLE_620) == []


def test_invented_requirement_is_still_caught():
    """Ослабление не должно пропускать выдуманное требование закона."""
    statement = (
        "Норма требует обязательной нотариальной формы договора подряда и уплаты государственной пошлины."
    )
    defects = paraphrase_defects(statement, _ARTICLE_620)
    assert any("нотариальная форма" in defect for defect in defects)


def test_fact_sentence_alone_still_gets_checked():
    """Если утверждение состоит только из фактов, проверка не исчезает."""
    statement = "Ответчик обязан уплатить неустойку по решению суда (обстоятельство 6)."
    assert paraphrase_defects(statement, _ARTICLE_620)


# ---------------------------------------------------------------------------
# 3. Гейт неустойки и профессиональная формулировка
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    [
        "Взыскать с ответчика неустойку за нарушение срока сдачи работ в размере 112 000 (сто двенадцать тысяч) тенге.",
        "Взыскать неустойку 112 000 тенге.",
        "Взыскать пеню в сумме 45 000 тенге.",
        "Взыскать неустойку: 1% от 1 200 000 тенге за 10 дней просрочки.",
    ],
)
def test_penalty_amount_is_recognised(request_text):
    assert _has_complete_penalty_calculation(request_text), request_text


@pytest.mark.parametrize(
    "request_text",
    [
        "Взыскать неустойку, исходя из суммы договора 1 200 000 тенге.",
        "Взыскать неустойку по договору.",
        "Взыскать неустойку в размере, определяемом судом.",
    ],
)
def test_penalty_without_its_own_amount_is_still_blocked(request_text):
    """База начисления и обещание «суд определит» — не размер неустойки."""
    assert not _has_complete_penalty_calculation(request_text), request_text


# ---------------------------------------------------------------------------
# 4. Скорость: составление документа не должно уходить на второй круг
# ---------------------------------------------------------------------------


def test_draft_effort_is_tuned_for_one_to_two_minutes():
    from korgan.pro_document_quality import DEFAULT_DRAFT_EFFORT, reasoning_for

    assert DEFAULT_DRAFT_EFFORT == "low"
    assert reasoning_for("korgan_fast_professional_claim", "gpt-5.1") == {"effort": "low"}
    # Служебные вызовы по-прежнему без рассуждения — там оно ничего не даёт.
    assert reasoning_for("korgan_verified_legal_research", "gpt-5.1") == {"effort": "none"}


# ---------------------------------------------------------------------------
# 5. Корпус должен переживать перезапуск контейнера
# ---------------------------------------------------------------------------


def test_corpus_path_is_configurable(monkeypatch, tmp_path):
    """Корпус можно положить на постоянный том вместо эфемерного контейнера.

    Без этого каждый рестарт собирал корпус с adilet заново, и неудачная
    загрузка оставляла сервис вообще без норм — а значит без документов.
    """
    import importlib

    monkeypatch.setenv("KORGAN_CORPUS_DB", str(tmp_path / "persistent" / "corpus.sqlite3"))
    module = importlib.reload(importlib.import_module("korgan.legal.corpus"))
    try:
        assert module.DEFAULT_DB_PATH == tmp_path / "persistent" / "corpus.sqlite3"
        # Каталог тома может быть пустым: корпус обязан создать его сам.
        with module.LegalCorpus(module.DEFAULT_DB_PATH) as corpus:
            corpus.create_schema()
            assert corpus.count() == 0
        assert module.DEFAULT_DB_PATH.exists()
    finally:
        monkeypatch.delenv("KORGAN_CORPUS_DB", raising=False)
        importlib.reload(module)


def test_corpus_path_defaults_to_the_repository_location(monkeypatch):
    import importlib

    monkeypatch.delenv("KORGAN_CORPUS_DB", raising=False)
    module = importlib.reload(importlib.import_module("korgan.legal.corpus"))
    assert module.DEFAULT_DB_PATH.name == "corpus.sqlite3"
    assert module.DEFAULT_DB_PATH.parent.name == "data"


def test_tls_context_uses_a_full_root_store_without_weakening_verification():
    """Корпус не должен падать из-за нехватки корней в системном хранилище.

    В логах прода это выглядело как CERTIFICATE_VERIFY_FAILED на adilet и
    заканчивалось тем, что норм нет вообще, а значит нет и документов.
    """
    from korgan.legal.corpus_refresh import _trusted_context
    import ssl

    context = _trusted_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert len(context.get_ca_certs()) > 50


# ---------------------------------------------------------------------------
# 6. Частичная загрузка корпуса лучше, чем никакой
# ---------------------------------------------------------------------------


def _fake_loader(good_acts, provisions_per_act=10):
    """Загрузчик, который умеет только перечисленные акты."""

    def loader(corpus, act_id):
        if act_id not in good_acts:
            raise RuntimeError(f"Both official sources failed for {act_id}")
        corpus.upsert_act(
            act_id=act_id,
            adilet_id="X",
            title_ru=act_id,
            url=f"https://adilet.zan.kz/rus/docs/{act_id}",
            edition_date="2026-07-01",
            loaded_at="2026-08-28",
        )
        for n in range(provisions_per_act):
            corpus.upsert_provision(
                act_id=act_id,
                article_no=str(100 + n),
                item_no=None,
                heading="h",
                body="Текст нормы достаточной длины для проверки целостности корпуса и цитат.",
                edition_date="2026-07-01",
                url=f"https://adilet.zan.kz/rus/docs/{act_id}",
                sort_key=n,
            )
        return provisions_per_act, "adilet", f"https://adilet.zan.kz/rus/docs/{act_id}"

    return loader


def test_partial_refresh_is_published_instead_of_nothing(monkeypatch, tmp_path):
    """Один недоступный акт не должен оставлять сервис вообще без норм."""
    from korgan.legal import corpus_refresh as refresh
    from korgan.legal.corpus import KNOWN_ACTS, LegalCorpus

    good = sorted(KNOWN_ACTS)[:-1]
    monkeypatch.setattr(refresh, "_load_from_official_sources", _fake_loader(set(good)))

    target = tmp_path / "corpus.sqlite3"
    total = refresh.refresh_corpus_once(target)

    assert total == 10 * len(good)
    with LegalCorpus(target) as corpus:
        assert corpus.count() == total


def test_complete_failure_keeps_the_existing_corpus(monkeypatch, tmp_path):
    from korgan.legal import corpus_refresh as refresh
    from korgan.legal.corpus import KNOWN_ACTS, LegalCorpus

    target = tmp_path / "corpus.sqlite3"
    monkeypatch.setattr(refresh, "_load_from_official_sources", _fake_loader(set(KNOWN_ACTS)))
    refresh.refresh_corpus_once(target)
    before = LegalCorpus(target).count()

    monkeypatch.setattr(refresh, "_load_from_official_sources", _fake_loader(set()))
    with pytest.raises(RuntimeError):
        refresh.refresh_corpus_once(target)

    with LegalCorpus(target) as corpus:
        assert corpus.count() == before, "неудачная сверка не должна обнулять корпус"


def test_partial_refresh_never_replaces_a_richer_corpus(monkeypatch, tmp_path):
    """Полный корпус нельзя обменивать на урезанный."""
    from korgan.legal import corpus_refresh as refresh
    from korgan.legal.corpus import KNOWN_ACTS, LegalCorpus

    target = tmp_path / "corpus.sqlite3"
    monkeypatch.setattr(refresh, "_load_from_official_sources", _fake_loader(set(KNOWN_ACTS)))
    refresh.refresh_corpus_once(target)
    before = LegalCorpus(target).count()

    monkeypatch.setattr(refresh, "_load_from_official_sources", _fake_loader({sorted(KNOWN_ACTS)[0]}))
    with pytest.raises(RuntimeError):
        refresh.refresh_corpus_once(target)

    with LegalCorpus(target) as corpus:
        assert corpus.count() == before


# ---------------------------------------------------------------------------
# 7. Преамбула договора: оборот речи не должен решать судьбу документа
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preamble",
    [
        # «в дальнейшем» — формулировка из шаблона KORGAN
        "ТОО «Астана Диджитал», БИН 190240012345, в лице директора, действующего на основании "
        "устава, именуемое в дальнейшем «Заказчик», с одной стороны, и ИП Ким А.В., ИИН 880712300456, "
        "действующий на основании свидетельства, именуемый в дальнейшем «Исполнитель», с другой "
        "стороны, заключили настоящий договор о нижеследующем.",
        # «далее» — столь же принятая формулировка, раньше блокировалась
        "ТОО «Астана Диджитал», БИН 190240012345, в лице директора, действующего на основании "
        "устава, именуемое далее Заказчик, с одной стороны, и ИП Ким А.В., ИИН 880712300456, "
        "действующий на основании свидетельства, именуемый далее Исполнитель, с другой стороны, "
        "заключили настоящий договор о нижеследующем.",
    ],
)
def test_both_role_designations_are_accepted(preamble):
    from korgan.contract_preamble import preamble_defects

    assert preamble_defects([preamble]) == []


def test_contract_between_two_individuals_is_not_blocked():
    """Гражданин подписывает договор сам: у него нет «в лице» и «на основании».

    Требовать эти обороты от договора аренды квартиры, займа или продажи
    автомобиля между физическими лицами — значит блокировать целую категорию
    договоров за отсутствие того, чего в них не бывает.
    """
    from korgan.contract_preamble import preamble_defects

    preamble = (
        "Иванов Иван Иванович, ИИН 800101300111, именуемый далее Арендодатель, с одной стороны, "
        "и Петров Пётр Петрович, ИИН 850202300222, именуемый далее Арендатор, с другой стороны, "
        "заключили настоящий договор о нижеследующем."
    )
    assert preamble_defects([preamble]) == []


def test_organisation_still_needs_a_signatory_and_authority():
    """Для организации подписант и основание полномочий по-прежнему обязательны."""
    from korgan.contract_preamble import preamble_defects

    preamble = (
        "ТОО «Астана Диджитал», БИН 190240012345, именуемое далее Заказчик, с одной стороны, и "
        "ИП Ким А.В., именуемый далее Исполнитель, с другой стороны, заключили настоящий договор."
    )
    defects = preamble_defects([preamble])
    assert any("основание полномочий" in d for d in defects)
    assert any("подписывающее договор" in d for d in defects)


def test_preamble_without_party_roles_is_still_blocked():
    from korgan.contract_preamble import preamble_defects

    assert preamble_defects(["Стороны заключили настоящий договор о нижеследующем."])


def test_generated_placeholder_preamble_passes_its_own_check():
    """Шаблон-заглушка обязан проходить проверку, иначе экспорт зациклится."""
    from korgan.contract_preamble import placeholder_preamble, preamble_defects

    text = placeholder_preamble(["ТОО «А», БИН 1"], ["ИП Б, ИИН 2"])
    assert preamble_defects([text]) == []


# ---------------------------------------------------------------------------
# 8. Пользователь всегда получает результат
# ---------------------------------------------------------------------------


def test_verification_notes_are_advice_not_a_blocker():
    """Пометка «проверить перед подачей» — продукт работы, а не её дефект.

    Пока она была жёстким блокером, выпуск был невозможен в принципе: у
    любого реального дела такая пометка есть, а hard blocker обнуляет ready
    независимо от оценки.
    """
    from korgan.document_quality import _common_hygiene

    blockers: list[str] = []
    issues: list[str] = []
    _common_hygiene(
        "claim",
        ["Обычный текст документа без дефектов."],
        blockers,
        issues,
        verified_claims=[],
        verification_notes=["FILING_ACTION: указать банковские реквизиты истца перед подачей."],
    )
    assert blockers == [], "подсказка юристу не должна блокировать выпуск"
    assert any("проверке перед подачей" in i for i in issues)


def test_real_defects_still_block():
    """Ослабление не должно пропускать незаполненные поля и служебный текст."""
    from korgan.document_quality import _common_hygiene

    blockers: list[str] = []
    issues: list[str] = []
    _common_hygiene(
        "claim",
        ["Взыскать [ТРЕБУЕТ УТОЧНЕНИЯ: сумма] тенге."],
        blockers,
        issues,
        verified_claims=[],
        verification_notes=[],
    )
    assert any("незаполненные" in b for b in blockers)


def test_blocked_document_is_translated_into_user_tasks():
    """Клиент должен видеть задачи, а не внутренние формулировки гейтов."""
    from korgan.miniapp_preliminary_delivery import humanize

    todo = humanize([
        "не определена госпошлина или подтвержденная льгота",
        "есть правовая ссылка, не прошедшая source-bound/corpus проверку",
        "FILING_ACTION: указать банковские реквизиты истца-юридического лица перед подачей иска.",
    ])
    assert todo
    joined = " ".join(todo).lower()
    assert "source-bound" not in joined and "corpus" not in joined
    assert "filing_action" not in joined
    assert any("пошлин" in t for t in todo)


def test_preliminary_delivery_is_on_by_default_and_switchable(monkeypatch):
    from korgan.miniapp_preliminary_delivery import FLAG_ENV, preliminary_delivery_enabled

    monkeypatch.delenv(FLAG_ENV, raising=False)
    assert preliminary_delivery_enabled() is True
    monkeypatch.setenv(FLAG_ENV, "off")
    assert preliminary_delivery_enabled() is False


def test_marking_preliminary_does_not_claim_filing_ready():
    from korgan.miniapp_preliminary_delivery import mark_preliminary

    result = mark_preliminary(
        {"document_base64": "...", "quality_score": 8.4, "filing_ready": True},
        ["не определена госпошлина или подтвержденная льгота"],
        "KOR-TEST",
    )
    assert result["filing_ready"] is False
    assert result["release_status"] == "preliminary"
    assert result["document_base64"], "документ должен остаться у пользователя"
    assert result["todo_before_filing"]
