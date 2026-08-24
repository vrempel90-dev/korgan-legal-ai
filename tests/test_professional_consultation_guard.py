from __future__ import annotations

from types import SimpleNamespace

import pytest

import korgan.professional_consultation_guard as guard
from korgan.legal.corpus import ACT_GK_GENERAL, LegalCorpus
from korgan.professional_consultation_guard import (
    _accept_verified_points,
    _corpus_article_check,
    _render_consultation,
    _safe_free_text,
    install_professional_consultation_guard,
)


ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"
ADILET_ENG = "https://adilet.zan.kz/eng/docs/K940001000_"
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
        output=[
            SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(
                    url=None,
                    sources=[SimpleNamespace(url=url) for url in urls],
                ),
            )
        ]
    )


def _point(*, source_url: str = ADILET) -> dict[str, str]:
    return {
        "statement": "Гражданские права могут защищаться предусмотренными законом способами.",
        "article": "статья 9 ГК РК",
        "provision_text": PROVISION,
        "source_url": source_url,
    }


def test_claimed_url_is_not_verified_unless_response_actually_opened_it() -> None:
    payload = {"verified_points": [_point()]}

    accepted, rejected, used = _accept_verified_points(
        FakeService(),
        payload,
        _response_with_sources(),
    )

    assert accepted == []
    assert used == []
    assert rejected
    assert "реально открытым" in rejected[0]


def test_opened_adilet_point_passes_source_and_paraphrase_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exact corpus identity has its own tests below. Keep this test scoped to the
    # live source binding + paraphrase contract.
    monkeypatch.setattr(guard, "_corpus_article_check", lambda *args: True)
    payload = {"verified_points": [_point()]}

    accepted, rejected, used = _accept_verified_points(
        FakeService(),
        payload,
        _response_with_sources(ADILET),
    )

    assert len(accepted) == 1
    assert rejected == []
    assert used == [ADILET]
    assert accepted[0][1] == "статья 9 ГК РК"


def test_non_russian_adilet_page_cannot_release_a_legal_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "_corpus_article_check", lambda *args: True)
    payload = {"verified_points": [_point(source_url=ADILET_ENG)]}

    accepted, rejected, used = _accept_verified_points(
        FakeService(),
        payload,
        _response_with_sources(ADILET_ENG),
    )

    assert accepted == []
    assert used == []
    assert any("русская официальная страница Adilet" in item for item in rejected)


def test_current_local_corpus_confirms_exact_article_and_quote(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "corpus.sqlite3"
    with LegalCorpus(db_path) as corpus:
        corpus.upsert_act(
            ACT_GK_GENERAL,
            "K940001000_",
            "Гражданский кодекс Республики Казахстан (Общая часть)",
            ADILET,
            "2026-08-24",
            "2026-08-24T15:00:00+00:00",
        )
        corpus.upsert_provision(
            act_id=ACT_GK_GENERAL,
            article_no="9",
            item_no=None,
            heading="Статья 9. Защита гражданских прав",
            body=PROVISION + " Дополнительный текст статьи для контрольной записи.",
            edition_date="2026-08-24",
            url=ADILET,
            sort_key=9,
        )

    monkeypatch.setattr(guard, "DEFAULT_DB_PATH", db_path)

    assert _corpus_article_check("статья 9 ГК РК", ADILET, PROVISION) is True
    assert _corpus_article_check("статья 999 ГК РК", ADILET, PROVISION) is False
    assert _corpus_article_check(
        "статья 9 ГК РК",
        ADILET,
        "Совершенно иной текст нормы, которого нет в текущей статье и который не должен пройти проверку.",
    ) is False


def test_precise_unbound_law_is_removed_from_operational_text() -> None:
    assert _safe_free_text("По статье 9 ГК РК вы вправе обратиться в суд.") == ""
    assert _safe_free_text("Госпошлина составляет 1% от цены иска.") == ""
    assert _safe_free_text("Срок составляет 10 дней.") == ""
    assert _safe_free_text("Соберите договор, переписку и подтверждение оплаты.")


def test_renderer_fails_closed_and_does_not_echo_hallucinated_law() -> None:
    payload = {
        "recommended_actions": [
            "Подайте документы в течение 10 дней.",
            "Соберите договор, переписку и подтверждение оплаты.",
        ],
        "verified_points": [],
        "unverified_claims": [
            "По статье 999 ГК РК применяется срок 10 дней.",
            "Не хватает официального подтверждения правового основания.",
        ],
    }

    answer = _render_consultation(payload, [], [], language="ru")

    assert "не буду выдавать непроверенную статью" in answer.lower()
    assert "999" not in answer
    assert "10 дней" not in answer
    assert "Не хватает официального подтверждения" in answer


def test_renderer_releases_only_verified_law_and_safe_actions() -> None:
    payload = {
        "recommended_actions": [
            "Соберите договор и подтверждение оплаты.",
            "По статье 777 ГК РК направьте заявление в течение 5 дней.",
        ],
        "verified_points": [],
        "unverified_claims": [],
    }
    accepted = [(
        "Гражданские права могут защищаться предусмотренными законом способами.",
        "статья 9 ГК РК",
        ADILET,
    )]

    answer = _render_consultation(payload, accepted, [], language="ru")

    assert "статья 9 ГК РК" in answer
    assert "Соберите договор и подтверждение оплаты" in answer
    assert "777" not in answer
    assert "5 дней" not in answer


def test_consult_schema_has_no_free_form_legal_analysis_channel() -> None:
    properties = guard._CONSULT_SCHEMA["properties"]
    assert "summary" not in properties
    assert "analysis" not in properties
    assert set(properties) == {"recommended_actions", "verified_points", "unverified_claims"}


def test_guard_binds_to_stable_service_used_by_strict_bot() -> None:
    from korgan.stable_legal_release import StableLegalProductionService

    install_professional_consultation_guard()

    assert getattr(StableLegalProductionService, "_korgan_professional_consultation_guard", False) is True
    assert StableLegalProductionService.consult.__module__ == "korgan.professional_consultation_guard"
