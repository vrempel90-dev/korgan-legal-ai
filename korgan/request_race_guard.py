from __future__ import annotations

import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from korgan import bot as base_bot

LOGGER = logging.getLogger(__name__)


def _upload_followup(request_kind: str, language: str) -> str:
    """Keep the post-upload CTA inside the document section the client selected."""
    if request_kind == "pretrial_response":
        if language == "kk":
            return (
                "Егер бәрі дұрыс болса, тағы құжаттар қосуға немесе "
                "сотқа дейінгі талапқа жауапты дайындауды жалғастыруға болады."
            )
        return (
            "Если всё верно, можно добавить ещё документы или продолжить "
            "подготовку ответа на претензию."
        )
    return (
        "Если всё верно, можно добавить ещё документы или попросить подготовить иск — "
        "он придёт файлом Word (.docx)."
    )


def install_request_race_guard() -> None:
    """Prevent a slow upload from being written into a newer legal request.

    Telegram updates are processed concurrently. Document extraction can still be
    running when the client switches to another document type. Without this guard,
    the extracted text from the old request may be saved after the switch and then
    look like fresh evidence in the new request.
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
            if (
                str(after.get("request_id") or "") != request_id
                or str(after.get("request_kind") or "") != request_kind
            ):
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
            if (
                str(after.get("request_id") or "") != request_id
                or str(after.get("request_kind") or "") != request_kind
            ):
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

        after = await state.get_data()
        if (
            str(after.get("request_id") or "") != request_id
            or str(after.get("request_kind") or "") != request_kind
        ):
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
