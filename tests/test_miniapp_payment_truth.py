"""О проверке платежа приложение обязано говорить то же, что делает бэкенд.

Развёрнутый путь — korgan.miniapp_api_recovery_cors — подключает слой
miniapp_manual_payment_admin последним. Этот слой снимает клиентские endpoint'ы
приёма чека, «so no client can bypass the administrator decision», и объявляет
сверку платежа ручной. Промежуточные слои v5 и ofd объявляют её автоматической,
поэтому одного взгляда на исходник недостаточно: значение зависит от порядка
слоёв, и проверять надо собранное приложение.

Этот тест — опора для фронтенда: пока он зелёный, обещание автоматической
проверки чека в интерфейсе будет неправдой о деньгах пользователя.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from korgan.miniapp_api_recovery_cors import app


def test_deployed_app_reports_administrator_confirmation_of_payment() -> None:
    with TestClient(app) as client:
        payload = client.get("/miniapp/parity").json()

    assert payload["document_manual_confirmation"] is True
    assert payload["automatic_receipt_verification"] is False
    assert payload["receipt_verification_mode"] == "kaspi_receipt_precheck_then_telegram_admin"
    # Решение по чеку принимает человек, а не модель.
    assert payload["receipt_ai_decision"] is False


def test_deployed_app_keeps_the_client_receipt_shortcut_closed() -> None:
    """Клиент не должен уметь объявить свой платёж принятым."""
    with TestClient(app) as client:
        response = client.post("/miniapp/documents/payments/1/receipt-url")

    assert response.status_code == 409
