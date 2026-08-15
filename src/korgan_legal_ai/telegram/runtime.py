from __future__ import annotations

import logging
import traceback
from threading import Event
from typing import Any

from korgan_legal_ai.documents import DocumentExtractionError, OpenAIDocumentExtractor
from korgan_legal_ai.domain.exceptions import ClarificationRequired, LegalQABlocked
from korgan_legal_ai.orchestration.engine import LegalEngine
from korgan_legal_ai.telegram.localization import text
from korgan_legal_ai.telegram.session import SessionState, SessionStore, TelegramSession
from korgan_legal_ai.telegram.word_export import build_claim_docx

logger = logging.getLogger(__name__)

PRIVACY_VERSION_DEFAULT = "2026-08-15-v3"

BOT_COMMANDS = [
    {"command": "start", "description": "Начать работу"},
    {"command": "menu", "description": "Главное меню"},
    {"command": "language", "description": "Язык интерфейса"},
    {"command": "privacy", "description": "Обработка данных"},
    {"command": "cancel", "description": "Отменить текущий запрос"},
    {"command": "help", "description": "Помощь"},
]

_ALLOWED_DOCUMENT_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/jpeg",
    "image/png",
}
_EXTENSION_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
_RESERVED_EVIDENCE_MARKERS = (
    "[DOCUMENT",
    "[PAGE",
    "[VISUAL_TRANSCRIPTION_REQUIRES_CONFIRMATION]",
    "[OCR_UNCERTAIN]",
)


