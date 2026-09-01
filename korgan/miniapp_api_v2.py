from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Reuse the already isolated Mini App runtime. Importing miniapp_api imports
# strict_bot, which installs the exact same production legal hardening layers
# without starting Telegram polling.
from korgan import ai_cost
from korgan import legal_calc
from korgan import miniapp_api as legacy
from korgan.asgi_lifespan import add_lifespan
from korgan.claim_docx import build_claim_docx
from korgan.contract_docx import build_contract_docx
from korgan.document_quality import assess_document_quality, rendered_docx_blockers
from korgan.legal_types import VerificationStatus
from korgan.pretrial import build_pretrial_docx
from korgan.pretrial_response import build_pretrial_response_docx
from korgan.response_docx import build_response_to_claim_docx

app = FastAPI(title="KORGAN Mini App API", version="0.7.0")
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

settings = legacy.settings
service = legacy.service
store = legacy.store
_DOCUMENT_TYPES = set(legacy._DOCUMENT_TYPES)
_ALLOWED_UPLOAD_EXTENSIONS = set(legacy._ALLOWED_UPLOAD_EXTENSIONS)
_MAX_UPLOAD_BYTES = legacy._MAX_UPLOAD_BYTES
_MAX_CONVERSATION_MESSAGES = legacy._MAX_CONVERSATION_MESSAGES
_generation_locks: dict[tuple[str, str], asyncio.Lock] = {}


class CaseRequest(BaseModel):
    # Empty description is allowed because the user may create a case entirely
    # from uploaded documents. No synthetic placeholder text is inserted into
    # the factual context.
    description: str = Field(default="", max_length=60000)
    document_type: str = "claim"
    language: str = "ru"


class GenerateRequest(BaseModel):
    case_id: str
    document_type: str = "claim"
    language: str = "ru"


async def _startup() -> None:
    await store.open()


async def _shutdown() -> None:
    await store.close()


add_lifespan(app, startup=_startup, shutdown=_shutdown)


def _status_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip()


def _is_verified(value: Any) -> bool:
    return _status_value(value).upper() == VerificationStatus.VERIFIED.value.upper()


def _public_case(item: dict[str, Any], *, include_conversation: bool = False) -> dict[str, Any]:
    return legacy._public_case(item, include_conversation=include_conversation)


def _case_context(case: dict[str, Any]) -> str:
    """Build legal context only from user-supplied facts and source materials.

    Each uploaded material keeps its filename as a source boundary. AI answers
    remain UI history and are never recycled into legal facts.
    """
    chunks: list[str] = []
    description = str(case.get("description") or "").strip()
    if description:
        chunks.append("Факты, сообщённые пользователем:\n" + description)

    material_chunks: list[str] = []
    for item in case.get("materials") or []:
        context = str(item.get("context") or "").strip()
        if not context:
            continue
        filename = str(item.get("filename") or "material").strip()
        material_chunks.append(f"ИСТОЧНИК МАТЕРИАЛА: {filename}\n{context}")
    if material_chunks:
        chunks.append("Материалы дела:\n" + "\n\n---\n\n".join(material_chunks))

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
    return "\n\n---\n\n".join(chunks)


def _append_unique_notes(draft: Any, issues: list[str]) -> list[str]:
    notes = [str(item) for item in list(getattr(draft, "verification_notes", []) or []) if str(item).strip()]
    for issue in issues:
        value = str(issue).strip()
        if value and value not in notes:
            notes.append(value)
    draft.verification_notes = notes
    return notes


def _release_metadata(document_type: str, context: str, research: Any, draft: Any) -> dict[str, Any]:
    """Apply the same fail-closed readiness semantics used by the production core."""
    quality_score: float | None = None
    quality_issues: list[str] = []

    # Все пять типов проходят один и тот же численный gate. Раньше претензия и
    # ответ на претензию оценивались только списком замечаний, без порога:
    # «готов» и «сойдёт» для них ничем не различались.
    kind = {
        "claim": "claim",
        "contract": "contract",
        "response": "response_to_claim",
        "pretrial": "pretrial",
        "pretrial_response": "pretrial_response",
    }.get(document_type)
    if kind is not None:
        report = assess_document_quality(kind, context, research, draft)
        quality_score = report.score
        quality_issues = report.repair_issues(limit=20)
        if not report.ready:
            _append_unique_notes(draft, quality_issues)

    notes = list(getattr(draft, "verification_notes", []) or [])
    research_verified = _is_verified(getattr(research, "status", None))
    draft_verified = _is_verified(getattr(draft, "status", None))
    quality_ready = not quality_issues
    if quality_score is not None:
        quality_ready = quality_score >= 10.0 and not quality_issues

    filing_ready = bool(research_verified and draft_verified and quality_ready and not notes)
    if filing_ready:
        draft.status = VerificationStatus.VERIFIED
    else:
        draft.status = VerificationStatus.NEEDS_VERIFICATION

    return {
        "filing_ready": filing_ready,
        "release_status": "verified" if filing_ready else "preliminary",
        "quality_score": quality_score,
        "quality_issues": quality_issues,
        "verification_notes": list(getattr(draft, "verification_notes", []) or []),
    }


