from __future__ import annotations

import json
import re

from korgan.claim_failure import (
    ClaimFailure,
    ClaimFailureCode,
    ClaimStage,
    CourtDocumentQualityError,
)
from korgan.claim_qa_policy import apply_soft_qa_findings, split_qa_issues
from korgan.fast_production_legal import ProductionOpenAILegalService as _FastBase
from korgan.legal_routing import detect_claim_profile
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.production_legal import (
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
_AMOUNT_RE = re.compile(r"(?<!\d)(\d[\d\s ]{2,})(?:\s*(?:тенге|тг))", re.IGNORECASE)


# Модель формулирует пошлину и как «госпошлина», и как «государственная
# пошлина». Единый критерий на обе формы; korgan.state_duty_final_hotfix
# переиспользует именно его, чтобы два места не расходились между собой.
_STATE_DUTY_RE = re.compile(
    r"(?:\bгоспошлин\w*\b|\bгосударственн\w*\s+пошлин\w*\b)",
    re.IGNORECASE,
)


def _is_state_duty_request(text: str) -> bool:
    return bool(_STATE_DUTY_RE.search(text or ""))


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
            # Do not recursively replace the canonical date inside the marker we
            # just inserted; that previously produced «ориентировочно» 2–3 times.
            if "точная дата требует сверки" in updated.lower() and canonical in updated:
                continue
            replacement = f"ориентировочно {canonical} (точная дата требует сверки по подтверждающему документу)"
            for variant in sorted(set(variants), key=len, reverse=True):
                if variant in updated:
                    updated = updated.replace(variant, replacement, 1)
                    break
        return updated

    draft.facts = [clean(item) for item in draft.facts]
    draft.attachments = [clean(item) for item in draft.attachments]


def _remove_false_state_duty_evidence(case_context: str, draft: ClaimDraft) -> None:
    """Do not let a draft pretend a state-duty receipt exists before upload."""
    if _has_state_duty_payment_proof(case_context):
        return

    draft.attachments = [item for item in draft.attachments if "пошлин" not in item.lower()]
    draft.legal_basis = [
        item for item in draft.legal_basis
        if not (
            "пошлин" in item.lower()
            and "платеж" in item.lower()
            and "подтверж" in item.lower()
        )
    ]


def _normalize_state_duty_request(draft: ClaimDraft) -> None:
    """The model never controls the amount of state duty in the prayer."""
    duty = (draft.state_duty or "").strip()
    # Убираем обе формулировки, иначе «государственная пошлина» от модели
    # переживала очистку и складывалась с канонической строкой в дубль.
    draft.requests = [request for request in draft.requests if not _is_state_duty_request(request)]

    if not duty or duty.startswith("[ТРЕБУЕТ"):
        return

    amount = duty.split("(", 1)[0].strip()
    if amount:
        draft.requests.append(
            f"Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере {amount}."
        )


def _remove_unsupported_cost_amounts(case_context: str, draft: ClaimDraft) -> None:
    """Drop invented court-cost numbers while preserving factual/verified ones."""
    context_digits = {re.sub(r"\D", "", match.group(1)) for match in _AMOUNT_RE.finditer(case_context)}
    cleaned: list[str] = []
    for request in draft.requests:
        lowered = request.lower()
        if "госпошлин" in lowered:
            cleaned.append(request)
            continue
        if "судебн" not in lowered or "расход" not in lowered:
            cleaned.append(request)
            continue
        amounts = {re.sub(r"\D", "", match.group(1)) for match in _AMOUNT_RE.finditer(request)}
        if amounts and not amounts.issubset(context_digits):
            continue
        cleaned.append(request)
    draft.requests = cleaned


def _deterministic_pre_qa(case_context: str, research: LegalResearch, draft: ClaimDraft) -> None:
    # Apply everything deterministically before the expensive independent QA.
    _apply_state_duty(case_context, draft)
    _restore_verified_court(research, draft)
    _sync_state_duty_request(draft)
    _remove_false_state_duty_evidence(case_context, draft)
    _mark_uncertain_dates(case_context, draft)
    _prepare_draft_for_validation(case_context, draft)

    # _prepare_draft_for_validation may add a missing-duty placeholder to the
    # annex list. It belongs in the Telegram QA notes, not in the court annexes.
    _remove_false_state_duty_evidence(case_context, draft)
    _remove_unsupported_cost_amounts(case_context, draft)
    _normalize_state_duty_request(draft)


class ProductionOpenAILegalService(_FastBase):
    """Fast runtime v3: profile-aware drafting, deterministic cleanup, one strict QA in normal cases."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        profile = detect_claim_profile(case_context)
        verified_block = "\n".join(f"- {x}" for x in research.verified_claims) or "нет подтвержденных выводов"
        unverified_block = "\n".join(f"- {x}" for x in research.unverified_claims) or "нет"

        prompt = (
            "Сформируй судебный проект искового заявления по праву Республики Казахстан. "
            "Верни только структуру документа для Word, без чатовых пояснений.\n\n"
            f"ПРЕДВАРИТЕЛЬНЫЙ ПРОФИЛЬ СПОРА: {profile.label}. Это поисковая маршрутизация, а не установленный юридический факт.\n"
            f"ФОКУС: {profile.research_focus}\n\n"
            "ПРАВИЛА:\n"
            "1. Используй все известные реквизиты сторон и не выдумывай отсутствующие.\n"
            "2. Факты сохраняй ровно с той степенью точности, которая есть в материалах. Если пользователь пишет, что дата примерная или требует сверки, не превращай её в точную.\n"
            "3. Правовое обоснование и юридическая квалификация отношений — только из VERIFIED. Нельзя выдавать предполагаемый вид договора за установленный факт, если профильные нормы не подтверждены.\n"
            "4. Не утверждай наличие квитанции госпошлины или другого приложения, если его нет в материалах.\n"
            "5. Не придумывай суд. Неподтвержденный суд оставь как поле для уточнения.\n"
            "6. Не указывай сумму госпошлины самостоятельно — её считает код. Вообще не придумывай суммы судебных расходов.\n"
            "7. В attachments перечисляй ТОЛЬКО реально имеющиеся документы. Отсутствующее обязательное приложение укажи только в verification_notes, но не вставляй служебную заглушку в список приложений.\n"
            "8. В теле иска запрещены URL, Markdown, NEEDS_VERIFICATION, 'подлежит уточнению' и чатовые советы.\n"
            "9. Название иска должно соответствовать фактическому способу защиты: взыскание долга, расторжение, признание, возмещение вреда и т.д. Не используй универсальное название, если VERIFIED и факты позволяют определить требование точнее.\n"
            "10. Норму для правового обоснования подбирай ОТ ТРЕБОВАНИЯ, а не от ближайшей по теме главы кодекса. Каждая норма в legal_basis должна доказывать именно то, что заявлено в просительной части. "
            "Процедурная норма о смежной стадии отношений (например, обязанность заказчика осмотреть и принять результат работ) НЕ является основанием для взыскания денег с подрядчика и не может быть единственным правовым обоснованием такого требования. "
            "Для возврата предоплаты за невыполненные работы основанием служит право заказчика отказаться от договора и потребовать возврата аванса при существенном нарушении подрядчиком либо неосновательное обогащение, если договор прекращён.\n"
            "11. Если ты не уверен, какая именно норма соответствует основанию требования, не подставляй формально похожую: укажи в verification_notes, что требуется подбор точной нормы юристом.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified_block}\n\n"
            f"НЕ ПОДТВЕРЖДЕНО (только для verification_notes):\n{unverified_block}"
        )

        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший судебный юрист KORGAN. Сначала правильно квалифицируй требуемый вид иска по подтвержденным нормам, "
                "затем составляй точный проект без фактических догадок. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_claim",
            schema=_CLAIM_SCHEMA,
        )

        draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **payload)
        _deterministic_pre_qa(case_context, research, draft)

        validation = await self.validate_claim(case_context, research, draft)
        blocking, evidence_gaps, unsupported_law = split_qa_issues(
            critical_errors=validation["critical_errors"],
            unsupported_legal_claims=validation["unsupported_legal_claims"],
            hard_issues=_hard_quality_issues(case_context, draft),
        )

        # Missing fields alone do not justify a costly model rewrite. The
        # preflight catches filing-critical party data before research; any
        # remaining filing item is surfaced as a review note.
        if not blocking:
            apply_soft_qa_findings(
                draft,
                evidence_gaps=evidence_gaps,
                unsupported_legal_claims=unsupported_law,
            )
            for item in validation["missing_required_fields"]:
                if item not in draft.verification_notes:
                    draft.verification_notes.append(item)
        else:
            repair_prompt = (
                "Исправь только перечисленные дефекты. Не добавляй новых фактов или права. "
                "Сохрани приблизительные даты приблизительными, не утверждай наличие отсутствующих документов, "
                "не придумывай судебные расходы и используй юридическую квалификацию только из VERIFIED.\n\n"
                f"ПРОФИЛЬ: {profile.label}\n"
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
            blocking, evidence_gaps, unsupported_law = split_qa_issues(
                critical_errors=validation["critical_errors"],
                unsupported_legal_claims=validation["unsupported_legal_claims"],
                hard_issues=_hard_quality_issues(case_context, draft),
            )
            if blocking:
                raise CourtDocumentQualityError(
                    ClaimFailure(
                        stage=ClaimStage.QA,
                        code=ClaimFailureCode.QA_BLOCKED,
                        issues=blocking,
                    )
                )
            apply_soft_qa_findings(
                draft,
                evidence_gaps=evidence_gaps,
                unsupported_legal_claims=unsupported_law,
            )
            for item in validation["missing_required_fields"]:
                if item not in draft.verification_notes:
                    draft.verification_notes.append(item)

        if research.unverified_claims or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        return draft
