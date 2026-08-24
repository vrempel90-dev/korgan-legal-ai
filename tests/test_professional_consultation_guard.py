from __future__ import annotations

from types import SimpleNamespace

from korgan.professional_consultation_guard import (
    _accept_verified_points,
    _render_consultation,
    _safe_free_text,
    install_professional_consultation_guard,
)


ADILET = "https://adilet.zan.kz/rus/docs/K940001000_"


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
        "statement": "Стороны вправе защищать свои гражданские права предусмотренными законом способами.",
        "article": "статья 9 ГК РК",
        "provision_text": (
            "Защита гражданских прав осуществляется судом, арбитражем путем признания прав, "
            "восстановления положения, существовавшего до нарушения права, и иными способами, предусмотренными законом."
        ),
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


def test_opened_adilet_point_passes_only_when_paraphrase_matches_provision() -> None:
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


def test_precise_unbound_law_is_removed_from_free_consultation_text() -> None:
    assert _safe_free_text("По статье 9 ГК РК вы вправе обратиться в суд.") == ""
    assert _safe_free_text("Госпошлина составляет 1% от цены иска.") == ""
    assert _safe_free_text("Срок составляет 10 дней.") == ""
    assert _safe_free_text("Соберите договор, переписку и подтверждение оплаты.")


def test_renderer_fails_closed_when_no_source_bound_point_survives() -> None:
    payload = {
        "summary": "По статье 999 ГК РК вы точно выиграете.",
        "analysis": ["Срок составляет 10 дней."],
        "recommended_actions": ["Подайте документы в течение 10 дней."],
        "verified_points": [],
        "unverified_claims": ["Не подтверждена применимая статья."],
    }

    answer = _render_consultation(payload, [], [], language="ru")

    assert "не буду выдавать непроверенную статью" in answer.lower()
    assert "999" not in answer
    assert "10 дней" not in answer
    assert "Не подтверждена применимая статья" in answer


def test_guard_binds_to_stable_service_used_by_strict_bot() -> None:
    from korgan.stable_legal_release import StableLegalProductionService

    install_professional_consultation_guard()

    assert getattr(StableLegalProductionService, "_korgan_professional_consultation_guard", False) is True
    assert StableLegalProductionService.consult.__module__ == "korgan.professional_consultation_guard"
