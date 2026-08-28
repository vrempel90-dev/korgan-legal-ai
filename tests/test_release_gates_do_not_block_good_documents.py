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
    import ssl

    from korgan.legal.corpus_refresh import _trusted_context

    context = _trusted_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert len(context.get_ca_certs()) > 50
