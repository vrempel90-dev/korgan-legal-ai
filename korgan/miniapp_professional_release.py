from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from korgan.miniapp_preliminary_delivery import (
    FLAG_ENV,
    humanize,
    mark_preliminary,
    preliminary_delivery_enabled,
)

LOGGER = logging.getLogger(__name__)
_INSTALLED = False

__all__ = [
    "FLAG_ENV",
    "ReleaseBlocked",
    "apply_release_policy",
    "install_miniapp_professional_release_gate",
    "professional_release_allowed",
]

_BLOCK_DETAIL = (
    "KORGAN не выпустил Word: документ не прошёл финальную профессиональную проверку. "
    "Оплата не должна списываться повторно; после исправления генерацию можно повторить."
)


class ReleaseBlocked(Exception):
    """Документ написан, но политика выпуска запретила отдавать его клиенту.

    Текст исключения предназначен пользователю: он попадает и в HTTP-ответ
    прямого запроса, и в `error_detail` фоновой задачи. Ничего внутреннего —
    ни стадий пайплайна, ни отладочных формулировок — в нём быть не должно.
    """

    def __init__(self, issues: list[str]) -> None:
        self.issues = list(issues)
        # Замечания приходят из проверок в их собственном протоколе — с
        # префиксами вроде FILING_ACTION и внутренними формулировками. Тот же
        # список для помеченного черновика давно переводится на человеческий
        # язык, и отказ пользуется тем же переводом: иначе клиент читал бы
        # разметку проверок. Непереводимое замечание не показывается вовсе —
        # объяснение без перечня причин честнее перечня из служебных строк.
        reasons = humanize(self.issues)
        detail = _BLOCK_DETAIL
        if reasons:
            detail += " Причина: " + "; ".join(reasons[:4])
        self.detail = detail
        super().__init__(detail)


def professional_release_allowed(result: dict[str, Any]) -> bool:
    """Only a fully verified filing-ready result may expose a Word document."""
    return bool(result.get("filing_ready")) and str(result.get("release_status") or "") == "verified"


def _issue_list(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("quality_issues", "verification_notes"):
        for item in list(result.get(key) or []):
            text = " ".join(str(item or "").split()).strip()
            if text and text not in values:
                values.append(text)
    return values


def apply_release_policy(result: dict[str, Any], *, case_id: str) -> dict[str, Any]:
    """Единственное правило выпуска для всех путей генерации.

    Прямой HTTP-запрос и фоновая задача вызывают разные слои движка, поэтому
    правило вынесено сюда: иначе фоновая задача выпускала бы документ, который
    прямой запрос выпустить отказался бы, и оплативший пользователь получал бы
    разный результат в зависимости от того, включены ли платежи.
    """
    if professional_release_allowed(result):
        return result

    issues = _issue_list(result)
    if preliminary_delivery_enabled():
        return mark_preliminary(result, issues, case_id)

    LOGGER.error(
        "MINIAPP_PROFESSIONAL_RELEASE_BLOCK case_id=%s score=%r issues=%s",
        case_id,
        result.get("quality_score"),
        issues[:6],
    )
    raise ReleaseBlocked(issues)


async def _purge_unreleased_document(core: Any, payload: Any, init_data: str, result: dict[str, Any]) -> None:
    """Make a failed quality attempt impossible to download through the case endpoint."""
    identity = core.legacy._identity(init_data)
    state = await core.legacy._require_consent(identity)
    case = state.get("cases", {}).get(payload.case_id)
    if case is None:
        return

    for key in ("document_base64", "filename"):
        case.pop(key, None)
    case["status"] = "quality_blocked"
    case["filing_ready"] = False
    case["release_status"] = "blocked"
    case["quality_score"] = result.get("quality_score")
    case["quality_issues"] = list(result.get("quality_issues") or [])
    case["verification_notes"] = list(result.get("verification_notes") or [])
    await core.store.save(identity, state)


def install_miniapp_professional_release_gate() -> None:
    """Never expose a paid Word document that the legal QA marked preliminary.

    The existing production service already performs source-bound legal research,
    drafting, deterministic checks and one bounded repair. Historically the Mini
    App still stored and returned the DOCX when those checks ended with
    filing_ready=False. This gate changes only release policy: a weak draft is
    purged and the paid order remains retryable instead of being delivered.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from korgan import miniapp_api_v2 as core

    original: Callable[..., Awaitable[dict[str, Any]]] = core.generate_document

    async def guarded_generate_document(payload: Any, x_telegram_init_data: str = "") -> dict[str, Any]:
        result = await original(payload, x_telegram_init_data)
        # Отдавать оплатившему пользователю пустоту хуже, чем отдать честно
        # помеченный черновик: документ уже написан, доработан и несёт штамп
        # PRELIMINARY DRAFT вместе с подвалом «перед подачей проверьте…».
        # Часть «блокеров» — вообще не дефекты, а подсказки юристу.
        # Выключается переменной KORGAN_PRELIMINARY_DELIVERY=off.
        try:
            return apply_release_policy(result, case_id=str(getattr(payload, "case_id", "")))
        except ReleaseBlocked as blocked:
            await _purge_unreleased_document(core, payload, x_telegram_init_data, result)
            raise HTTPException(status_code=422, detail=blocked.detail) from blocked

    core.generate_document = guarded_generate_document  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info(
        "Installed Mini App professional release gate: preliminary delivery=%s",
        "on" if preliminary_delivery_enabled() else "off",
    )