class TelegramRuntime:
    def __init__(
        self,
        *,
        api: Any,
        engine: LegalEngine,
        sessions: SessionStore,
        document_extractor: OpenAIDocumentExtractor | None = None,
        privacy_version: str = PRIVACY_VERSION_DEFAULT,
        poll_timeout_seconds: int = 30,
        max_case_chars: int = 60000,
        max_document_bytes: int = 10_000_000,
        max_documents_per_case: int = 8,
    ) -> None:
        self.api = api
        self.engine = engine
        self.sessions = sessions
        self.document_extractor = document_extractor
        self.privacy_version = privacy_version
        self.poll_timeout_seconds = poll_timeout_seconds
        self.max_case_chars = max_case_chars
        self.max_document_bytes = max_document_bytes
        self.max_documents_per_case = max_documents_per_case

    @staticmethod
    def _safe_exception_diagnostics(exc: BaseException) -> tuple[str, str, str]:
        """Return privacy-safe pipeline diagnostics without logging case text or exception text."""
        frames = traceback.extract_tb(exc.__traceback__)
        normalized = [(frame, frame.filename.replace("\\", "/")) for frame in frames]
        stage_rules = (
            ("/documents/", "document_extraction"),
            ("/fact_lock/", "fact_lock"),
            ("/router/", "task_router"),
            ("/procedural_rules/", "procedural_rules"),
            ("/research/", "legal_research"),
            ("/corpus/", "legal_research"),
            ("/procedural/", "procedural_checks"),
            ("/drafting/", "drafting"),
            ("/house_style/", "house_style"),
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
        project_frames = [(frame, path) for frame, path in normalized if "/korgan_legal_ai/" in path]
        selected = project_frames[-1][0] if project_frames else (frames[-1] if frames else None)
        if selected is None:
            location = "unknown"
        else:
            path = selected.filename.replace("\\", "/")
            marker = "/korgan_legal_ai/"
            relative = (
                f"korgan_legal_ai/{path.split(marker, maxsplit=1)[1]}"
                if marker in path
                else path.rsplit("/", maxsplit=1)[-1]
            )
            location = f"{relative}:{selected.name}:{selected.lineno}"
        cause = exc.__cause__ or exc.__context__
        return stage, location, type(cause).__name__ if cause is not None else "none"

    @staticmethod
    def _language_markup() -> dict[str, Any]:
        return {
            "inline_keyboard": [[
                {"text": "🇷🇺 Русский", "callback_data": "lang:ru"},
                {"text": "🇰🇿 Қазақша", "callback_data": "lang:kk"},
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
            "inline_keyboard": [
                [
                    {"text": text(language, "claim_button"), "callback_data": "flow:claim"},
                    {"text": text(language, "claim_docs_button"), "callback_data": "flow:documents"},
                ],
                [
                    {"text": text(language, "capabilities_button"), "callback_data": "nav:help"},
                    {"text": text(language, "language_button"), "callback_data": "nav:language"},
                ],
                [
                    {"text": text(language, "privacy_button"), "callback_data": "nav:privacy"},
                ],
            ]
        }

    def _documents_markup(self, language: str) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": text(language, "documents_actions_build"), "callback_data": "documents:build"}],
                [{"text": text(language, "documents_actions_clear"), "callback_data": "documents:clear"}],
            ]
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

    def _start_documents(self, user_id: int, chat_id: int, session: TelegramSession) -> None:
        if not self._require_consent(user_id, chat_id, session):
            return
        session.case_buffer = None
        session.state = SessionState.AWAITING_DOCUMENTS
        self.sessions.save(user_id, session)
        self.api.send_message(
            chat_id,
            text(session.language, "documents_prompt"),
            reply_markup=self._documents_markup(session.language),
        )

    @staticmethod
    def _command(value: str) -> str | None:
        if not value.startswith("/"):
            return None
        return value.split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()

    @staticmethod
    def _document_count(buffer: str | None) -> int:
        return (buffer or "").count("[DOCUMENT doc-")

    @staticmethod
    def _resolve_document_mime(document: dict[str, Any]) -> str | None:
        mime = document.get("mime_type")
        if isinstance(mime, str) and mime in _ALLOWED_DOCUMENT_MIME:
            return mime
        filename = document.get("file_name")
        if isinstance(filename, str):
            lower = filename.lower()
            for suffix, candidate in _EXTENSION_MIME.items():
                if lower.endswith(suffix):
                    return candidate
        return None

    @staticmethod
    def _safe_user_note(value: str) -> str:
        """Prevent user text from masquerading as transport-generated evidence markers."""
        safe = value
        for marker in _RESERVED_EVIDENCE_MARKERS:
            safe = safe.replace(marker, marker.replace("[", "［", 1))
        return safe

    def _append_case_text(self, session: TelegramSession, value: str) -> bool:
        existing = session.case_buffer or ""
        candidate = value if not existing else f"{existing}\n\n{value}"
        if len(candidate) > self.max_case_chars:
            return False
        session.case_buffer = candidate
        return True

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

    def _send_word_document(self, chat_id: int, session: TelegramSession, result: Any) -> None:
        if not hasattr(self.api, "send_document"):
            return
        try:
            data = build_claim_docx(result.document.text)
            case_id = getattr(getattr(result, "locked_case", None), "case_id", "")
            suffix = str(case_id)[:8] if case_id else "draft"
            self.api.send_document(
                chat_id,
                filename=f"KORGAN_isk_{suffix}.docx",
                data=data,
                caption=text(session.language, "word_ready"),
            )
        except Exception as exc:
            logger.error("word_delivery_failed exception_type=%s", type(exc).__name__)
            self.api.send_message(chat_id, text(session.language, "word_failed"))

    def _process_case(
        self,
        *,
        user_id: int,
        chat_id: int,
        session: TelegramSession,
        candidate: str,
        clarification_state: SessionState,
    ) -> None:
        self.api.send_message(chat_id, text(session.language, "processing"))
        try:
            result = self.engine.process(candidate)
        except ClarificationRequired as exc:
            logger.info(
                "legal_request_needs_clarification stage=fact_lock question_count=%d",
                len(exc.questions),
            )
            session.state = clarification_state
            session.case_buffer = candidate
            self.sessions.save(user_id, session)
            questions = "\n".join(f"• {question}" for question in exc.questions)
            self.api.send_message(chat_id, text(session.language, "clarification", questions=questions))
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
                text(session.language, "needs", items=", ".join(document.needs_verification)),
            )
        else:
            self.api.send_message(chat_id, text(session.language, "no_needs"))
        self.api.send_message(chat_id, document.text)
        self._send_word_document(chat_id, session, result)
        self._send_menu(user_id, chat_id, session)

    def _handle_document_message(
        self,
        *,
        message: dict[str, Any],
        user_id: int,
        chat_id: int,
        session: TelegramSession,
    ) -> bool:
        document = message.get("document")
        photos = message.get("photo")
        file_id: str | None = None
        mime_type: str | None = None
        reported_size: int | None = None

        if isinstance(document, dict):
            file_id_value = document.get("file_id")
            if isinstance(file_id_value, str):
                file_id = file_id_value
            mime_type = self._resolve_document_mime(document)
            size_value = document.get("file_size")
            reported_size = size_value if isinstance(size_value, int) else None
        elif isinstance(photos, list) and photos:
            photo = photos[-1] if isinstance(photos[-1], dict) else None
            if photo:
                file_id_value = photo.get("file_id")
                if isinstance(file_id_value, str):
                    file_id = file_id_value
                size_value = photo.get("file_size")
                reported_size = size_value if isinstance(size_value, int) else None
                mime_type = "image/jpeg"
        else:
            return False

        if not self._require_consent(user_id, chat_id, session):
            return True

        # If a user adds evidence while already describing/clarifying a case, keep the locked input
        # buffer and attach the document to the same matter. Starting the document path from the menu
        # still creates a fresh case via _start_documents().
        if session.state == SessionState.AWAITING_CLARIFICATION:
            session.state = SessionState.AWAITING_DOCUMENT_CLARIFICATION
            self.sessions.save(user_id, session)
            self.api.send_message(
                chat_id,
                text(session.language, "documents_prompt"),
                reply_markup=self._documents_markup(session.language),
            )
        elif session.state == SessionState.AWAITING_CLAIM:
            session.state = SessionState.AWAITING_DOCUMENTS
            self.sessions.save(user_id, session)
            self.api.send_message(
                chat_id,
                text(session.language, "documents_prompt"),
                reply_markup=self._documents_markup(session.language),
            )
        elif session.state not in {
            SessionState.AWAITING_DOCUMENTS,
            SessionState.AWAITING_DOCUMENT_CLARIFICATION,
        }:
            self._start_documents(user_id, chat_id, session)
            session = self.sessions.get(user_id)

        if file_id is None or mime_type not in _ALLOWED_DOCUMENT_MIME:
            self.api.send_message(chat_id, text(session.language, "document_unsupported"))
            return True
        if reported_size is not None and reported_size > self.max_document_bytes:
            self.api.send_message(
                chat_id,
                text(
                    session.language,
                    "document_too_large",
                    limit_mb=max(1, self.max_document_bytes // 1_000_000),
                ),
            )
            return True
        count = self._document_count(session.case_buffer)
        if count >= self.max_documents_per_case:
            self.api.send_message(
                chat_id,
                text(session.language, "document_limit", limit=self.max_documents_per_case),
            )
            return True
        if self.document_extractor is None or not hasattr(self.api, "download_file"):
            self.api.send_message(chat_id, text(session.language, "document_error"))
            return True

        self.api.send_message(chat_id, text(session.language, "document_processing"))
        if hasattr(self.api, "send_chat_action"):
            try:
                self.api.send_chat_action(chat_id, "typing")
            except Exception:
                pass

        try:
            raw = self.api.download_file(file_id, max_bytes=self.max_document_bytes)
            extracted = self.document_extractor.extract(
                source_id=f"doc-{count + 1}",
                data=raw,
                mime_type=mime_type,
            )
        except DocumentExtractionError:
            logger.warning("document_extraction_blocked reason=safe_extraction_failed")
            self.api.send_message(chat_id, text(session.language, "document_empty"))
            return True
        except Exception as exc:
            stage, location, cause_type = self._safe_exception_diagnostics(exc)
            logger.error(
                "document_ingest_failed stage=%s exception_type=%s cause_type=%s location=%s",
                stage,
                type(exc).__name__,
                cause_type,
                location,
            )
            self.api.send_message(chat_id, text(session.language, "document_error"))
            return True

        if not self._append_case_text(session, extracted.as_case_context()):
            self.api.send_message(
                chat_id,
                text(session.language, "too_long", limit=self.max_case_chars),
            )
            return True
        # Preserve the distinction that this case was already waiting for a clarification so a
        # later typed answer is immediately re-run through Fact Lock rather than treated as a note.
        if session.state != SessionState.AWAITING_DOCUMENT_CLARIFICATION:
            session.state = SessionState.AWAITING_DOCUMENTS
        self.sessions.save(user_id, session)
        self.api.send_message(
            chat_id,
            text(
                session.language,
                "document_received",
                index=count + 1,
                chars=len(extracted.text),
            ),
            reply_markup=self._documents_markup(session.language),
        )
        return True

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

        if self._handle_document_message(
            message=message,
            user_id=user_id,
            chat_id=chat_id,
            session=session,
        ):
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

        if session.state == SessionState.AWAITING_DOCUMENTS:
            safe_note = self._safe_user_note(value)
            if not self._append_case_text(session, f"[USER_NOTE]\n{safe_note}"):
                self.api.send_message(chat_id, text(session.language, "too_long", limit=self.max_case_chars))
                return
            self.sessions.save(user_id, session)
            self.api.send_message(
                chat_id,
                text(session.language, "document_note_added"),
                reply_markup=self._documents_markup(session.language),
            )
            return

        if session.state not in {
            SessionState.AWAITING_CLAIM,
            SessionState.AWAITING_CLARIFICATION,
            SessionState.AWAITING_DOCUMENT_CLARIFICATION,
        }:
            self._send_menu(user_id, chat_id, session)
            return

        existing = session.case_buffer or ""
        candidate = value if not existing else f"{existing}\n\nДополнение пользователя:\n{value}"
        if len(candidate) > self.max_case_chars:
            self.api.send_message(chat_id, text(session.language, "too_long", limit=self.max_case_chars))
            return
        session.case_buffer = candidate
        self.sessions.save(user_id, session)
        clarification_state = (
            SessionState.AWAITING_DOCUMENT_CLARIFICATION
            if session.state == SessionState.AWAITING_DOCUMENT_CLARIFICATION
            else SessionState.AWAITING_CLARIFICATION
        )
        self._process_case(
            user_id=user_id,
            chat_id=chat_id,
            session=session,
            candidate=candidate,
            clarification_state=clarification_state,
        )

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
        if data == "flow:documents":
            self._start_documents(user_id, chat_id, session)
            return
        if data == "documents:build":
            if not self._require_consent(user_id, chat_id, session):
                return
            candidate = session.case_buffer or ""
            if not candidate.strip():
                self.api.send_message(
                    chat_id,
                    text(session.language, "documents_missing"),
                    reply_markup=self._documents_markup(session.language),
                )
                return
            self._process_case(
                user_id=user_id,
                chat_id=chat_id,
                session=session,
                candidate=candidate,
                clarification_state=SessionState.AWAITING_DOCUMENT_CLARIFICATION,
            )
            return
        if data == "documents:clear":
            session = self.sessions.clear_case(user_id)
            self.api.send_message(chat_id, text(session.language, "cancelled"))
            self._start_documents(user_id, chat_id, session)
            return
        if data == "nav:help":
            self.api.send_message(chat_id, text(session.language, "help"))
            return
        if data == "nav:language":
            self._send_language(user_id, chat_id, session)
            return
        if data == "nav:privacy":
            self._send_privacy(user_id, chat_id, session)
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
                updates = self.api.get_updates(offset=offset, timeout_seconds=self.poll_timeout_seconds)
                for update in updates:
                    update_id = update.get("update_id")
                    try:
                        self.handle_update(update)
                    except Exception as exc:
                        logger.error("Telegram update failed safely: %s", type(exc).__name__)
                    finally:
                        if isinstance(update_id, int):
                            offset = update_id + 1
            except Exception as exc:
                logger.error("Telegram polling iteration failed safely: %s", type(exc).__name__)
                stopper.wait(2.0)
