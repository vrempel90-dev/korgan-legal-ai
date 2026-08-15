from __future__ import annotations

import logging
import traceback
from threading import Event
from typing import Any

from korgan_legal_ai.domain.exceptions import ClarificationRequired, LegalQABlocked
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.telegram.localization import text
from korgan_legal_ai.telegram.session import (
    SessionState,
    SessionStore,
    TelegramSession,
)

logger = logging.getLogger(__name__)

PRIVACY_VERSION_DEFAULT = "2026-08-15"

BOT_COMMANDS = [
    {"command": "start", "description": "Начать работу"},
    {"command": "menu", "description": "Главное меню"},
    {"command": "language", "description": "Язык интерфейса"},
    {"command": "privacy", "description": "Обработка данных"},
    {"command": "cancel", "description": "Отменить текущий запрос"},
    {"command": "help", "description": "Помощь"},
]


class TelegramRuntime:
    def __init__(
        self,
        *,
        api: Any,
        engine: LegalEngine,
        sessions: SessionStore,
        privacy_version: str = PRIVACY_VERSION_DEFAULT,
        poll_timeout_seconds: int = 30,
        max_case_chars: int = 16000,
    ) -> None:
        self.api = api
        self.engine = engine
        # The backend is always chosen explicitly by the caller. There is no default, so a
        # misconfigured deployment can never quietly downgrade to in-memory sessions.
        self.sessions = sessions
        self.privacy_version = privacy_version
        self.poll_timeout_seconds = poll_timeout_seconds
        self.max_case_chars = max_case_chars

    @staticmethod
    def _safe_exception_diagnostics(exc: BaseException) -> tuple[str, str, str]:
        """Return privacy-safe pipeline diagnostics without logging case text or exception text.

        Exception messages from providers can contain request fragments. We therefore record only
        exception classes plus a project-relative traceback location. The stage is inferred from
        module paths already present in the traceback, so diagnostics remain useful without
        persisting Telegram ids, case text, prompts, URLs, or provider payloads.
        """
        frames = traceback.extract_tb(exc.__traceback__)
        normalized = [
            (frame, frame.filename.replace("\\", "/"))
            for frame in frames
        ]

        stage_rules = (
            ("/fact_lock/", "fact_lock"),
            ("/router/", "task_router"),
            ("/procedural_rules/", "procedural_rules"),
            ("/research/", "legal_research"),
            ("/corpus/", "legal_research"),
            ("/procedural/", "procedural_checks"),
            ("/drafting/", "drafting"),
            ("/qa/", "final_qa"),
            ("/calculations/", "calculations"),
            ("/evidence/", "evidence_map"),
            ("/orchestration/", "orchestration"),
            ("/llm/", "llm_provider"),
        )
        stage = "unknown"
        for marker, candidate in stage_rules:
            if any(marker in path for _, path in normalized):
                stage = candidate
                break

        project_frames = [
            (frame, path)
            for frame, path in normalized
            if "/korgan_legal_ai/" in path
        ]
        selected = project_frames[-1][0] if project_frames else (frames[-1] if frames else None)
        if selected is None:
            location = "unknown"
        else:
            path = selected.filename.replace("\\", "/")
            marker = "/korgan_legal_ai/"
            relative = f"korgan_legal_ai/{path.split(marker, maxsplit=1)[1]}" if marker in path else path.rsplit("/", maxsplit=1)[-1]
            location = f"{relative}:{selected.name}:{selected.lineno}"

        cause = exc.__cause__ or exc.__context__
        cause_type = type(cause).__name__ if cause is not None else "none"
        return stage, location, cause_type

    @staticmethod
    def _language_markup() -> dict[str, Any]:
        return {
            "inline_keyboard": [[
                {"text": "Русский", "callback_data": "lang:ru"},
                {"text": "Қазақша", "callback_data": "lang:kk"},
            ]]
        }

    def _privacy_markup(self, language: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [[
                {"text": text(language, "privacy_accept"), "callback_data": "consent:accept"},
                {"text": text(language, "privacy_decline"), "callback_data": "consent:decline"},
            ]]
        }

    def _menu_markup(self, language: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [[
                {"text": text(language, "claim_button"), "callback_data": "flow:claim"}
            ]]
        }

    def _send_language(self, user_id: int, chat_id: int, session: TelegramSession) -> None:
        session.state = SessionState.LANGUAGE
        self.sessions.save(user_id, session)
        self.api.send_message(
            chat_id,
            text(session.language, "choose_language"),
            reply_markup=self._language_markup(),
        )

    def _send_privacy(self, user_id: int, chat_id: int, session: TelegramSession) -> None:
        session.state = SessionState.PRIVACY
        self.sessions.save(user_id, session)
        self.api.send_message(
            chat_id,
            text(session.language, "privacy"),
            reply_markup=self._privacy_markup(session.language),
        )

    def _require_consent(self, user_id: int, chat_id: int, session: TelegramSession) -> bool:
        """Gate every legal action behind consent to the *current* privacy version.

        A superseded policy version must not keep holding unfinished case text, so the buffer
        is dropped before the session is written back and the user is asked to accept again.
        """
        if session.consent_version == self.privacy_version:
            return True
        session.case_buffer = None
        self.api.send_message(chat_id, text(session.language, "consent_required"))
        self._send_privacy(user_id, chat_id, session)
        return False

    def _send_menu(self, user_id: int, chat_id: int, session: TelegramSession) -> None:
        if not self._require_consent(user_id, chat_id, session):
            return
        session.state = SessionState.MENU
        self.sessions.save(user_id, session)
        self.api.send_message(
            chat_id,
            text(session.language, "menu"),
            reply_markup=self._menu_markup(session.language),
        )

    def _start_claim(self, user_id: int, chat_id: int, session: TelegramSession) -> None:
        if not self._require_consent(user_id, chat_id, session):
            return
        session.case_buffer = None
        session.state = SessionState.AWAITING_CLAIM
        self.sessions.save(user_id, session)
        self.api.send_message(chat_id, text(session.language, "claim_prompt"))

    @staticmethod
    def _command(value: str) -> str | None:
        if not value.startswith("/"):
            return None
        return value.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()

    def _handle_command(
        self,
        *,
        user_id: int,
        chat_id: int,
        command: str,
        session: TelegramSession,
    ) -> None:
        if command == "/start":
            language = session.language
            session = self.sessions.reset(user_id, language=language)
            self._send_language(user_id, chat_id, session)
        elif command == "/language":
            self._send_language(user_id, chat_id, session)
        elif command == "/privacy":
            self._send_privacy(user_id, chat_id, session)
        elif command == "/menu":
            self._send_menu(user_id, chat_id, session)
        elif command == "/cancel":
            session = self.sessions.clear_case(user_id)
            self.api.send_message(chat_id, text(session.language, "cancelled"))
            if session.consent_version == self.privacy_version:
                self._send_menu(user_id, chat_id, session)
        elif command == "/help":
            self.api.send_message(chat_id, text(session.language, "help"))
        else:
            self.api.send_message(chat_id, text(session.language, "help"))

    def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = sender.get("id")
        if not isinstance(chat_id, int) or not isinstance(user_id, int):
            return

        session = self.sessions.get(user_id)
        if chat.get("type") != "private":
            self.api.send_message(chat_id, text(session.language, "private_only"))
            return

        value = message.get("text")
        if not isinstance(value, str) or not value.strip():
            self.api.send_message(chat_id, text(session.language, "empty"))
            return
        value = value.strip()

        command = self._command(value)
        if command is not None:
            self._handle_command(
                user_id=user_id,
                chat_id=chat_id,
                command=command,
                session=session,
            )
            return

        if not self._require_consent(user_id, chat_id, session):
            return

        if session.state not in {
            SessionState.AWAITING_CLAIM,
            SessionState.AWAITING_CLARIFICATION,
        }:
            self._send_menu(user_id, chat_id, session)
            return

        existing = session.case_buffer or ""
        candidate = value if not existing else f"{existing}\n\nДополнение пользователя:\n{value}"
        if len(candidate) > self.max_case_chars:
            self.api.send_message(
                chat_id,
                text(session.language, "too_long", limit=self.max_case_chars),
            )
            return

        session.case_buffer = candidate
        self.sessions.save(user_id, session)
        self.api.send_message(chat_id, text(session.language, "processing"))
        try:
            result = self.engine.process(candidate)
        except ClarificationRequired as exc:
            logger.info(
                "legal_request_needs_clarification stage=fact_lock question_count=%d",
                len(exc.questions),
            )
            session.state = SessionState.AWAITING_CLARIFICATION
            self.sessions.save(user_id, session)
            questions = "\n".join(f"• {question}" for question in exc.questions)
            self.api.send_message(
                chat_id,
                text(session.language, "clarification", questions=questions),
            )
            return
        except LegalQABlocked:
            logger.warning("legal_request_blocked stage=final_qa reason=qa_blocked")
            self.sessions.clear_case(user_id)
            self.api.send_message(chat_id, text(session.language, "qa_blocked"))
            return
        except NotImplementedError:
            logger.warning("legal_request_blocked stage=task_router reason=unsupported_workflow")
            self.sessions.clear_case(user_id)
            self.api.send_message(chat_id, text(session.language, "unsupported"))
            return
        except Exception as exc:
            stage, location, cause_type = self._safe_exception_diagnostics(exc)
            logger.error(
                "legal_request_failed stage=%s exception_type=%s cause_type=%s location=%s",
                stage,
                type(exc).__name__,
                cause_type,
                location,
            )
            self.sessions.clear_case(user_id)
            self.api.send_message(chat_id, text(session.language, "internal_error"))
            return

        session = self.sessions.clear_case(user_id)
        document = result.document
        qa = getattr(result, "qa", None)
        qa_passed = getattr(qa, "passed", "unknown")
        logger.info(
            "legal_request_completed readiness=%s needs_verification_count=%d qa_passed=%s",
            document.readiness.value,
            len(document.needs_verification),
            qa_passed,
        )
        self.api.send_message(
            chat_id,
            text(session.language, "result_header", readiness=document.readiness.value),
        )
        if document.needs_verification:
            self.api.send_message(
                chat_id,
                text(
                    session.language,
                    "needs",
                    items=", ".join(document.needs_verification),
                ),
            )
        else:
            self.api.send_message(chat_id, text(session.language, "no_needs"))
        self.api.send_message(chat_id, document.text)
        self._send_menu(user_id, chat_id, session)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        query_id = callback.get("id")
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        user_id = sender.get("id")
        chat_id = chat.get("id")
        data = callback.get("data")
        if isinstance(query_id, str):
            self.api.answer_callback_query(query_id)
        if not isinstance(user_id, int) or not isinstance(chat_id, int) or not isinstance(data, str):
            return

        session = self.sessions.get(user_id)
        if chat.get("type") != "private":
            self.api.send_message(chat_id, text(session.language, "private_only"))
            return

        if data in {"lang:ru", "lang:kk"}:
            session.language = data.split(":", maxsplit=1)[1]
            self._send_privacy(user_id, chat_id, session)
            return
        if data == "consent:accept":
            session.consent_version = self.privacy_version
            session.case_buffer = None
            self._send_menu(user_id, chat_id, session)
            return
        if data == "consent:decline":
            language = session.language
            self.sessions.delete(user_id)
            self.api.send_message(chat_id, text(language, "privacy_declined"))
            return
        if data == "flow:claim":
            self._start_claim(user_id, chat_id, session)
            return
        if data == "menu":
            self._send_menu(user_id, chat_id, session)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if isinstance(message, dict):
            self._handle_message(message)
            return
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._handle_callback(callback)

    def run_forever(self, *, stop_event: Event | None = None) -> None:
        stopper = stop_event or Event()
        me = self.api.get_me()
        logger.info("Telegram runtime starting", extra={"bot_id": me.get("id")})
        self.api.delete_webhook(drop_pending_updates=False)
        self.api.set_my_commands(BOT_COMMANDS)

        offset: int | None = None
        while not stopper.is_set():
            try:
                updates = self.api.get_updates(
                    offset=offset,
                    timeout_seconds=self.poll_timeout_seconds,
                )
                for update in updates:
                    update_id = update.get("update_id")
                    try:
                        self.handle_update(update)
                    except Exception as exc:
                        # One update that cannot be handled must never block the queue: without
                        # confirming the offset Telegram redelivers it forever and the bot stops
                        # serving every other user. Nothing is released to the user here, so the
                        # legal path stays fail-closed while the transport keeps running.
                        logger.error(
                            "Telegram update failed safely: %s",
                            type(exc).__name__,
                        )
                    finally:
                        if isinstance(update_id, int):
                            offset = update_id + 1
            except Exception as exc:
                logger.error("Telegram polling iteration failed safely: %s", type(exc).__name__)
                stopper.wait(2.0)
