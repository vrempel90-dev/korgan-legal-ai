from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.production_legal import (
    COURT_NOTE,
    ProductionOpenAILegalService as _BaseProductionOpenAILegalService,
)
from korgan.verified_openai import _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)


_CONSULT_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verified_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["statement", "article", "source_url"],
                "additionalProperties": False,
            },
        },
        "unresolved_facts": {"type": "array", "items": {"type": "string"}},
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verified_points", "unresolved_facts", "clarifying_questions"],
    "additionalProperties": False,
}


_CLAIMANT_ROLE_MARKERS = (
    "истец",
    "истца",
    "истцу",
    "займодав",
    "кредитор",
)

_DEFENDANT_ROLE_MARKERS = (
    "ответчик",
    "ответчика",
    "ответчику",
    "заемщик",
    "заёмщик",
    "должник",
)

_OPTIONAL_CONTACT_MARKERS = (
    "телефон",
    "сотов",
    "мобильн",
    "e-mail",
    "email",
    "электронн",
)

_DOB_MARKERS = (
    "дата рождения",
    "дата рожд.",
    "родился",
    "родилась",
)

_DOB_PLACEHOLDER = "Дата рождения: [ТРЕБУЕТ УТОЧНЕНИЯ: дата рождения истца]"
_DOB_NOTE = (
    "Не установлена дата рождения физического лица-истца — требуется уточнить обязательный реквизит иска перед подачей."
)

_STATE_DUTY_ATTACHMENT = (
    "[ТРЕБУЕТ ДОБАВИТЬ: документ, подтверждающий уплату государственной пошлины, "
    "либо ходатайство об отсрочке по уплате государственной пошлины]"
)
_STATE_DUTY_ATTACHMENT_NOTE = (
    "В материалах нет документа, подтверждающего уплату государственной пошлины, либо ходатайства об отсрочке; "
    "его необходимо добавить к иску перед подачей."
)

_DATE_PATTERN = re.compile(r"(?<!\d)(\d{2}[./-]\d{2}[./-]\d{4})(?!\d)")
_DUE_LINE_MARKERS = (
    "срок возврат",
    "срок исполн",
    "обязался вернуть",
    "обязана вернуть",
    "обязан вернуть",
    "возвратить до",
    "вернуть до",
    "не позднее",
)
_LIMITATION_MARKERS = (
    "исковая давност",
    "исковой давност",
    "статьи 178",
    "ст. 178",
    "статьи 180",
    "ст. 180",
)


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", value.lower())


def _is_adilet_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "adilet.zan.kz" or host.endswith(".adilet.zan.kz")


def _party_for_prefix(prefix: str) -> str | None:
    lowered = prefix.lower()
    if any(marker in lowered for marker in _CLAIMANT_ROLE_MARKERS):
        return "claimant"
    if any(marker in lowered for marker in _DEFENDANT_ROLE_MARKERS):
        return "defendant"
    return None


def _append_if_missing(target: list[str], label: str, value: str) -> None:
    clean = value.strip()
    if not clean or clean.lower() == "не установлено":
        return
    normalized_existing = _normalize("\n".join(target))
    if _normalize(clean) in normalized_existing:
        return
    target.append(f"{label}: {clean}")


def _restore_role_bound_bucket(
    case_context: str,
    draft: ClaimDraft,
    bucket: str,
    label: str,
) -> None:
    for line in case_context.splitlines():
        if not line.startswith(bucket):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw or raw.lower() == "не установлено":
            continue

        for value in raw.split(";"):
            candidate = value.strip()
            if ":" not in candidate:
                continue
            prefix, remainder = candidate.split(":", 1)
            party = _party_for_prefix(prefix)
            if party == "claimant":
                _append_if_missing(draft.claimant, label, remainder)
            elif party == "defendant":
                _append_if_missing(draft.defendant, label, remainder)


def _remove_unsupported_conditionals(draft: ClaimDraft) -> None:
    """Drop optional court-text items that the model itself marked as conditional."""
    for field_name in ("facts", "legal_basis", "requests", "attachments"):
        values = list(getattr(draft, field_name))
        cleaned = [item for item in values if "при наличии" not in item.lower()]
        setattr(draft, field_name, cleaned)


