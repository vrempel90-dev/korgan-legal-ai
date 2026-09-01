"""Фактические владельцы HTTP-маршрутов боевого приложения MiniApp.

Все слои `miniapp_api*` делят ОДИН объект FastAPI: v2 создаёт его, а каждый
следующий слой снимает старый маршрут через `_drop_route` и регистрирует свой.
Поэтому «кто владеет маршрутом» — свойство всего собранного приложения, а не
отдельного модуля.

Раньше каждый слой проверял это по-своему: набор v4 требовал, чтобы
`/miniapp/documents/generate` принадлежал v4, а набор v5 — чтобы v5. Оба
утверждения не могут быть верны одновременно, и какое из них выполнится,
зависело от порядка импортов тестовых модулей. При этом само свойство важное:
дублирующийся маршрут означал бы, что запрос молча уходит не в тот обработчик.

Здесь ожидаемые владельцы записаны один раз и по фактическому боевому
приложению — тому, которое поднимает `korgan.miniapp_telegram_launcher`.
"""

from __future__ import annotations

from typing import Any

from korgan.miniapp_api_recovery_cors import app


def all_routes() -> list[Any]:
    """Все маршруты приложения, включая подключённые через include_router.

    FastAPI держит подключённый роутер вложенным объектом, а не разворачивает
    его в общий список, поэтому плоский обход `app.router.routes` не видит
    маршруты выдачи документа и аналитики.
    """
    collected: list[Any] = []
    pending: list[Any] = list(app.router.routes)
    while pending:
        item = pending.pop(0)
        if getattr(item, "path", None) is None:
            # fastapi.routing._IncludedRouter хранит подключённый роутер в
            # original_router; у обычных Mount вложенные маршруты лежат в routes.
            nested = getattr(item, "original_router", None)
            nested_routes = getattr(nested, "routes", None) or getattr(item, "routes", None)
            if nested_routes:
                pending.extend(nested_routes)
                continue
        collected.append(item)
    return collected


def route(path: str, method: str) -> Any:
    """Единственный маршрут для пары путь+метод. Дубликат — это ошибка."""
    matches = [
        item
        for item in all_routes()
        if getattr(item, "path", None) == path
        and method.upper() in (getattr(item, "methods", set()) or set())
    ]
    assert len(matches) == 1, f"{method} {path}: ожидался ровно один маршрут, найдено {len(matches)}"
    return matches[0]


def endpoint(path: str, method: str) -> Any:
    return route(path, method).endpoint


def owner(path: str, method: str) -> str:
    """Модуль и имя фактического обработчика — удобочитаемо для diff в отчёте."""
    handler = endpoint(path, method)
    return f"{handler.__module__}.{handler.__name__}"


# Владельцы, зафиксированные по собранному боевому приложению. Изменение этой
# таблицы — сознательное решение о том, какой слой обслуживает запрос, и должно
# сопровождаться объяснением в коммите.
EXPECTED_OWNERS: dict[tuple[str, str], str] = {
    ("/health", "GET"): "korgan.miniapp_api_v2.health",
    ("/miniapp/consent", "GET"): "korgan.miniapp_consent_status.get_consent_status",
    ("/miniapp/cases", "POST"): "korgan.miniapp_api_v2.create_case",
    ("/miniapp/cases/{case_id}/materials", "POST"): "korgan.miniapp_api_v2.upload_material",
    ("/miniapp/cases/{case_id}/document", "GET"): "korgan.miniapp_api_v2.get_document",
    ("/miniapp/consultation", "POST"): "korgan.miniapp_api_v4.consultation",
    ("/miniapp/consultation/payments/{order_id}/retry", "POST"): "korgan.miniapp_api_v4.retry_paid_consultation",
    ("/miniapp/admin/document-payments", "GET"): "korgan.miniapp_api_v4.admin_document_payments",
    (
        "/miniapp/admin/document-payments/{order_id}/decision",
        "POST",
    ): "korgan.miniapp_api_v4.admin_document_payment_decision",
    ("/miniapp/documents/generate", "POST"): "korgan.miniapp_generation_api.generate_document_job",
    (
        "/miniapp/documents/generation/{job_id}",
        "GET",
    ): "korgan.miniapp_generation_api.generation_status",
    (
        "/miniapp/documents/generation/{job_id}/retry",
        "POST",
    ): "korgan.miniapp_generation_api.retry_generation",
    ("/miniapp/documents/payments/{order_id}", "GET"): "korgan.miniapp_api_v5.document_payment_status",
    ("/miniapp/documents/payments/{order_id}/retry", "POST"): "korgan.miniapp_api_v5.retry_paid_document",
    (
        "/miniapp/consultation/payments/{order_id}",
        "GET",
    ): "korgan.miniapp_api_ofd_upload.consultation_payment_status",
    (
        "/miniapp/consultation/payments/{order_id}/receipt",
        "POST",
    ): "korgan.miniapp_api_ofd_upload.consultation_receipt_upload",
    (
        "/miniapp/consultation/payments/{order_id}/receipt-url",
        "POST",
    ): "korgan.miniapp_api_ofd.consultation_receipt_url",
    # Ручное подтверждение платежа за документ — самый внешний слой оплаты.
    (
        "/miniapp/documents/payments/{order_id}/receipt",
        "POST",
    ): "korgan.miniapp_manual_payment_admin.document_receipt_upload_manual",
    (
        "/miniapp/documents/payments/{order_id}/receipt-url",
        "POST",
    ): "korgan.miniapp_manual_payment_admin.document_receipt_url_manual_only",
    ("/miniapp/parity", "GET"): "korgan.miniapp_manual_payment_admin.parity",
    ("/miniapp/pricing", "GET"): "korgan.miniapp_manual_payment_admin.pricing",
    ("/miniapp/cases/{case_id}/document/telegram", "POST"): "korgan.miniapp_telegram_delivery.send_document_to_telegram",
    ("/miniapp/cases/{case_id}/document/access", "POST"): "korgan.miniapp_document_access.create_document_access",
    ("/miniapp/document/download", "GET"): "korgan.miniapp_document_access.download_document",
    ("/miniapp/document/preview", "GET"): "korgan.miniapp_document_access.preview_document",
}
