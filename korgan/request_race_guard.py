from __future__ import annotations

import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan import bot as base_bot
from korgan.request_scope import document_request_lock

LOGGER = logging.getLogger(__name__)


def _upload_followup(request_kind: str, language: str) -> str:
    """Keep the post-upload CTA inside the document section the client selected."""
    kk = str(language or "").lower().startswith("kk")
    if request_kind == "claim":
        if kk:
            return (
                "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе талап қою арызын "
                "дайындауды жалғастыруға болады."
            )
        return (
            "Если всё верно, можно добавить ещё документы или попросить подготовить иск — "
            "он придёт файлом Word (.docx)."
        )
    if request_kind == "pretrial":
        return (
            "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе сотқа дейінгі талапты "
            "дайындауды жалғастыруға болады."
            if kk
            else "Если всё верно, можно добавить ещё документы или продолжить подготовку досудебной претензии."
        )
    if request_kind == "pretrial_response":
        return (
            "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе сотқа дейінгі талапқа жауапты "
            "дайындауды жалғастыруға болады."
            if kk
            else "Если всё верно, можно добавить ещё документы или продолжить подготовку ответа на претензию."
        )
    if request_kind == "response":
        return (
            "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе талап қою арызына пікірді "
            "дайындауды жалғастыруға болады."
            if kk
            else "Если всё верно, можно добавить ещё документы или продолжить подготовку отзыва на иск."
        )
    if request_kind == "contract":
        return (
            "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе шартты дайындауды жалғастыруға болады."
            if kk
            else "Если всё верно, можно добавить ещё документы или продолжить подготовку договора."
        )
    return (
        "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе таңдалған құжатпен жұмысты жалғастыруға болады."
        if kk
        else "Если всё верно, можно добавить ещё документы или продолжить работу с выбранным документом."
    )


def _request_matches(data: dict, request_id: str, request_kind: str) -> bool:
    return (
        str(data.get("request_id") or "") == request_id
        and str(data.get("request_kind") or "") == request_kind
    )


def install_request_race_guard() -> None:
    """Prevent a slow upload from being written into a newer legal request.

    Telegram updates are processed concurrently. Document extraction can still be
    running when the client switches to another document type. The same per-session
    request lock used to replace document requests protects the final save and
    client notice, so an old upload cannot leak into a newer request.
    """
    if getattr(base_bot, "_request_race_guard_installed", False):
        return

    async def guarded_analyze_upload(
        message: Message,
        state: FSMContext,
        data: bytes,
        filename: str,
        mime_type: str | None,
    ) -> None:
        service = base_bot.service
        if service is None:
            return

        before = await state.get_data()
        request_id = str(before.get("request_id") or "")
        request_kind = str(before.get("request_kind") or "")
        language = str(before.get("language") or "ru")

        await message.bot.send_chat_action(message.chat.id, "typing")
        try:
            extracted = await service.extract_document(data, filename, mime_type)
        except ValueError as exc:
            after = await state.get_data()
            if not _request_matches(after, request_id, request_kind):
                LOGGER.info(
                    "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                    request_id,
                    request_kind,
                    filename,
                )
                return
            await message.answer(str(exc), reply_markup=base_bot.MENU)
            return
        except Exception:
            LOGGER.exception("Document analysis failed")
            after = await state.get_data()
            if not _request_matches(after, request_id, request_kind):
                LOGGER.info(
                    "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                    request_id,
                    request_kind,
                    filename,
                )
                return
            await message.answer(
                "Не удалось разобрать документ. Проверьте формат/качество и попробуйте ещё раз.",
                reply_markup=base_bot.MENU,
            )
            return

        async with document_request_lock(state):
            after = await state.get_data()
            if not _request_matches(after, request_id, request_kind):
                LOGGER.info(
                    "STALE_UPLOAD_SUPPRESSED request_id=%s kind=%s file=%s",
                    request_id,
                    request_kind,
                    filename,
                )
                return

            count = await base_bot._save_document(state, extracted)
            preview = extracted.as_context()
            await message.answer(
                f"✅ Материал разобран и добавлен в дело ({count}).\n\n{preview[:3200]}\n\n"
                + _upload_followup(request_kind, language),
                reply_markup=base_bot.MENU,
            )

    base_bot._analyze_upload = guarded_analyze_upload
    base_bot._request_race_guard_installed = True
    LOGGER.info("KORGAN request race guard installed")