def _is_placeholder(value: str) -> bool:
    upper = value.upper()
    return "[ТРЕБУЕТ УТОЧНЕНИЯ" in upper or "[ТРЕБУЕТ ДОБАВИТЬ" in upper


def _drop_optional_unknown_contacts(draft: ClaimDraft) -> None:
    """Unknown phone/e-mail are optional, so do not render them as filing blockers."""
    for field_name in ("claimant", "defendant"):
        values = list(getattr(draft, field_name))
        cleaned: list[str] = []
        for item in values:
            lowered = item.lower()
            if _is_placeholder(item) and any(marker in lowered for marker in _OPTIONAL_CONTACT_MARKERS):
                continue
            cleaned.append(item)
        setattr(draft, field_name, cleaned)


def _claimant_is_natural_person(draft: ClaimDraft) -> bool:
    text = "\n".join(draft.claimant).lower()
    return "иин" in text and "бин" not in text and bool(re.search(r"(?<!\d)\d{12}(?!\d)", text))


def _restore_claimant_dob(case_context: str, draft: ClaimDraft) -> None:
    claimant_text = "\n".join(draft.claimant).lower()
    if any(marker in claimant_text for marker in _DOB_MARKERS):
        return

    for line in case_context.splitlines():
        for segment in line.split(";"):
            lowered = segment.lower()
            if "дата рождения" not in lowered:
                continue
            if not any(marker in lowered for marker in _CLAIMANT_ROLE_MARKERS):
                continue
            match = _DATE_PATTERN.search(segment)
            if match:
                draft.claimant.append(f"Дата рождения: {match.group(1)}")
                return


def _enforce_claimant_dob(case_context: str, draft: ClaimDraft) -> None:
    if not _claimant_is_natural_person(draft):
        return
    _restore_claimant_dob(case_context, draft)
    if any(marker in "\n".join(draft.claimant).lower() for marker in _DOB_MARKERS):
        return
    if _DOB_PLACEHOLDER not in draft.claimant:
        draft.claimant.append(_DOB_PLACEHOLDER)
    if _DOB_NOTE not in draft.verification_notes:
        draft.verification_notes.append(_DOB_NOTE)


def _has_state_duty_payment_proof(case_context: str) -> bool:
    lowered = case_context.lower()
    if "госпошлин" not in lowered and "государственн" not in lowered:
        return False
    payment_markers = (
        "квитанц",
        "чек",
        "платежн",
        "платёжн",
        "оплачен",
        "оплачена",
        "уплачен",
        "уплачена",
    )
    return any(marker in lowered for marker in payment_markers)


def _enforce_state_duty_attachment(case_context: str, draft: ClaimDraft) -> None:
    if _has_state_duty_payment_proof(case_context):
        draft.verification_notes[:] = [
            note for note in draft.verification_notes if note != _STATE_DUTY_ATTACHMENT_NOTE
        ]
        draft.attachments[:] = [
            item for item in draft.attachments if item != _STATE_DUTY_ATTACHMENT
        ]
        return

    if _STATE_DUTY_ATTACHMENT not in draft.attachments:
        draft.attachments.append(_STATE_DUTY_ATTACHMENT)
    if _STATE_DUTY_ATTACHMENT_NOTE not in draft.verification_notes:
        draft.verification_notes.append(_STATE_DUTY_ATTACHMENT_NOTE)


def _drop_nonstandard_party_summons(draft: ClaimDraft) -> None:
    cleaned: list[str] = []
    for request in draft.requests:
        lowered = request.lower()
        if (
            "вызвать" in lowered
            and "судеб" in lowered
            and "истц" in lowered
            and "ответчик" in lowered
            and "объяснен" in lowered
        ):
            continue
        cleaned.append(request)
    draft.requests = cleaned


def _recent_due_date(case_context: str) -> date | None:
    candidates: list[date] = []
    for line in case_context.splitlines():
        lowered = line.lower()
        if not any(marker in lowered for marker in _DUE_LINE_MARKERS):
            continue
        for match in _DATE_PATTERN.finditer(line):
            try:
                candidates.append(datetime.strptime(match.group(1).replace("/", ".").replace("-", "."), "%d.%m.%Y").date())
            except ValueError:
                continue
    if not candidates:
        return None
    return max(candidates)


