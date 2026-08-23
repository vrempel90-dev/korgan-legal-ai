from __future__ import annotations

import base64
import logging
from typing import Any

from korgan.claim_quality_hotfix import ProductionClaimService
from korgan.legal_types import ClaimDraft, ExtractedDocument, LegalResearch, VerificationStatus
from korgan.openai_legal import OpenAILegalService, _CLAIM_SCHEMA, _EXTRACT_SCHEMA

LOGGER = logging.getLogger(__name__)
_INSTALLED = False
_ORIGINAL_EXTRACT = OpenAILegalService.extract_document
_ORIGINAL_DRAFT = ProductionClaimService.draft_claim

_DEMAND_MARKER = "ТРЕБОВАНИЕ ИЗ ДОКУМЕНТА:"


def _claim_payload(draft: ClaimDraft) -> dict[str, Any]:
    return {
        "title": draft.title,
        "court": draft.court,
        "claimant": list(draft.claimant),
        "defendant": list(draft.defendant),
        "price_of_claim": draft.price_of_claim,
        "facts": list(draft.facts),
        "legal_basis": list(draft.legal_basis),
        "requests": list(draft.requests),
        "attachments": list(draft.attachments),
        "verification_notes": list(draft.verification_notes),
    }


def _has_uploaded_pretrial(case_context: str) -> bool:
    text = (case_context or "").lower().replace("ё", "е")
    return "файл:" in text and any(token in text for token in ("претенз", "талап хат", "сотқа дейінгі талап"))


async def _claim_aware_extract_document(
    self: OpenAILegalService,
    data: bytes,
    filename: str,
    mime_type: str | None = None,
) -> ExtractedDocument:
    """Extract uploaded evidence without losing the operative demands of a pretrial claim.

    The old generic extractor often summarized a pretrial demand but omitted the
    exact requested performance. That left later claim drafting without the
    client's already-stated remedy and could produce an empty prayer section.
    Keep one model call, but make those demands first-class facts in the existing
    `important_facts` field so every downstream service sees them in case_context.
    """
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    prompt = (
        "Извлеки из документа только факты, видимые в самом документе. Не делай правовых выводов из памяти. "
        "Особенно найди стороны, ИИН/БИН/номера, адреса и контакты если видны, даты, суммы, обязательства, "
        "нарушения условий, доказательства и важные факты для возможного судебного спора. "
        "КРИТИЧЕСКОЕ ПРАВИЛО ДЛЯ ПРЕТЕНЗИЙ/ТРЕБОВАНИЙ/ТАЛАП ХАТ: не сворачивай просительную часть в общую выжимку. "
        "Каждое конкретное требование автора документа (вернуть деньги, оплатить долг, выполнить работу, передать имущество, "
        "устранить нарушение и т.п.) перенеси ОТДЕЛЬНЫМ элементом important_facts и начинай этот элемент дословным маркером "
        f"«{_DEMAND_MARKER} ». Сохрани указанную в документе сумму, срок, адресата и предмет требования без изменения смысла. "
        "Если в претензии несколько требований — сохрани каждое отдельным элементом. "
        "Также зафиксируй факт и дату направления/получения претензии и ответ на неё, только если это видно в документе. "
        "Не придумывай отсутствующие сведения и явно перечисли всё нечитабельное или отсутствующее."
    )

    if suffix in {"jpg", "jpeg", "png", "webp"} or (mime_type or "").startswith("image/"):
        media = mime_type or ("image/png" if suffix == "png" else "image/jpeg")
        encoded = base64.b64encode(data).decode("ascii")
        content: list[dict[str, Any]] = [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{media};base64,{encoded}", "detail": "high"},
            ],
        }]
    elif suffix == "docx":
        text = self._docx_text(data)
        content = [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": f"{prompt}\n\nТекст DOCX:\n{text[:self.settings.max_case_text_chars]}",
            }],
        }]
    elif suffix == "txt":
        text = data.decode("utf-8", errors="replace")
        content = [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": f"{prompt}\n\nТекст файла:\n{text[:self.settings.max_case_text_chars]}",
            }],
        }]
    elif suffix == "pdf" or (mime_type or "") == "application/pdf":
        encoded = base64.b64encode(data).decode("ascii")
        content = [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_file", "filename": filename, "file_data": encoded},
            ],
        }]
    else:
        raise ValueError("Поддерживаются PDF, DOCX, TXT, JPG, JPEG, PNG и WEBP.")

    payload, _ = await self._structured_response(
        model=self.settings.openai_vision_model,
        instructions=(
            "Ты модуль извлечения фактов KORGAN Legal AI для Республики Казахстан. "
            "Не придумывай отсутствующие реквизиты. Для претензии обязательно сохрани каждое явно написанное требование "
            f"в important_facts с маркером «{_DEMAND_MARKER} ». "
            "Если поле не видно — оставь список пустым или добавь его в missing_or_unclear."
        ),
        content=content,
        schema_name="korgan_document_extract",
        schema=_EXTRACT_SCHEMA,
    )
    return ExtractedDocument(filename=filename, **payload)


