from __future__ import annotations

import base64
import hashlib
import io
import time
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from korgan import miniapp_api_v4 as v4

app = v4.app
core = v4.core
service = v4.service
settings = v4.settings

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MAX_DOCUMENT_CONTEXT_CHARS = 60000


class DocumentConsultationRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    case_id: str | None = None
    language: str = "ru"
    document_revision: str | None = Field(default=None, max_length=64)


def _document_bytes(case: dict[str, Any]) -> bytes:
    encoded = str(case.get("document_base64") or "").strip()
    if not encoded:
        raise HTTPException(status_code=409, detail="Сначала сформируйте документ, затем откройте консультацию по нему")
    try:
        data = base64.b64decode(encoded, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=409, detail="Текущая версия документа повреждена. Сформируйте документ заново") from exc
    if not data:
        raise HTTPException(status_code=409, detail="Текущая версия документа пуста. Сформируйте документ заново")
    return data


def _revision_from_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case_document_revision(case: dict[str, Any]) -> str:
    try:
        return _revision_from_bytes(_document_bytes(case))
    except HTTPException:
        return ""


def _extract_docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        root = ET.fromstring(xml)
    except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise HTTPException(status_code=409, detail="Не удалось прочитать текущий DOCX. Сформируйте документ заново") from exc

    paragraphs: list[str] = []
    p_tag = f"{{{_W_NS}}}p"
    t_tag = f"{{{_W_NS}}}t"
    for paragraph in root.iter(p_tag):
        text = "".join(node.text or "" for node in paragraph.iter(t_tag)).strip()
        if text:
            paragraphs.append(text)
    result = "\n".join(paragraphs).strip()
    if not result:
        raise HTTPException(status_code=409, detail="В текущем DOCX не найден текст. Сформируйте документ заново")
    return result[:_MAX_DOCUMENT_CONTEXT_CHARS]


def _document_context(case: dict[str, Any], requested_revision: str | None) -> tuple[str, str]:
    base_context = core._case_context(case)
    revision = str(requested_revision or "").strip().lower()
    if not revision:
        return base_context, ""

    data = _document_bytes(case)
    current_revision = _revision_from_bytes(data)
    if revision != current_revision:
        raise HTTPException(
            status_code=409,
            detail=(
                "Документ был обновлён после открытия консультации. "
                "Откройте актуальный документ и задайте вопрос ещё раз."
            ),
        )

    filename = str(case.get("filename") or "KORGAN_document.docx").strip()
    document_type = str(case.get("document_type") or "document").strip()
    title = str(case.get("title") or filename).strip()
    document_text = _extract_docx_text(data)

    pinned = (
        "КОНСУЛЬТАЦИЯ ПО КОНКРЕТНОЙ СГЕНЕРИРОВАННОЙ ВЕРСИИ ДОКУМЕНТА KORGAN.\n"
        f"Версия SHA-256: {current_revision}\n"
        f"Тип документа: {document_type}\n"
        f"Название: {title}\n"
        f"Файл: {filename}\n\n"
        "ТЕКСТ ЭТОЙ ВЕРСИИ ДОКУМЕНТА:\n"
        f"{document_text}\n\n"
        "Правило ответа: отвечай применительно именно к тексту этой версии. "
        "Не приписывай документу отсутствующие положения. Если находишь юридический, "
        "фактический, расчётный или процессуальный недостаток, укажи его применительно "
        "к конкретному фрагменту документа. Ссылки на законодательство РК подтверждай "
        "по официальным источникам тем же способом, что и в обычной консультации."
    )
    return "\n\n---\n\n".join(part for part in (base_context, pinned) if part.strip()), current_revision


def _install_public_revision() -> None:
    if getattr(core, "_korgan_document_revision_public_case", False):
        return
    original = core._public_case

    def public_case(item: dict[str, Any], *, include_conversation: bool = False) -> dict[str, Any]:
        payload = original(item, include_conversation=include_conversation)
        revision = _case_document_revision(item)
        if revision:
            payload["document_revision"] = revision
        return payload

    core._public_case = public_case
    core._korgan_document_revision_public_case = True


_install_public_revision()
v4._drop_route("/miniapp/consultation", "POST")


@app.post("/miniapp/consultation")
async def consultation(
    payload: DocumentConsultationRequest,
    x_telegram_init_data: str = Header(default=""),
) -> dict[str, Any]:
    identity = core.legacy._identity(x_telegram_init_data)
    state = await core.legacy._require_consent(identity)
    case: dict[str, Any] | None = None
    case_context = ""
    pinned_revision = ""

    if payload.case_id:
        case = state["cases"].get(payload.case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        case_context, pinned_revision = _document_context(case, payload.document_revision)
    elif payload.document_revision:
        raise HTTPException(status_code=400, detail="Версия документа передана без дела")

    language = "kk" if payload.language == "kk" else "ru"
    quota_id = v4._quota_user_id(identity)
    used: int | None = 0
    if settings.consultation_limit_enabled:
        used = await v4.reserve_free_consultation(quota_id, settings.free_consultations_per_day)
        if used is None:
            order = await v4.create_consultation_order(
                user_id=quota_id,
                chat_id=quota_id,
                question=payload.message,
                case_context=case_context,
                language=language,
                amount_kzt=settings.consultation_price_kzt,
            )
            pending = dict(state.get("pending_consultations") or {})
            pending[str(order.id)] = payload.case_id or ""
            state["pending_consultations"] = pending
            await core.store.save(identity, state)
            return {
                "answer": "",
                "sources": [],
                "payment_required": True,
                "free_remaining": 0,
                "document_revision": pinned_revision,
                "payment": v4._payment_payload(order),
            }

    try:
        answer, urls = await service.consult(
            payload.message,
            case_context=case_context,
            language=language,
        )
    except Exception as exc:
        if settings.consultation_limit_enabled and used:
            await v4.release_free_consultation(quota_id)
        raise HTTPException(
            status_code=502,
            detail="Не удалось выполнить юридический поиск. Бесплатный запрос не списан — попробуйте ещё раз.",
        ) from exc

    v4._append_case_conversation(case, question=payload.message, answer=answer, urls=list(urls or []))
    if case is not None:
        await core.store.save(identity, state)

    remaining = (
        max(settings.free_consultations_per_day - int(used or 0), 0)
        if settings.consultation_limit_enabled
        else None
    )
    return {
        "answer": answer,
        "sources": list(urls or []),
        "payment_required": False,
        "free_remaining": remaining,
        "document_revision": pinned_revision,
    }
