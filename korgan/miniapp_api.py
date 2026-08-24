from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qsl

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Importing strict_bot installs the same production legal hardening layers, but
# does NOT start Telegram polling because main() is protected by __main__.
from korgan import strict_bot as _production_runtime  # noqa: F401
from korgan.claim_docx import build_claim_docx
from korgan.claim_pipeline_v2 import ClaimPipelineV2Adapter
from korgan.config import get_settings
from korgan.pretrial_response import PretrialResponseProductionService

app = FastAPI(title="KORGAN Mini App API", version="0.1.0")
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "korgan-miniapp-api"}


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
    return {"cases": [{k: v for k, v in item.items() if k != "document_base64"} for item in cases]}


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
    }
    state["cases"][case_id] = item
    return {"case": item}


@app.post("/miniapp/consultation")
async def consultation(payload: ConsultationRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = _identity(x_telegram_init_data)
    state = _require_consent(user_id)
    case_context = ""
    if payload.case_id:
        case = state["cases"].get(payload.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        case_context = str(case.get("description", ""))
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
    if payload.document_type != "claim":
        raise HTTPException(status_code=501, detail="This document type is not wired yet")

    language = "kk" if payload.language == "kk" else "ru"
    context = str(case.get("description", ""))
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
        }
    )
    return {
        "case_id": payload.case_id,
        "status": case["status"],
        "title": draft.title,
        "verification_status": case["verification_status"],
        "verification_notes": case["verification_notes"],
        "filename": "KORGAN_iskovoe_zayavlenie.docx",
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
