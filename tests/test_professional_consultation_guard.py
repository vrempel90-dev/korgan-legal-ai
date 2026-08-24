from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import korgan.professional_consultation_guard as guard
from korgan import claim_release_entrypoint
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.claim_service_mux import ClaimServiceMux
from korgan.config import Settings
from korgan.finalized_litigation import FinalizedProductionClaimService
from korgan.legal.corpus import ACT_GK_GENERAL, LegalCorpus
from korgan.pretrial_response import PretrialResponseProductionService
from korgan.professional_consultation_guard import (
    _accept_verified_points,
    _corpus_article_check,
    _render_consultation,
    _safe_free_text,
    install_professional_consultation_guard,
)

ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
ADILET_ENG = "https://adilet.zan.kz/eng/docs/K940001000_"
TAX_ADILET = "https://adilet.zan.kz/rus/docs/K2500000214"
COURT_URL = "https://sud.gov.kz/rus/content/sudy-respubliki-kazahstan"
PROVISION = (
    "Защита гражданских прав осуществляется судом, арбитражем путем признания прав, "
    "восстановления положения, существовавшего до нарушения права, и иными способами, предусмотренными законом."
)


class FakeService:
    @staticmethod
    def _is_current_official_source(url: str) -> bool:
        return url.startswith("https://adilet.zan.kz/") or url.startswith("https://sud.gov.kz/")


def _response_with_sources(*urls: str):
    return SimpleNamespace(
        output=[SimpleNamespace(
            type="web_search_call",
            action=SimpleNamespace(url=None, sources=[SimpleNamespace(url=url) for url in urls]),
        )]
    )


def _point(*, source_url: str = ADILET) -> dict[str, str]:
    return {
        "statement": "Гражданские права могут защищаться предусмотренными законом способами.",
        "article": "статья 9 ГК РК",
        "provision_text": PROVISION,
        "source_url": source_url,
    }


def _tax_point() -> dict[str, str]:
    return {
        "statement": "Для имущественного требования физического лица ставка государственной пошлины составляет 1% от цены иска.",
        "article": "статья 665 НК РК",
        "provision_text": (
            "С исковых заявлений имущественного характера, подаваемых в суд физическими лицами, "
            "государственная пошлина взимается в размере одного процента от суммы иска."
        ),
        "source_url": TAX_ADILET,
    }


def test_claimed_url_is_not_verified_unless_response_actually_opened_it() -> None:
    accepted, rejected, used = _accept_verified_points(
        FakeService(), {"verified_points": [_point()]}, _response_with_sources()
    )
    assert accepted == []
    assert used == []
    assert rejected and "реально открытым" in rejected[0]


def test_opened_adilet_point_passes_all_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "_corpus_article_check", lambda *args: True)
    accepted, rejected, used = _accept_verified_points(
        FakeService(), {"verified_points": [_point()]}, _response_with_sources(ADILET)
    )
    assert len(accepted) == 1
    assert rejected == []
    assert used == [ADILET]


def test_non_russian_adilet_page_cannot_release_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "_corpus_article_check", lambda *args: True)
    accepted, rejected, used = _accept_verified_points(
        FakeService(), {"verified_points": [_point(source_url=ADILET_ENG)]}, _response_with_sources(ADILET_ENG)
    )
    assert accepted == []
    assert used == []
    assert any("русская официальная страница Adilet" in item for item in rejected)


def test_court_url_alone_never_releases_exact_jurisdiction() -> None:
    payload = {"verified_points": [{
        "statement": "Дело подсудно Специализированному межрайонному экономическому суду города Алматы.",
        "article": "официальный перечень судов",
        "provision_text": "Официальная страница содержит сведения о судебной системе Республики Казахстан.",
        "source_url": COURT_URL,
    }]}
    accepted, rejected, used = _accept_verified_points(FakeService(), payload, _response_with_sources(COURT_URL))
    assert accepted == []
    assert used == []
    assert any("отдельной официальной проверки" in item for item in rejected)


def test_current_local_corpus_confirms_exact_article_and_quote(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(db_path) as corpus:
        corpus.upsert_act(
            ACT_GK_GENERAL, "K940001000_", "Гражданский кодекс Республики Казахстан (Общая часть)",
            ADILET, "2026-08-24", "2026-08-24T15:00:00+00:00",
        )
        corpus.upsert_provision(
            act_id=ACT_GK_GENERAL, article_no="9", item_no=None,
            heading="Статья 9. Защита гражданских прав",
            body=PROVISION + " Дополнительный текст статьи для контрольной записи.",
            edition_date="2026-08-24", url=ADILET, sort_key=9,
        )
    monkeypatch.setattr(guard, "DEFAULT_DB_PATH", db_path)
    assert _corpus_article_check("статья 9 ГК РК", ADILET, PROVISION) is True
    assert _corpus_article_check("статья 999 ГК РК", ADILET, PROVISION) is False
    assert _corpus_article_check("статья 9 ГК РК", ADILET, PROVISION + " Срок составляет 10 дней.") is False


def test_missing_local_corpus_fails_closed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "DEFAULT_DB_PATH", tmp_path / "missing.sqlite3")
    assert _corpus_article_check("статья 9 ГК РК", ADILET, PROVISION) is False


