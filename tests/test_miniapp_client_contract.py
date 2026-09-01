"""Бэкенд обязан отдавать ровно те поля, по которым клиент решает работать.

miniapp/src/runtimeReadiness.js пропускает приложение к работе только при этих
значениях. Если хоть одно поле исчезнет или переименуется, boot() поставит
connection 'down', и мини-апп покажет «нет связи» с заблокированными кнопками —
без ошибки в интерфейсе и без записи о причине.

Именно так продукт и стоял: клиент требовал parity.api_version == '0.9.0', а
собранное приложение отдавало '1.0.0'. Совпадали все содержательные поля, и не
совпадало только число. Теперь клиент требует лишь непустую версию, а этот тест
держит содержательную часть контракта.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from korgan.miniapp_api_recovery_cors import app


def test_health_carries_the_fields_the_client_requires() -> None:
    with TestClient(app) as client:
        health = client.get("/health").json()

    assert health["status"] == "ok"
    assert health["legal_runtime"] == "strict_bot"
    assert health["word_quality_target"] == "10/10"
    assert health["preliminary_fallback"] is True


def test_parity_carries_the_fields_the_client_requires() -> None:
    with TestClient(app) as client:
        parity = client.get("/miniapp/parity").json()

    assert parity["status"] == "ok"
    # Клиент требует непустую версию, но не конкретное число: сверка на
    # равенство ломала приложение при каждом повышении версии бэкенда.
    assert isinstance(parity["api_version"], str) and parity["api_version"].strip()
    assert parity["service_outer"] == "ClaimPipelineV2Adapter"
    assert parity["service_claim_mux"] == "ClaimServiceMux"
    assert parity["service_stable"] == "PretrialResponseProductionService"
    assert parity["word_quality_target"] == "10/10"
    assert parity["preliminary_fallback"] is True
    assert isinstance(parity["consultation_limit_enabled"], bool)
    assert isinstance(parity["document_payments_enabled"], bool)
    if parity["document_payments_enabled"]:
        assert parity["document_manual_confirmation"] is True
