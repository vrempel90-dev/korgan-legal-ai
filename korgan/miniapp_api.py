from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Importing strict_bot installs the same production legal hardening layers, but
# does NOT start Telegram polling because main() is protected by __main__.
from korgan import strict_bot as _production_runtime  # noqa: F401
from korgan.claim_docx import build_claim_docx
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.config import get_settings
from korgan.pretrial_response import PretrialResponseProductionService

app = FastAPI(title="KORGAN Mini App API", version="0.3.0")
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

# Isolated staging state. It deliberately does not write into the production
# Telegram session store. A dedicated persistent Mini App store will replace
# this only after its migrations and deletion semantics are regression-tested.
_sessions: dict[str, dict[str, Any]] = {}

_CLAIM_CATEGORIES = {"claim", "debt", "consumer", "housing", "labor"}
_ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".txt", ".jpg", ".jpeg", ".png", ".webp"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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
    return pairs


def _identity(init_data: str) -> str:
    pairs = _validate_init_data(init_data)
    try:
        user = json.loads(pairs.get("user", "{}"))
        return str(user["id"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="Telegram user missing")


def _state(user_id: str) -> dict[str, Any]:
    return _sessions.setdefault(user_id, {"consent": None, "cases": {}})


def _require_consent(user_id: str) -> dict[str, Any]:
    state = _state(user_id)
    consent = state.get("consent") or {}
    if not consent.get("accepted"):
        raise HTTPException(status_code=403, detail="Terms acceptance required")
    return state


def _public_case(item: dict[str, Any]) -> dict[str, Any]:
    public = {k: v for k, v in item.items() if k not in {"document_base64", "materials"}}
    public["materials_count"] = len(item.get("materials") or [])
    public["material_names"] = [str(x.get("filename") or "") for x in item.get("materials") or []]
    return public


def _case_context(case: dict[str, Any]) -> str:
    chunks = [str(case.get("description") or "").strip()]
    materials = case.get("materials") or []
    if materials:
        chunks.append(
            "Материалы дела:\n" + "\n\n---\n\n".join(str(item.get("context") or "") for item in materials)
        )
    return "\n\n---\n\n".join(chunk for chunk in chunks if chunk)


def _extension(filename: str) -> str:
    lowered = filename.lower().strip()
    for ext in sorted(_ALLOWED_UPLOAD_EXTENSIONS, key=len, reverse=True):
        if lowered.endswith(ext):
            return ext
    return ""


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "korgan-miniapp-api", "version": "0.3.0"}


@app.post("/miniapp/consent")
async def set_consent(payload: ConsentRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _state(user_id)
    state["consent"] = payload.model_dump()
    if not payload.accepted:
        state["cases"] = {}
    return {"ok": True, "accepted": payload.accepted, "terms_version": payload.terms_version}


@app.get("/miniapp/cases")
async def list_cases(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _require_consent(user_id)
    cases = list(state["cases"].values())
    return {"cases": [_public_case(item) for item in reversed(cases)]}


@app.post("/miniapp/cases")
async def create_case(payload: CaseRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _require_consent(user_id)
    digest = hashlib.sha256(f"{user_id}:{payload.description}:{len(state['cases'])}".encode()).hexdigest()[:12]
    case_id = f"KOR-{digest.upper()}"
    item = {
        "id": case_id,
        "description": payload.description,
        "document_type": payload.document_type,
        "language": "kk" if payload.language == "kk" else "ru",
        "status": "created",
        "materials": [],
    }
    state["cases"][case_id] = item
    return {"case": _public_case(item)}


@app.post("/miniapp/cases/{case_id}/materials")
async def upload_material(
    case_id: str,
    file: UploadFile = File(...),
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _require_consent(user_id)
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
    materials.append({
        "filename": filename,
        "content_type": file.content_type or "",
        "context": extracted.as_context(),
    })
    case["materials"] = materials[-settings.max_case_documents :]
    case["status"] = "materials_ready"
    return {
        "ok": True,
        "case": _public_case(case),
        "preview": extracted.as_context()[:1800],
    }


@app.post("/miniapp/consultation")
async def consultation(payload: ConsultationRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _require_consent(user_id)
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
    return {"answer": answer, "sources": urls}


@app.post("/miniapp/documents/generate")
async def generate_document(payload: GenerateRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _require_consent(user_id)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    document_type = payload.document_type or str(case.get("document_type") or "claim")
    if document_type not in _CLAIM_CATEGORIES:
        raise HTTPException(status_code=501, detail="Этот тип документа подключается на следующем этапе")

    language = "kk" if payload.language == "kk" else "ru"
    context = _case_context(case)
    research = await service.research_case(context, language=language)
    draft = await service.draft_claim(context, research, language=language)
    file_bytes = build_claim_docx(draft)
    case.update(
        {
            "status": "document_ready",
            "title": draft.title,
            "verification_status": getattr(draft.status, "value", str(draft.status)),
            "verification_notes": list(draft.verification_notes),
            "document_base64": base64.b64encode(file_bytes).decode("ascii"),
            "filename": "KORGAN_iskovoe_zayavlenie.docx",
        }
    )
    return {
        "case_id": payload.case_id,
        "status": case["status"],
        "title": draft.title,
        "verification_status": case["verification_status"],
        "verification_notes": case["verification_notes"],
        "filename": case["filename"],
        "document_base64": case["document_base64"],
    }


@app.delete("/miniapp/cases/{case_id}")
async def delete_case(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, bool]:
    user_id = _identity(x_telegram_init_data)
    state = _state(user_id)
    state["cases"].pop(case_id, None)
    return {"ok": True}


@app.delete("/miniapp/me")
async def delete_me(x_telegram_init_data: str = Header(default="")) -> dict[str, bool]:
    user_id = _identity(x_telegram_init_data)
    _sessions.pop(user_id, None)
    return {"ok": True}
