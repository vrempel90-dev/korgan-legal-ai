from __future__ import annotations

import json
import re

from korgan.fast_production_legal import ProductionOpenAILegalService as _FastBase
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.production_legal import (
    CourtDocumentQualityError,
    _apply_state_duty,
    _hard_quality_issues,
)
from korgan.repaired_production_legal import (
    _has_state_duty_payment_proof,
    _prepare_draft_for_validation,
    _restore_verified_court,
    _sync_state_duty_request,
)


_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_UNCERTAINTY_MARKERS = (
    "примерно",
    "ориентировочно",
    "точную дату надо сверить",
    "точную дату нужно сверить",
    "дату надо сверить",
    "дату нужно сверить",
    "не помню точную дату",
    "дата неточная",
    "дата не точная",
    "около ",
)
_DATE_WORD_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)
_DATE_NUM_RE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")


def _uncertain_date_variants(case_context: str) -> list[tuple[str, tuple[str, ...]]]:
    result: list[tuple[str, tuple[str, ...]]] = []
    seen: set[str] = set()
    for line in case_context.splitlines():
        lowered = line.lower()
        if not any(marker in lowered for marker in _UNCERTAINTY_MARKERS):
            continue

        for match in _DATE_WORD_RE.finditer(line):
            day = int(match.group(1))
            month_word = match.group(2).lower()
            year = int(match.group(3))
            month = _MONTHS[month_word]
            canonical = f"{day:02d}.{month:02d}.{year:04d}"
            original = match.group(0)
            if canonical not in seen:
                seen.add(canonical)
                result.append((canonical, (original, canonical, canonical.replace(".", "/"), canonical.replace(".", "-"))))

        for match in _DATE_NUM_RE.finditer(line):
            day, month, year = map(int, match.groups())
            canonical = f"{day:02d}.{month:02d}.{year:04d}"
            original = match.group(0)
            if canonical not in seen:
                seen.add(canonical)
                result.append((canonical, (original, canonical, canonical.replace(".", "/"), canonical.replace(".", "-"))))
    return result


def _mark_uncertain_dates(case_context: str, draft: ClaimDraft) -> None:
    uncertain = _uncertain_date_variants(case_context)
    if not uncertain:
        return

    def clean(text: str) -> str:
        updated = text
        for canonical, variants in uncertain:
            if "ориентировочно" in updated.lower() and canonical in updated:
                continue
            replacement = f"ориентировочно {canonical} (точная дата требует сверки по подтверждающему документу)"
            for variant in sorted(set(variants), key=len, reverse=True):
                if variant in updated:
                    updated = updated.replace(variant, replacement)
        return updated

    draft.facts = [clean(item) for item in draft.facts]
    draft.attachments = [clean(item) for item in draft.attachments]


def _remove_false_state_duty_evidence(case_context: str, draft: ClaimDraft) -> None:
    """Do not let the draft pretend a state-duty receipt exists when it was not supplied."""
    if _has_state_duty_payment_proof(case_context):
        return

    cleaned_attachments: list[str] = []
    for item in draft.attachments:
        lowered = item.lower()
        if "пошлин" in lowered and "[требует добавить" not in lowered and "[ТРЕБУЕТ ДОБАВИТЬ" not in item:
            # Generic «document confirming payment» is an assertion that the
            # attachment exists. The deterministic filing layer will add the
            # correct missing-document marker instead.
            continue
        cleaned_attachments.append(item)
    draft.attachments = cleaned_attachments

    draft.legal_basis = [
        item for item in draft.legal_basis
        if not (
            "пошлин" in item.lower()
            and "платеж" in item.lower()
            and "подтверж" in item.lower()
        )
    ]


