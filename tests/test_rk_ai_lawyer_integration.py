from __future__ import annotations

from pathlib import Path

from korgan import citation_audit, client_safe_ui
from korgan.legal.citation_extensions import install_extended_citation_audit
from korgan.legal.corpus import LegalCorpus
from korgan.legal.corpus_refresh import refresh_corpus_once
from korgan.legal.pipeline import research_from_corpus, route_act_ids
from korgan.legal.rk_catalog import CORE_ACT_IDS, KNOWN_ACTS, OPTIONAL_ACT_IDS
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.request_basis_coverage import ensure_request_basis_coverage
from scripts.load_corpus import strip_html


def _research(lines: list[str]) -> LegalResearch:
    return LegalResearch(
        status=VerificationStatus.VERIFIED,
        applicable_law=[],
        procedural_requirements=[],
        verified_claims=lines,
        unverified_claims=[],
        source_urls=["https://adilet.zan.kz/rus/docs/K990000409_"],
        notes=[],
    )


def _draft(requests: list[str], basis: list[str] | None = None) -> ClaimDraft:
    return ClaimDraft(
        status=VerificationStatus.VERIFIED,
        title="Исковое заявление",
        court="Районный суд",
        claimant=["Истец"],
        defendant=["Ответчик"],
        price_of_claim="800 000 ₸",
        facts=["Факт 1", "Факт 2", "Факт 3"],
        legal_basis=list(basis or []),
        requests=requests,
        attachments=[],
        verification_notes=[],
        source_urls=[],
    )


def test_extended_catalog_keeps_production_core_and_adds_broad_rk_law() -> None:
    assert {
        "GK_RK_OBSHAYA",
        "GK_RK_OSOBENNAYA",
        "GPK_RK",
        "NK_RK_GOSPOSHLINA",
        "ZPP_RK",
        "TK_RK",
    } == set(CORE_ACT_IDS)
    assert "APPC_RK" in OPTIONAL_ACT_IDS
    assert "FAMILY_RK" in OPTIONAL_ACT_IDS
    assert "ENFORCEMENT_RK" in OPTIONAL_ACT_IDS
    assert "BANKS_RK" in OPTIONAL_ACT_IDS
    assert len(KNOWN_ACTS) >= 25


def test_law_router_separates_employment_family_and_admin_procedure() -> None:
    employment = route_act_ids("Работодатель не выплатил зарплату и компенсацию за отпуск")
    family = route_act_ids("Хочу взыскать алименты на ребенка после развода")
    admin = route_act_ids("Нужно обжаловать административный акт госоргана по АППК РК")
    assert "TK_RK" in employment
    assert "FAMILY_RK" in family
    assert admin == ("APPC_RK",)


def test_exact_article_reference_is_injected_ahead_of_fts(monkeypatch) -> None:
    monkeypatch.setenv("KORGAN_LOCAL_CORPUS", "1")
    with LegalCorpus(":memory:") as corpus:
        corpus.upsert_act(
            "TK_RK", "K1500000414", "Трудовой кодекс Республики Казахстан",
            "https://adilet.zan.kz/rus/docs/K1500000414", "2026-08-17", "2026-08-17",
        )
        corpus.upsert_provision(
            act_id="TK_RK", article_no="113", item_no=None,
            heading="Порядок и сроки выплаты заработной платы",
            body="Работодатель выплачивает работнику заработную плату в установленные сроки.",
            edition_date="2026-08-17",
            url="https://adilet.zan.kz/rus/docs/K1500000414#z113", sort_key=1,
        )
        result = research_from_corpus("Проверь статью 113 ТК РК", corpus=corpus, limit=5)
    assert result is not None
    assert result.provisions[0].act_id == "TK_RK"
    assert result.provisions[0].article_no == "113"


def test_adilet_parser_drops_amendment_footnote_noise() -> None:
    html = """
    <html><body><article>
      <p><b>Статья 1. Основное правило</b></p>
      <p>Нормативный текст статьи.</p>
      <p>Сноска. Статья с изменениями, внесенными Законом Республики Казахстан.</p>
      <p><b>Статья 2. Следующее правило</b></p>
      <p>Другой нормативный текст.</p>
    </article></body></html>
    """
    text = strip_html(html)
    assert "Нормативный текст статьи" in text
    assert "Сноска." not in text
    assert "Статья 2." in text


def test_optional_act_failure_does_not_destroy_complete_core(monkeypatch, tmp_path: Path) -> None:
    from korgan.legal import corpus_refresh

    def fake_load(corpus: LegalCorpus, act_id: str) -> int:
        if act_id in OPTIONAL_ACT_IDS:
            raise RuntimeError("optional source unavailable")
        adilet_id, title = KNOWN_ACTS[act_id]
        corpus.upsert_act(
            act_id, adilet_id, title, f"https://adilet.zan.kz/rus/docs/{adilet_id}",
            "2026-08-17", "2026-08-17",
        )
        corpus.upsert_provision(
            act_id=act_id, article_no="1", item_no=None, heading="Тест",
            body="Достаточный нормативный текст для атомарного core refresh.",
            edition_date="2026-08-17",
            url=f"https://adilet.zan.kz/rus/docs/{adilet_id}#z1", sort_key=1,
        )
        return 1

    monkeypatch.setattr(corpus_refresh, "_load_one", fake_load)
    path = tmp_path / "corpus.sqlite3"
    total = refresh_corpus_once(path)
    assert total == len(CORE_ACT_IDS)
    with LegalCorpus(path) as corpus:
        assert corpus.count() == len(CORE_ACT_IDS)


def test_loan_request_gets_its_own_verified_basis() -> None:
    research = _research([
        "Заемщик обязан возвратить полученную сумму займа в согласованный срок "
        "[основание: статья 722 ГК РК; текст нормы: «Заемщик обязан возвратить заимодателю полученную сумму займа в срок и порядке, предусмотренных договором.»; "
        "источник: https://adilet.zan.kz/rus/docs/K990000409_]"
    ])
    draft = _draft(["Взыскать с ответчика основной долг 800 000 тенге."])
    missing = ensure_request_basis_coverage(
        "По расписке ответчику передана сумма в займ, остаток долга не возвращен.",
        draft,
        research,
    )
    assert missing == []
    assert any("статья 722" in line for line in draft.legal_basis)


def test_loan_request_without_verified_basis_blocks_release() -> None:
    draft = _draft(["Взыскать с ответчика основной долг 800 000 тенге."])
    missing = ensure_request_basis_coverage(
        "По расписке ответчику передана сумма в займ, остаток долга не возвращен.",
        draft,
        _research([]),
    )
    assert "взыскание долга по займу" in missing
    assert draft.status == VerificationStatus.NEEDS_VERIFICATION
    assert any("Нет отдельной VERIFIED" in note for note in draft.verification_notes)


def test_extended_citation_audit_resolves_consumer_law_to_local_corpus() -> None:
    install_extended_citation_audit()
    refs = citation_audit.extract_references(
        "Согласно статье 35 Закона РК о защите прав потребителей потребитель вправе заявить требование."
    )
    assert refs
    assert refs[0].act == "Закон РК о защите прав потребителей"
    assert client_safe_ui._ACT_IDS["Закон РК о защите прав потребителей"] == ("ZPP_RK",)