def _drop_irrelevant_limitation_discussion(case_context: str, draft: ClaimDraft) -> None:
    """Keep limitation analysis only when it can matter; do not pad fresh claims with it."""
    due = _recent_due_date(case_context)
    if due is None:
        return
    age_days = (date.today() - due).days
    if age_days < 0 or age_days > 730:
        return

    draft.facts = [
        item for item in draft.facts
        if not any(marker in item.lower() for marker in _LIMITATION_MARKERS)
    ]
    draft.legal_basis = [
        item for item in draft.legal_basis
        if not any(marker in item.lower() for marker in _LIMITATION_MARKERS)
    ]


def _prepare_draft_for_validation(case_context: str, draft: ClaimDraft) -> None:
    _remove_unsupported_conditionals(draft)
    _drop_optional_unknown_contacts(draft)
    _drop_nonstandard_party_summons(draft)
    _drop_irrelevant_limitation_discussion(case_context, draft)

    _restore_role_bound_bucket(case_context, draft, "Адреса:", "Адрес")
    _restore_role_bound_bucket(case_context, draft, "Идентификаторы:", "ИИН/БИН")
    _restore_role_bound_bucket(case_context, draft, "Контакты:", "Контакт")

    _enforce_claimant_dob(case_context, draft)
    _enforce_state_duty_attachment(case_context, draft)


def _restore_verified_court(research: LegalResearch, draft: ClaimDraft) -> None:
    """Replace the generic court placeholder only with a source-bound verified court."""
    court = ""
    for note in research.notes:
        if note.startswith("VERIFIED_COURT:"):
            court = note.split(":", 1)[1].strip()
            break
    if not court:
        return

    normalized = _normalize(court)
    if not normalized or not any(normalized in _normalize(claim) for claim in research.verified_claims):
        return

    draft.court = court
    draft.verification_notes[:] = [note for note in draft.verification_notes if note != COURT_NOTE]


def _sync_state_duty_request(draft: ClaimDraft) -> None:
    """Use the deterministic duty amount in the prayer for relief instead of a vague future amount."""
    duty = draft.state_duty.strip()
    if not duty or duty.startswith("[ТРЕБУЕТ"):
        return

    amount = duty.split("(", 1)[0].strip()
    if not amount:
        return

    cleaned: list[str] = []
    for request in draft.requests:
        lowered = request.lower()
        vague = (
            "судебн" in lowered
            and "расход" in lowered
            and (
                "который будет подтверж" in lowered
                or "которые будут подтверж" in lowered
                or "документально подтверж" in lowered
            )
            and "госпошлин" not in lowered
        )
        if vague:
            continue
        cleaned.append(request)
    draft.requests = cleaned

    if not any("госпошлин" in request.lower() for request in draft.requests):
        draft.requests.append(
            f"Взыскать с ответчика в пользу истца расходы по уплате государственной пошлины в размере {amount}."
        )