def test_precise_unbound_law_is_removed_from_operational_text() -> None:
    assert _safe_free_text("По статье 9 ГК РК вы вправе обратиться в суд.") == ""
    assert _safe_free_text("Госпошлина составляет 1% от цены иска.") == ""
    assert _safe_free_text("Подайте жалобу в течение 10 дней.") == ""
    assert _safe_free_text("10 күн ішінде талап беріңіз.") == ""
    assert _safe_free_text("Срок для ответа составляет десять рабочих дней.") == ""
    assert _safe_free_text("Ставка составляет один процент.") == ""
    assert _safe_free_text("Дело рассматривает специализированный межрайонный экономический суд.") == ""
    assert _safe_free_text("Істі мамандандырылған ауданаралық экономикалық сот қарайды.") == ""
    assert _safe_free_text("Соберите договор, переписку и подтверждение оплаты.")


def test_renderer_never_echoes_unverified_exact_law() -> None:
    payload = {
        "recommended_actions": ["Подайте документы в течение десяти дней.", "Соберите договор и переписку."],
        "verified_points": [],
        "unverified_claims": ["По статье 999 ГК РК применяется срок 10 дней.", "Не хватает официального подтверждения основания."],
    }
    answer = _render_consultation(
        payload, [], ["По статье 888 ГК РК срок составляет десять дней."], language="ru"
    )
    assert "999" not in answer and "888" not in answer
    assert "10 дней" not in answer and "десяти дней" not in answer.lower()
    assert "Не хватает официального подтверждения" in answer


def test_renderer_releases_verified_law_and_only_safe_actions() -> None:
    payload = {
        "recommended_actions": ["Соберите договор и подтверждение оплаты.", "Подайте жалобу в течение 5 дней."],
        "verified_points": [], "unverified_claims": [],
    }
    accepted = [("Гражданские права могут защищаться предусмотренными законом способами.", "статья 9 ГК РК", ADILET)]
    answer = _render_consultation(payload, accepted, [], language="ru")
    assert "статья 9 ГК РК" in answer
    assert "Соберите договор и подтверждение оплаты" in answer
    assert "5 дней" not in answer


def test_consult_schema_has_no_free_form_legal_analysis_channel() -> None:
    properties = guard._CONSULT_SCHEMA["properties"]
    assert set(properties) == {"recommended_actions", "verified_points", "unverified_claims"}


def test_guard_patches_both_supported_production_service_classes() -> None:
    from korgan.stable_legal_release import StableLegalProductionService
    install_professional_consultation_guard()
    assert StableLegalProductionService.consult.__module__ == "korgan.professional_consultation_guard"
    assert FinalizedProductionClaimService.consult.__module__ == "korgan.professional_consultation_guard"


def test_claim_release_entrypoint_installs_consult_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(claim_release_entrypoint.claim_quality_hotfix, "install_runtime_hotfix", lambda: calls.append("claim"))
    monkeypatch.setattr(claim_release_entrypoint, "install_professional_consultation_guard", lambda: calls.append("consult"))
    monkeypatch.setattr(claim_release_entrypoint.bot, "main", lambda: "bot-main")
    monkeypatch.setattr(claim_release_entrypoint.asyncio, "run", lambda value: calls.append(value))
    claim_release_entrypoint.main()
    assert calls == ["claim", "consult", "bot-main"]
    assert claim_release_entrypoint.bot.OpenAILegalService is FinalizedProductionClaimService


def test_guard_runs_through_strict_service_delegation_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    install_professional_consultation_guard()
    monkeypatch.setattr(guard, "_corpus_article_check", lambda *args: True)
    settings = Settings(telegram_bot_token="test-token", openai_api_key="test-key")
    stable = PretrialResponseProductionService(settings)
    production = ClaimPipelineV2Adapter(ClaimServiceMux(stable, settings))
    sources = [ADILET, TAX_ADILET]
    payload = {
        "recommended_actions": ["Соберите договор и подтверждение оплаты."],
        "verified_points": [_point(), _tax_point()], "unverified_claims": [],
    }

    async def fake_structured_response(**kwargs):
        return payload, _response_with_sources(*sources)

    monkeypatch.setattr(stable, "_structured_response", fake_structured_response)
    answer, urls = asyncio.run(production.consult("Как защитить право?", language="ru"))
    assert "статья 9 ГК РК" in answer and "статья 665 НК РК" in answer and "1%" in answer
    assert urls == [ADILET, TAX_ADILET]
    sources.clear()
    blocked, blocked_urls = asyncio.run(production.consult("Как защитить право?", language="ru"))
    assert blocked_urls == [] and "статья 9" not in blocked and "1%" not in blocked


def test_guard_runs_on_current_procfile_service(monkeypatch: pytest.MonkeyPatch) -> None:
    install_professional_consultation_guard()
    monkeypatch.setattr(guard, "_corpus_article_check", lambda *args: True)
    settings = Settings(telegram_bot_token="test-token", openai_api_key="test-key")
    service = FinalizedProductionClaimService(settings)
    payload = {"recommended_actions": [], "verified_points": [_point()], "unverified_claims": []}

    async def fake_structured_response(**kwargs):
        return payload, _response_with_sources(ADILET)

    monkeypatch.setattr(service, "_structured_response", fake_structured_response)
    answer, urls = asyncio.run(service.consult("Как защитить право?", language="ru"))
    assert "статья 9 ГК РК" in answer
    assert urls == [ADILET]