async def _generate(document_type: str, context: str, language: str) -> tuple[Any, bytes, str, dict[str, Any]]:
    if document_type == "claim":
        research = await service.research_case(context, language=language)
        draft = await service.draft_claim(context, research, language=language)
        meta = _release_metadata(document_type, context, research, draft)
        file_bytes = build_claim_docx(draft)
        filename = "KORGAN_iskovoe_zayavlenie.docx"
    elif document_type == "contract":
        research = await legacy._method("research_contract")(context, language=language)
        draft = await legacy._method("draft_contract")(context, research, language=language)
        meta = _release_metadata(document_type, context, research, draft)
        file_bytes = build_contract_docx(draft)
        filename = "KORGAN_dogovor.docx"
    elif document_type == "response":
        research = await legacy._method("research_response_to_claim")(context, language=language)
        draft = await legacy._method("draft_response_to_claim")(context, research, language=language)
        meta = _release_metadata(document_type, context, research, draft)
        file_bytes = build_response_to_claim_docx(draft)
        filename = "KORGAN_otzyv_na_isk.docx"
    elif document_type == "pretrial":
        research = await legacy._method("research_pretrial")(context, language=language)
        draft = await legacy._method("draft_pretrial")(context, research, language=language)
        meta = _release_metadata(document_type, context, research, draft)
        file_bytes = build_pretrial_docx(draft, language=language)
        filename = "KORGAN_dosudebnaya_pretenziya.docx"
    elif document_type == "pretrial_response":
        research = await legacy._method("research_pretrial_response")(context, language=language)
        draft = await legacy._method("draft_pretrial_response")(context, research, language=language)
        meta = _release_metadata(document_type, context, research, draft)
        file_bytes = build_pretrial_response_docx(draft, language=language)
        filename = "KORGAN_otvet_na_pretenziyu.docx"
    else:
        raise HTTPException(status_code=400, detail="Unsupported document type")

    if meta["filing_ready"]:
        blockers = rendered_docx_blockers(file_bytes, ready_expected=True)
        if blockers:
            raise HTTPException(
                status_code=422,
                detail="Финальный Word не прошёл проверку целостности: " + str(blockers[0]),
            )
    return draft, file_bytes, filename, meta


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "korgan-miniapp-api",
        "version": "0.7.0",
        "storage": "postgres" if store.pool is not None else "memory",
        "state_encryption": "AES-256-GCM",
        "legal_runtime": "strict_bot",
        "word_quality_target": "10/10",
        "preliminary_fallback": True,
        # Кто из провайдеров реально отвечает. Без этого поля смена провайдера
        # была бы невидимой в проде: ключ есть в переменных окружения, а
        # подтвердить, что запрос ушёл в Anthropic, а не тихо откатился на
        # OpenAI из-за неустановленного SDK, было бы нечем.
        "ai_provider": settings.active_ai_provider,
        # Какой именно commit отвечает. Railway подставляет SHA сам при сборке
        # из GitHub. Без этого поля «деплой заехал» проверялось по тому, что
        # сервис вообще отвечает, — но так неотличимы новая версия и живая
        # старая, если ответ /health от изменений не зависит. Пустая строка
        # означает запуск не из Railway (локально, в тестах), а не сбой.
        "commit": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
        # Свежесть справочника ставок. Таблица базовой ставки НБ РК кончается
        # накануне следующего заседания, и после этой даты неустойка честно не
        # считается. Отказ правильный, но безмолвный: без этого поля о нём
        # узнавали бы по маркеру «требует проверки» в документе клиента.
        "legal_rates": legal_calc.rates_freshness(),
        # Фактический расход, измеренный по ответам провайдера. До этого
        # monthly_ai_budget_usd попадал только в текст лог-сообщения, и
        # «бюджета хватит на четыре месяца» нельзя было ни подтвердить, ни
        # опровергнуть. Поле называется «since_start», потому что счётчик
        # живёт в памяти процесса и обнуляется при рестарте.
        "ai_cost": ai_cost.METER.snapshot(),
    }


