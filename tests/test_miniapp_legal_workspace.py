from __future__ import annotations

import asyncio
from datetime import date

from korgan import miniapp_legal_workspace as workspace


async def _allowed_identity(_: str):
    return "user", {"cases": {}}


def test_workspace_capabilities_are_kz_current_law_and_do_not_enable_payment():
    payload = asyncio.run(workspace.capabilities())
    assert payload["jurisdiction"] == "KZ"
    assert payload["current_law_verification"] is True
    assert payload["official_norm_source"] == "adilet.zan.kz"
    assert payload["calculations_are_deterministic"] is True
    assert payload["payment_enabled_by_workspace"] is False
    assert "state_duty" in payload["tools"]
    assert "position_stress_test" in payload["tools"]


def test_property_state_duty_uses_deterministic_legal_calc(monkeypatch):
    monkeypatch.setattr(workspace, "_require_identity", _allowed_identity)
    request = workspace.StateDutyRequest(mode="property", claimant_type="individual", amount_kzt=5_000_000)
    payload = asyncio.run(workspace.state_duty(request, "telegram-init"))
    assert payload["status"] == "calculated"
    assert payload["amount_kzt"] == workspace.legal_calc.calc_gosposhlina_claim(5_000_000, True)
    assert payload["source_url"].startswith("https://adilet.zan.kz/")
    assert payload["mrp"] == workspace.legal_calc.mrp_on()


def test_late_penalty_353_returns_formula_and_official_source(monkeypatch):
    monkeypatch.setattr(workspace, "_require_identity", _allowed_identity)
    request = workspace.LatePenaltyRequest(
        principal_kzt=1_000_000,
        start_date=date(2026, 1, 10),
        end_date=date(2026, 1, 20),
        rate_date=date(2026, 1, 10),
    )
    payload = asyncio.run(workspace.late_penalty_353(request, "telegram-init"))
    assert payload["status"] == "calculated"
    assert payload["amount_kzt"] > 0
    assert payload["days"] == 11
    assert "×" in payload["formula"]
    assert payload["source_url"].startswith("https://adilet.zan.kz/")
    assert payload["rate_source_url"]


def test_late_penalty_fails_closed_when_rate_is_not_known(monkeypatch):
    monkeypatch.setattr(workspace, "_require_identity", _allowed_identity)
    request = workspace.LatePenaltyRequest(
        principal_kzt=1_000_000,
        start_date=date(2099, 1, 1),
        end_date=date(2099, 1, 2),
        rate_date=date(2099, 1, 1),
    )
    payload = asyncio.run(workspace.late_penalty_353(request, "telegram-init"))
    assert payload["status"] == "needs_verification"
    assert payload["amount_kzt"] is None
    assert "ТРЕБУЕТ ПРОВЕРКИ" in payload["reason"]


def test_stress_test_uses_case_context_and_professional_consult(monkeypatch):
    async def identity(_: str):
        return "user", {
            "cases": {
                "case-1": {
                    "id": "case-1",
                    "description": "Поставщик не передал оплаченный товар. Оплата 1 000 000 тенге подтверждена.",
                    "materials": [],
                    "conversation": [],
                }
            }
        }

    calls: dict[str, str] = {}

    class Service:
        async def consult(self, question: str, case_context: str = "", language: str = "ru"):
            calls["question"] = question
            calls["context"] = case_context
            calls["language"] = language
            return "Слабое место: необходимо подтвердить факт передачи товара.", ["https://adilet.zan.kz/rus/docs/K940001000_"]

    monkeypatch.setattr(workspace, "_require_identity", identity)
    monkeypatch.setattr(workspace.core, "service", Service())
    payload = asyncio.run(
        workspace.stress_test(
            workspace.StressTestRequest(case_id="case-1", focus="доказательства", language="ru"),
            "telegram-init",
        )
    )
    assert payload["status"] == "verified_analysis"
    assert payload["current_law_only"] is True
    assert "Stress Test" in calls["question"]
    assert "Поставщик" in calls["context"]
    assert payload["sources"][0].startswith("https://adilet.zan.kz/")