class ProductionOpenAILegalService(_BaseProductionOpenAILegalService):
    """Production service with court-ready drafting plus practical source-bound consultation."""

    async def consult(
        self,
        question: str,
        case_context: str = "",
        language: str = "ru",
    ) -> tuple[str, list[str]]:
        """Consult without turning fail-closed into a refusal to help.

        Exact law is source-bound to Adilet. When the answer depends on contract
        wording or missing evidence, the assistant still gives a practical factual
        analysis and asks for the exact missing documents instead of refusing.
        """
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": ["adilet.zan.kz"]},
            "search_context_size": "medium",
        }]
        research_prompt = (
            f"Дата проверки: {date.today().isoformat()}. Исследуй ТОЛЬКО тот правовой вопрос, который задал пользователь. "
            "Не превращай обычную консультацию в исследование для искового заявления.\n\n"
            "ПРАВИЛА:\n"
            "1. verified_points: только выводы по действующему праву Республики Казахстан, для которых ты реально открыл страницу Adilet.\n"
            "2. Для каждого verified_point укажи точный номер статьи/пункта и URL той страницы Adilet, которую реально использовал.\n"
            "3. Если ответ зависит от текста договора, акта, приложения, переписки, вида переданных документов или иных фактов — перечисли это в unresolved_facts.\n"
            "4. В clarifying_questions дай только вопросы, ответы на которые реально изменят юридический вывод.\n"
            "5. Не выдумывай содержание договора и не подменяй отсутствие факта предположением.\n"
            "6. Не ищи госпошлину, подсудность, исковую давность и процессуальные нормы, если пользователь об этом не спрашивает и они не нужны для ответа.\n\n"
            f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}\n\n"
            f"МАТЕРИАЛЫ/КОНТЕКСТ:\n{case_context[:30000] if case_context else 'нет'}"
        )

        payload, research_response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN для консультаций по праву Республики Казахстан. "
                "Ищи только то, что относится к вопросу. Fail-closed относится к нормам права, а не к способности помочь пользователю."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": research_prompt}]}],
            schema_name="korgan_consult_research",
            schema=_CONSULT_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(research_response)
            if _is_adilet_url(url) and self._is_current_official_source(url)
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }

        verified_points: list[str] = []
        used_urls: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not article or not actual_url:
                continue
            verified_points.append(f"{statement} [статья/пункт: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unresolved = [str(x).strip() for x in payload.get("unresolved_facts", []) if str(x).strip()]
        clarifying = [str(x).strip() for x in payload.get("clarifying_questions", []) if str(x).strip()]

        LOGGER.info(
            "KORGAN consultation research: actual_adilet_urls=%d verified_points=%d unresolved=%d",
            len(actual_urls),
            len(verified_points),
            len(unresolved),
        )

        answer_prompt = (
            f"ВОПРОС:\n{question}\n\n"
            f"КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ:\n{case_context[:30000] if case_context else 'нет'}\n\n"
            f"ПОДТВЕРЖДЕННЫЕ НОРМЫ/ВЫВОДЫ:\n{json.dumps(verified_points, ensure_ascii=False)}\n\n"
            f"НЕУСТАНОВЛЕННЫЕ ФАКТЫ:\n{json.dumps(unresolved, ensure_ascii=False)}\n\n"
            f"УТОЧНЯЮЩИЕ ВОПРОСЫ:\n{json.dumps(clarifying, ensure_ascii=False)}\n\n"
            "Дай практическую консультацию. Начни с краткого ответа по сути. Затем объясни, от чего зависит окончательный вывод и что пользователю делать дальше. "
            "Конкретное содержание закона, номера статей, сроки, обязанности и запреты можно утверждать ТОЛЬКО из списка ПОДТВЕРЖДЕННЫЕ НОРМЫ/ВЫВОДЫ. "
            "Если список пуст, НЕ ОТКАЗЫВАЙСЯ ОТ КОНСУЛЬТАЦИИ: дай предварительный анализ только по фактам пользователя, объясни договорные/доказательственные развилки "
            "и запроси нужный документ или пункт договора. Не пиши фразу 'не удалось проверить ответ' и не советуй просто переформулировать вопрос. "
            "Не выдумывай отсутствующие условия договора. Если нужен документ, назови конкретно какой раздел/пункт нужен."
        )

        response = await self.client.responses.create(
            model=self.settings.openai_model,
            instructions=(
                "Ты KORGAN Legal AI, практикующий юридический ассистент по праву Казахстана. "
                "Помогай пользователю даже при неполных данных, но отделяй фактический предварительный анализ от подтвержденных норм права. "
                f"Отвечай на {'казахском' if language == 'kk' else 'русском'}."
            ),
            input=answer_prompt,
            store=False,
        )

        fully_verified = bool(verified_points) and not unresolved
        marker = "✅ VERIFIED" if fully_verified else "⚠️ NEEDS_VERIFICATION"
        return f"{marker}\n\n{response.output_text.strip()}", used_urls

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        draft = await super().draft_claim(case_context, research, language=language)

        _restore_verified_court(research, draft)
        _sync_state_duty_request(draft)
        _prepare_draft_for_validation(case_context, draft)

        if research.unverified_claims or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        else:
            draft.status = research.status
        return draft

    async def validate_claim(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> dict[str, list[str]]:
        _prepare_draft_for_validation(case_context, draft)
        return await super().validate_claim(case_context, research, draft)
