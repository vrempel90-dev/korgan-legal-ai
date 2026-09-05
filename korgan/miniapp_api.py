from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qsl

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Importing strict_bot installs the same production legal hardening layers, but
# does NOT start Telegram polling because main() is protected by __main__.
from korgan import strict_bot as _production_runtime  # noqa: F401
from korgan.asgi_lifespan import add_lifespan
from korgan.claim_docx import build_claim_docx
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.config import get_settings
from korgan.document_type_routing import DOCUMENT_TYPES, resolve_document_type
from korgan.contract_docx import build_contract_docx
from korgan.document_quality import assess_document_quality, rendered_docx_blockers
from korgan.legal_types import VerificationStatus
from korgan.miniapp_store import MiniAppStore
from korgan.pretrial import build_pretrial_docx
from korgan.pretrial_response import PretrialResponseProductionService, build_pretrial_response_docx
from korgan.response_docx import build_response_to_claim_docx

app = FastAPI(title="KORGAN Mini App API", version="0.6.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://korgan-miniapp-staging-production.up.railway.app",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

settings = get_settings()
service = ClaimPipelineV2Adapter(PretrialResponseProductionService(settings))
store = MiniAppStore(
    settings.database_url,
    secret=settings.telegram_bot_token,
    retention_days=int(os.getenv("MINIAPP_RETENTION_DAYS", "30")),
)

# Набор типов задаётся один раз в `document_type_routing`: там же зафиксировано
# правило, что выбор пользователя окончателен и текстом дела не уточняется.
_DOCUMENT_TYPES = set(DOCUMENT_TYPES)
_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".webp"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_MAX_CONVERSATION_MESSAGES = 40
_INIT_DATA_MAX_AGE_SECONDS = int(os.getenv("MINIAPP_INIT_DATA_MAX_AGE_SECONDS", "86400"))
_generation_locks: dict[tuple[str, str], asyncio.Lock] = {}


class ConsultationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    case_id: str | None = None
    language: str = "ru"


class CaseRequest(BaseModel):
    description: str = Field(min_length=1, max_length=60000)
    document_type: str = "claim"
    language: str = "ru"


class GenerateRequest(BaseModel):
    case_id: str
    document_type: str = "claim"
    language: str = "ru"


class ConsentRequest(BaseModel):
    accepted: bool
    terms_version: str = "2026-08-16-v1"


async def _startup() -> None:
    await store.open()


async def _shutdown() -> None:
    await store.close()


add_lifespan(app, startup=_startup, shutdown=_shutdown)


def _validate_init_data(raw: str) -> dict[str, str]:
    if not raw:
        if os.getenv("MINIAPP_ALLOW_DEV_AUTH", "false").lower() == "true":
            return {"user": json.dumps({"id": "staging-dev"})}
        raise HTTPException(status_code=401, detail="Telegram authentication required")

    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise HTTPException(status_code=401, detail="Invalid Telegram initData")

    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid Telegram signature")

    auth_date = pairs.get("auth_date")
    if auth_date:
        try:
            age = int(time.time()) - int(auth_date)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid Telegram auth_date") from exc
        if age < -60 or age > _INIT_DATA_MAX_AGE_SECONDS:
            raise HTTPException(status_code=401, detail="Telegram authentication expired")
    return pairs


def _identity(init_data: str) -> str:
    pairs = _validate_init_data(init_data)
    try:
        user = json.loads(pairs.get("user", "{}"))
        return str(user["id"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Telegram user missing")


async def _state(user_id: str) -> dict[str, Any]:
    state = await store.load(user_id)
    state.setdefault("consent", None)
    state.setdefault("cases", {})
    return state


async def _require_consent(user_id: str) -> dict[str, Any]:
    state = await _state(user_id)
    consent = state.get("consent") or {}
    if not consent.get("accepted"):
        raise HTTPException(status_code=403, detail="Terms acceptance required")
    return state


def _public_case(item: dict[str, Any], *, include_conversation: bool = False) -> dict[str, Any]:
    hidden = {"document_base64", "materials", "conversation"}
    public = {k: v for k, v in item.items() if k not in hidden}
    public["materials_count"] = len(item.get("materials") or [])
    public["material_names"] = [str(x.get("filename") or "") for x in item.get("materials") or []]
    public["conversation_count"] = len(item.get("conversation") or [])
    public["has_document"] = bool(item.get("document_base64"))
    if include_conversation:
        public["conversation"] = list(item.get("conversation") or [])
    return public


def _case_context(case: dict[str, Any]) -> str:
    """Build drafting context only from user-supplied facts and uploaded material.

    AI consultation answers remain available as UI history, but they are never
    fed back into research/drafting as facts. This prevents a previous model
    answer from becoming self-reinforcing evidence in a later Word document.
    """
    chunks = [str(case.get("description") or "").strip()]
    materials = case.get("materials") or []
    if materials:
        chunks.append(
            "Материалы дела:\n" + "\n\n---\n\n".join(str(item.get("context") or "") for item in materials)
        )

    user_history = [
        str(item.get("text") or "").strip()
        for item in list(case.get("conversation") or [])[-20:]
        if item.get("role") == "user" and str(item.get("text") or "").strip()
    ]
    if user_history:
        chunks.append(
            "Дополнительные факты, сообщённые пользователем в консультации:\n"
            + "\n".join(f"- {text}" for text in user_history[-10:])
        )
    return "\n\n---\n\n".join(chunk for chunk in chunks if chunk)


def _extension(filename: str) -> str:
    lowered = filename.lower().strip()
    for ext in sorted(_ALLOWED_UPLOAD_EXTENSIONS, key=len, reverse=True):
        if lowered.endswith(ext):
            return ext
    return ""


def _method(name: str) -> Callable[..., Awaitable[Any]]:
    candidate = getattr(service, name, None)
    if candidate is None:
        raise HTTPException(status_code=503, detail=f"KORGAN generator unavailable: {name}")
    return candidate


async def _generate(document_type: str, context: str, language: str) -> tuple[Any, bytes, str]:
    if document_type == "claim":
        research = await service.research_case(context, language=language)
        draft = await service.draft_claim(context, research, language=language)
        return draft, build_claim_docx(draft), "KORGAN_iskovoe_zayavlenie.docx"

    if document_type == "contract":
        research = await _method("research_contract")(context, language=language)
        draft = await _method("draft_contract")(context, research, language=language)
        quality = assess_document_quality("contract", context, research, draft)
        draft.status = VerificationStatus.VERIFIED if quality.ready else VerificationStatus.NEEDS_VERIFICATION
        file_bytes = build_contract_docx(draft)
        if quality.ready and rendered_docx_blockers(file_bytes, ready_expected=True):
            raise HTTPException(status_code=422, detail="Договор не прошёл финальную проверку Word")
        return draft, file_bytes, "KORGAN_dogovor.docx"

    if document_type == "response":
        research = await _method("research_response_to_claim")(context, language=language)
        draft = await _method("draft_response_to_claim")(context, research, language=language)
        quality = assess_document_quality("response_to_claim", context, research, draft)
        draft.status = VerificationStatus.VERIFIED if quality.ready else VerificationStatus.NEEDS_VERIFICATION
        file_bytes = build_response_to_claim_docx(draft)
        if quality.ready and rendered_docx_blockers(file_bytes, ready_expected=True):
            raise HTTPException(status_code=422, detail="Отзыв не прошёл финальную проверку Word")
        return draft, file_bytes, "KORGAN_otzyv_na_isk.docx"

    if document_type == "pretrial":
        research = await _method("research_pretrial")(context, language=language)
        draft = await _method("draft_pretrial")(context, research, language=language)
        return draft, build_pretrial_docx(draft, language=language), "KORGAN_dosudebnaya_pretenziya.docx"

    if document_type == "pretrial_response":
        research = await _method("research_pretrial_response")(context, language=language)
        draft = await _method("draft_pretrial_response")(context, research, language=language)
        return draft, build_pretrial_response_docx(draft, language=language), "KORGAN_otvet_na_pretenziyu.docx"

    raise HTTPException(status_code=400, detail="Unsupported document type")


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "korgan-miniapp-api",
        "version": "0.6.1",
        "storage": "postgres" if store.pool is not None else "memory",
        "state_encryption": "AES-256-GCM",
    }


@app.post("/miniapp/consent")
async def set_consent(payload: ConsentRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _state(user_id)
    state["consent"] = payload.model_dump()
    if not payload.accepted:
        state["cases"] = {}
    await store.save(user_id, state)
    return {"ok": True, "accepted": payload.accepted, "terms_version": payload.terms_version}


@app.get("/miniapp/cases")
async def list_cases(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    cases = list(state["cases"].values())
    return {"cases": [_public_case(item) for item in reversed(cases)]}


@app.get("/miniapp/cases/{case_id}")
async def get_case(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    case = state["cases"].get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"case": _public_case(case, include_conversation=True)}


@app.get("/miniapp/cases/{case_id}/document")
async def get_document(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    case = state["cases"].get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    encoded = str(case.get("document_base64") or "")
    if not encoded:
        raise HTTPException(status_code=404, detail="Document not generated")
    return {
        "case_id": case_id,
        "filename": str(case.get("filename") or "KORGAN_document.docx"),
        "document_base64": encoded,
        "title": str(case.get("title") or ""),
        "verification_status": str(case.get("verification_status") or ""),
        "verification_notes": list(case.get("verification_notes") or []),
    }


@app.post("/miniapp/cases")
async def create_case(payload: CaseRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    # Карточка документа в Mini App и есть выбор пользователя. Описание дела в
    # том же запросе на тип не влияет: именно попытка «уточнить» выбор по тексту
    # переворачивала претензию в ответ на претензию.
    document_type = resolve_document_type(payload.document_type)
    if document_type is None:
        raise HTTPException(status_code=400, detail="Выберите поддерживаемый тип документа")
    digest = hashlib.sha256(f"{user_id}:{payload.description}:{time.time_ns()}".encode()).hexdigest()[:12]
    case_id = f"KOR-{digest.upper()}"
    item = {
        "id": case_id,
        "description": payload.description,
        "document_type": document_type,
        "language": "kk" if payload.language == "kk" else "ru",
        "status": "created",
        "materials": [],
        "conversation": [],
    }
    state["cases"][case_id] = item
    await store.save(user_id, state)
    return {"case": _public_case(item, include_conversation=True)}


@app.post("/miniapp/cases/{case_id}/materials")
async def upload_material(
    case_id: str,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    case = state["cases"].get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    filename = (file.filename or "material").strip()
    if _extension(filename) not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Поддерживаются PDF, DOCX, TXT, JPG, JPEG, PNG и WEBP")
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")

    try:
        extracted = await service.extract_document(data, filename, file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось разобрать материал") from exc

    materials = list(case.get("materials") or [])
    materials.append({"filename": filename, "content_type": file.content_type or "", "context": extracted.as_context()})
    case["materials"] = materials[-settings.max_case_documents :]
    case["status"] = "materials_ready"
    await store.save(user_id, state)
    return {"ok": True, "case": _public_case(case, include_conversation=True), "preview": extracted.as_context()[:1800]}


@app.post("/miniapp/consultation")
async def consultation(payload: ConsultationRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    case: dict[str, Any] | None = None
    case_context = ""
    if payload.case_id:
        case = state["cases"].get(payload.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        case_context = _case_context(case)

    answer, urls = await service.consult(
        payload.message,
        case_context=case_context,
        language="kk" if payload.language == "kk" else "ru",
    )
    if case is not None:
        conversation = list(case.get("conversation") or [])
        conversation.extend([
            {"role": "user", "text": payload.message, "ts": int(time.time())},
            {"role": "ai", "text": answer, "sources": list(urls or []), "ts": int(time.time())},
        ])
        case["conversation"] = conversation[-_MAX_CONVERSATION_MESSAGES:]
        await store.save(user_id, state)
    return {"answer": answer, "sources": urls}


@app.post("/miniapp/documents/generate")
async def generate_document(payload: GenerateRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = await _require_consent(user_id)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in _DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")

    lock_key = (user_id, payload.case_id)
    lock = _generation_locks.setdefault(lock_key, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="Документ уже формируется")

    async with lock:
        language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
        context = _case_context(case)
        draft, file_bytes, filename = await _generate(document_type, context, language)
        case.update({
            "status": "document_ready",
            "title": getattr(draft, "title", "") or filename,
            "verification_status": getattr(getattr(draft, "status", None), "value", str(getattr(draft, "status", ""))),
            "verification_notes": list(getattr(draft, "verification_notes", []) or []),
            "document_base64": base64.b64encode(file_bytes).decode("ascii"),
            "filename": filename,
        })
        await store.save(user_id, state)

    return {
        "case_id": payload.case_id,
        "status": case["status"],
        "title": case["title"],
        "verification_status": case["verification_status"],
        "verification_notes": case["verification_notes"],
        "filename": case["filename"],
        "document_base64": case["document_base64"],
    }


@app.delete("/miniapp/cases/{case_id}")
async def delete_case(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, bool]:
    user_id = _identity(x_telegram_init_data)
    state = await _state(user_id)
    state["cases"].pop(case_id, None)
    await store.save(user_id, state)
    _generation_locks.pop((user_id, case_id), None)
    return {"ok": True}


@app.delete("/miniapp/me")
async def delete_me(x_telegram_init_data: str = Header(default="")) -> dict[str, bool]:
    user_id = _identity(x_telegram_init_data)
    await store.delete(user_id)
    for key in [key for key in _generation_locks if key[0] == user_id]:
        _generation_locks.pop(key, None)
    return {"ok": True}