@app.post("/miniapp/consent")
async def set_consent(
    payload: legacy.ConsentRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    return await legacy.set_consent(payload, x_telegram_init_data)


@app.get("/miniapp/cases")
async def list_cases(x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
    cases = list(state["cases"].values())
    return {"cases": [_public_case(item) for item in reversed(cases)]}


@app.get("/miniapp/cases/{case_id}")
async def get_case(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
    case = state["cases"].get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"case": _public_case(case, include_conversation=True)}


@app.get("/miniapp/cases/{case_id}/document")
async def get_document(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
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
        "filing_ready": bool(case.get("filing_ready")),
        "release_status": str(case.get("release_status") or "preliminary"),
        "quality_score": case.get("quality_score"),
        "quality_issues": list(case.get("quality_issues") or []),
    }


@app.post("/miniapp/cases")
async def create_case(payload: CaseRequest, x_telegram_init_data: str = Header(default="")) -> dict[str, Any]:
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
    document_type = payload.document_type.strip().lower()
    if document_type not in _DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Выберите поддерживаемый тип документа")

    description = payload.description.strip()
    digest = hashlib.sha256(f"{user_id}:{description}:{time.time_ns()}".encode()).hexdigest()[:12]
    case_id = f"KOR-{digest.upper()}"
    item = {
        "id": case_id,
        "description": description,
        "document_type": document_type,
        "language": "kk" if payload.language == "kk" else "ru",
        "status": "created",
        "materials": [],
        "conversation": [],
        "filing_ready": False,
        "release_status": "not_generated",
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
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
    case = state["cases"].get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    filename = (file.filename or "material").strip()
    if legacy._extension(filename) not in _ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Поддерживаются PDF, DOCX, TXT, JPG, JPEG, PNG и WEBP")
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 20 МБ")
    if not data:
        raise HTTPException(status_code=400, detail="Пустой файл")

    digest = hashlib.sha256(data).hexdigest()
    materials = list(case.get("materials") or [])
    duplicate = next((item for item in materials if item.get("sha256") == digest), None)
    if duplicate is not None:
        return {
            "ok": True,
            "duplicate": True,
            "case": _public_case(case, include_conversation=True),
            "preview": str(duplicate.get("context") or "")[:1800],
        }

    try:
        extracted = await service.extract_document(data, filename, file.content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Не удалось разобрать материал") from exc

    extracted_context = extracted.as_context()
    materials.append({
        "filename": filename,
        "content_type": file.content_type or "",
        "size": len(data),
        "sha256": digest,
        "context": extracted_context,
    })
    case["materials"] = materials[-settings.max_case_documents :]
    case["status"] = "materials_ready"
    case["filing_ready"] = False
    case["release_status"] = "not_generated"
    # A changed evidence set invalidates any previously generated Word document.
    for key in (
        "document_base64", "filename", "verification_status", "verification_notes",
        "quality_score", "quality_issues", "title",
    ):
        case.pop(key, None)
    await store.save(user_id, state)
    return {
        "ok": True,
        "duplicate": False,
        "case": _public_case(case, include_conversation=True),
        "preview": extracted_context[:1800],
    }


@app.post("/miniapp/consultation")
async def consultation(
    payload: legacy.ConsultationRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
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
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._require_consent(user_id)
    case = state["cases"].get(payload.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    document_type = str(case.get("document_type") or payload.document_type or "claim")
    if document_type not in _DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")

    context = _case_context(case)
    if not context.strip():
        raise HTTPException(status_code=422, detail="Добавьте описание ситуации или загрузите материалы дела")

    lock_key = (user_id, payload.case_id)
    lock = _generation_locks.setdefault(lock_key, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="Документ уже формируется")

    async with lock:
        language = "kk" if str(case.get("language") or payload.language) == "kk" else "ru"
        draft, file_bytes, filename, meta = await _generate(document_type, context, language)
        case.update({
            # Keep the existing frontend-compatible status while exposing an
            # explicit filing_ready/release_status distinction.
            "status": "document_ready",
            "title": getattr(draft, "title", "") or filename,
            "verification_status": _status_value(getattr(draft, "status", None)),
            "verification_notes": list(meta["verification_notes"]),
            "quality_score": meta["quality_score"],
            "quality_issues": list(meta["quality_issues"]),
            "filing_ready": bool(meta["filing_ready"]),
            "release_status": str(meta["release_status"]),
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
        "quality_score": case["quality_score"],
        "quality_issues": case["quality_issues"],
        "filing_ready": case["filing_ready"],
        "release_status": case["release_status"],
        "filename": case["filename"],
        "document_base64": case["document_base64"],
    }


@app.delete("/miniapp/cases/{case_id}")
async def delete_case(case_id: str, x_telegram_init_data: str = Header(default="")) -> dict[str, bool]:
    user_id = legacy._identity(x_telegram_init_data)
    state = await legacy._state(user_id)
    state["cases"].pop(case_id, None)
    await store.save(user_id, state)
    _generation_locks.pop((user_id, case_id), None)
    return {"ok": True}


@app.delete("/miniapp/me")
async def delete_me(x_telegram_init_data: str = Header(default="")) -> dict[str, bool]:
    user_id = legacy._identity(x_telegram_init_data)
    await store.delete(user_id)
    for key in [key for key in _generation_locks if key[0] == user_id]:
        _generation_locks.pop(key, None)
    return {"ok": True}