async def _draft_claim_with_uploaded_pretrial_recovery(
    self: ProductionClaimService,
    case_context: str,
    research: LegalResearch,
    language: str = "ru",
) -> ClaimDraft:
    draft = await _ORIGINAL_DRAFT(self, case_context, research, language=language)
    if draft.requests or not _has_uploaded_pretrial(case_context):
        return draft

    LOGGER.warning("UPLOADED_PRETRIAL_EMPTY_PRAYER_RECOVERY start")
    try:
        repaired_payload = await self._quality_repair(
            schema_name="korgan_uploaded_pretrial_claim_recovery",
            schema=_CLAIM_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=_claim_payload(draft),
            issues=[
                "Просительная часть иска пуста, хотя в материалах есть загруженная досудебная претензия. "
                "Нужно использовать конкретные требования из этой претензии как заявленную пользователем позицию."
            ],
            language=language,
            document_label="исковое заявление по загруженной претензии",
            extra_rules=(
                "8. Загруженная претензия — материал пользователя и источник фактов/его заявленных требований, а не образец и не внешняя правовая норма.\n"
                f"9. В первую очередь найди в МАТЕРИАЛАХ элементы с маркером «{_DEMAND_MARKER}» и перенеси их смысл в раздел ПРОШУ СУД.\n"
                "10. Сформулируй требование как исполнимую просьбу к суду, используя только стороны, суммы, предмет и обстоятельства из материалов. Не придумывай новые суммы, даты, договоры или последствия.\n"
                "11. Не удаляй основное требование только потому, что отдельный реквизит подачи, госпошлина, точное наименование суда или дополнительное требование ещё требует уточнения. Такие недостатки оставляй в verification_notes.\n"
                "12. Если правовая опора для требования ещё не прошла source-bound проверку, не выдумывай статью: сохрани фактическое требование и оставь документ в NEEDS_VERIFICATION/PRELIMINARY."
            ),
        )
    except Exception:
        LOGGER.exception("UPLOADED_PRETRIAL_EMPTY_PRAYER_RECOVERY failed")
        return draft

    repaired = ClaimDraft(
        status=VerificationStatus.NEEDS_VERIFICATION,
        source_urls=list(research.source_urls),
        **repaired_payload,
    )
    if repaired.requests:
        LOGGER.info("UPLOADED_PRETRIAL_EMPTY_PRAYER_RECOVERY ok requests=%d", len(repaired.requests))
        return repaired

    LOGGER.warning("UPLOADED_PRETRIAL_EMPTY_PRAYER_RECOVERY still_empty")
    return draft


def install_claim_upload_material_bridge() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    OpenAILegalService.extract_document = _claim_aware_extract_document  # type: ignore[assignment]
    ProductionClaimService.draft_claim = _draft_claim_with_uploaded_pretrial_recovery  # type: ignore[assignment]
    _INSTALLED = True
    LOGGER.info("Installed claim upload material bridge: pretrial demands -> claim prayer")