def _deterministic_pre_qa(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    # Apply the fields that used to be added only after model QA. Doing this
    # before validation prevents false contradictions and often avoids the
    # expensive repair pass entirely.
    _apply_state_duty(case_context, draft)
    _restore_verified_court(research, draft)
    _sync_state_duty_request(draft)
    _remove_false_state_duty_evidence(case_context, draft)
    _mark_uncertain_dates(case_context, draft)
    _prepare_draft_for_validation(case_context, draft)


class ProductionOpenAILegalService(_FastBase):
    """Fast runtime v2: deterministic pre-QA repairs, then one strict validation."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        verified_block = "\n".join(f"- {x}" for x in research.verified_claims) or "нет подтвержденных выводов"
        unverified_block = "\n".join(f"- {x}" for x in research.unverified_claims) or "нет"

        prompt = (
            "Сформируй судебный проект искового заявления по праву Республики Казахстан. "
            "Верни только структуру документа для Word, без чатовых пояснений.\n\n"
            "ПРАВИЛА:\n"
            "1. Используй все известные реквизиты сторон и не выдумывай отсутствующие.\n"
            "2. Факты сохраняй ровно с той степенью точности, которая есть в материалах. Если пользователь пишет, что дата примерная или требует сверки, не превращай её в точную.\n"
            "3. Правовое обоснование — только из VERIFIED.\n"
            "4. Не утверждай наличие квитанции госпошлины или другого приложения, если его нет в материалах.\n"
            "5. Не придумывай суд. Неподтвержденный суд оставь как поле для уточнения.\n"
            "6. Не указывай сумму госпошлины самостоятельно — её считает код.\n"
            "7. В attachments перечисляй только реально имеющиеся документы; отсутствующее обязательное приложение помечай как требующее добавления.\n"
            "8. В теле иска запрещены URL, Markdown, NEEDS_VERIFICATION и чатовые советы.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified_block}\n\n"
            f"НЕ ПОДТВЕРЖДЕНО (только для verification_notes):\n{unverified_block}"
        )

        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший судебный юрист KORGAN. Составляй точный проект иска без фактических догадок. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_claim",
            schema=_CLAIM_SCHEMA,
        )

        draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **payload)
        _deterministic_pre_qa(case_context, research, draft)

        validation = await self.validate_claim(case_context, research, draft)
        blocking = list(dict.fromkeys(
            validation["critical_errors"]
            + validation["unsupported_legal_claims"]
            + _hard_quality_issues(case_context, draft)
        ))

        # Missing fields alone do not justify a costly model rewrite. The
        # preflight catches filing-critical party data before research; any
        # remaining missing field is surfaced as a review note.
        if not blocking:
            for item in validation["missing_required_fields"]:
                if item not in draft.verification_notes:
                    draft.verification_notes.append(item)
        else:
            repair_prompt = (
                "Исправь только перечисленные дефекты. Не добавляй новых фактов или права. "
                "Сохрани приблизительные даты приблизительными и не утверждай наличие квитанции госпошлины, если её нет.\n\n"
                f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
                f"VERIFIED:\n{verified_block}\n\n"
                f"ЗАМЕЧАНИЯ:\n{json.dumps(blocking, ensure_ascii=False)}\n\n"
                f"ТЕКУЩИЙ ПРОЕКТ:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            repaired_payload, _ = await self._structured_response(
                model=self.settings.openai_model,
                instructions="Ты редактор судебных документов KORGAN. Исправляй только подтвержденные дефекты, без фантазии.",
                content=[{"role": "user", "content": [{"type": "input_text", "text": repair_prompt}]}],
                schema_name="korgan_repaired_claim",
                schema=_CLAIM_SCHEMA,
            )
            draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **repaired_payload)
            _deterministic_pre_qa(case_context, research, draft)
            validation = await self.validate_claim(case_context, research, draft)
            blocking = list(dict.fromkeys(
                validation["critical_errors"]
                + validation["unsupported_legal_claims"]
                + _hard_quality_issues(case_context, draft)
            ))
            if blocking:
                raise CourtDocumentQualityError("; ".join(blocking[:12]))
            for item in validation["missing_required_fields"]:
                if item not in draft.verification_notes:
                    draft.verification_notes.append(item)

        if research.unverified_claims or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        return draft
