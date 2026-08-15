from __future__ import annotations

import json
import re

from korgan.legal_calc import NEEDS_CALCULATION_MARKER, gosposhlina_line
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA, _VALIDATION_SCHEMA
from korgan.verified_openai import VerifiedOpenAILegalService


class CourtDocumentQualityError(RuntimeError):
    """Raised when a draft still fails deterministic court-document checks."""


_FORBIDDEN_COURT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("needs_verification", "служебная отметка NEEDS_VERIFICATION попала в тело иска"),
    ("можно адаптировать", "чатовая фраза «можно адаптировать» попала в иск"),
    ("если нужно", "чатовое предложение пользователю попало в иск"),
    ("могу доработать", "чатовое предложение доработки попало в иск"),
    ("если отправите", "чатовый запрос дополнительных данных попал в иск"),
    ("что еще нужно сделать", "служебный раздел попал в иск"),
    ("что ещё нужно сделать", "служебный раздел попал в иск"),
    ("официальные источники", "список источников попал в тело иска"),
    ("http://", "URL попал в тело иска"),
    ("https://", "URL попал в тело иска"),
    ("при наличии", "условная формулировка «при наличии» попала в судебный текст"),
    ("подлежит уточнению", "чатовая формулировка «подлежит уточнению» попала в иск"),
    ("указать наименование", "инструкция пользователю попала в иск"),
    ("указать полный адрес", "инструкция пользователю попала в иск"),
    ("###", "Markdown-заголовок попал в иск"),
    ("**", "Markdown-разметка попала в иск"),
)

_NON_PARTY_LOCATION_MARKERS = (
    "место заключения",
    "место подписания",
    "место исполнения договора",
    "место передачи денег",
    "место совершения сделки",
)

_EXPLICIT_ADDRESS_MARKERS = (
    "место жительства",
    "место регистрации",
    "адрес регистрации",
    "адрес проживания",
    "улица",
    "ул.",
    "проспект",
    "пр-т",
    "микрорайон",
    "мкр",
    "дом ",
    "д. ",
    "квартира",
    "кв.",
)


def _court_body_text(draft: ClaimDraft) -> str:
    return "\n".join(
        [
            draft.title,
            draft.court,
            *draft.claimant,
            *draft.defendant,
            draft.price_of_claim,
            *draft.facts,
            *draft.legal_basis,
            *draft.requests,
            *draft.attachments,
        ]
    )


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", value.lower())


def _known_party_data_issues(case_context: str, draft: ClaimDraft) -> list[str]:
    """Catch loss of identifiers/e-mail and only addresses explicitly tied to a party."""
    issues: list[str] = []
    party_text = "\n".join([*draft.claimant, *draft.defendant])
    normalized_party = _normalize(party_text)

    # IIN/BIN-like 12-digit identifiers present in case materials must not disappear.
    for identifier in sorted(set(re.findall(r"(?<!\d)\d{12}(?!\d)", case_context))):
        if identifier not in party_text:
            issues.append(f"известный ИИН/БИН {identifier} потерян в реквизитах сторон")

    for email in sorted(set(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", case_context, re.IGNORECASE))):
        if email.lower() not in party_text.lower():
            issues.append(f"известный e-mail {email} потерян в реквизитах сторон")

    # The extractor's «Адреса» bucket may also contain a contract/signing location.
    # A generic city or «место заключения договора» is NOT a party address. Enforce
    # preservation only when the value is explicitly bound to a party or clearly
    # looks like a residential/registration street address.
    for line in case_context.splitlines():
        if not line.startswith("Адреса:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw or raw == "не установлено":
            continue

        for value in raw.split(";"):
            candidate = value.strip()
            role_bound = False

            if ":" in candidate:
                prefix, remainder = candidate.split(":", 1)
                if any(
                    word in prefix.lower()
                    for word in ("истец", "ответчик", "займодав", "заемщик", "заёмщик", "адрес истца", "адрес ответчика")
                ):
                    role_bound = True
                    candidate = remainder.strip()

            lowered_candidate = candidate.lower()
            if any(marker in lowered_candidate for marker in _NON_PARTY_LOCATION_MARKERS):
                continue

            if not role_bound and not any(marker in lowered_candidate for marker in _EXPLICIT_ADDRESS_MARKERS):
                continue

            norm = _normalize(candidate)
            if len(norm) >= 8 and norm not in normalized_party:
                issues.append(f"известный адрес «{candidate}» потерян в реквизитах сторон")

    return issues


COURT_PLACEHOLDER = "[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда по месту жительства ответчика]"

COURT_NOTE = (
    "Точное наименование суда не выводится расчётом: требуется привязка адреса ответчика "
    "к конкретному судебному участку и специализации — NEEDS_VERIFICATION."
)

STATE_DUTY_NOTE = (
    "Государственная пошлина не рассчитана детерминированно: из материалов не установлены "
    "цена иска и/или статус истца (физическое либо юридическое лицо) — NEEDS_VERIFICATION."
)

# «Медеуский районный суд города Алматы», «СМЭС города Астаны» и т. п.
_COURT_NAME_PATTERN = re.compile(
    r"(?:районн\w*|городск\w*|межрайонн\w*|специализированн\w*|областн\w*|верховн\w*)\s+суд|\bсмэс\b",
    re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-zа-яё]{3,}", text.lower())


def _named_in_materials(court: str, case_context: str) -> bool:
    """True when every word of the court name also occurs in the materials.

    Russian declension («Медеускому суду» vs «Медеуский суд») rules out exact
    comparison, so each word is matched by its stem. Requiring *all* words —
    the toponym included — keeps this from accepting an unrelated mention.
    """
    court_words = _words(court)
    if not court_words:
        return False
    context_words = _words(case_context)
    return all(
        any(candidate.startswith(word[: min(5, len(word))]) for candidate in context_words)
        for word in court_words
    )


def _enforce_court_verification(case_context: str, draft: ClaimDraft) -> None:
    """A concrete court name is never derivable from law alone.

    It may only survive when the case materials themselves name the court;
    otherwise the model guessed it, and a guessed court sends the claim to the
    wrong forum. Such a guess is replaced by an explicit verification marker.
    """
    court = draft.court.strip()
    if not court or "[ТРЕБУЕТ" in court.upper():
        return
    if not _COURT_NAME_PATTERN.search(court):
        return

    if _named_in_materials(court.replace("В суд", "", 1), case_context):
        return

    draft.court = COURT_PLACEHOLDER
    if COURT_NOTE not in draft.verification_notes:
        draft.verification_notes.append(COURT_NOTE)


_STALE_DUTY_NOTE_MARKERS = (
    "не подтверж",
    "не указан",
    "не рассчит",
    "needs_verification",
    "требует расчёт",
    "требует расчет",
    "требует уточнени",
)


def _is_stale_duty_note(note: str) -> bool:
    """A model note saying the duty is unknown, now that code has computed it."""
    lowered = note.lower()
    return "пошлин" in lowered and any(marker in lowered for marker in _STALE_DUTY_NOTE_MARKERS)


def _apply_state_duty(case_context: str, draft: ClaimDraft) -> None:
    """Compute the state duty in code; the model never supplies this number."""
    draft.state_duty = gosposhlina_line(case_context, draft.price_of_claim)
    if draft.state_duty == NEEDS_CALCULATION_MARKER:
        if STATE_DUTY_NOTE not in draft.verification_notes:
            draft.verification_notes.append(STATE_DUTY_NOTE)
        return

    # The amount is now deterministic, so notes claiming it is unknown would
    # contradict the document the user receives.
    draft.verification_notes[:] = [
        note for note in draft.verification_notes if not _is_stale_duty_note(note)
    ]


def _hard_quality_issues(case_context: str, draft: ClaimDraft) -> list[str]:
    body = _court_body_text(draft)
    lowered = body.lower()
    issues = [description for needle, description in _FORBIDDEN_COURT_PATTERNS if needle in lowered]
    issues.extend(_known_party_data_issues(case_context, draft))
    return list(dict.fromkeys(issues))


def _sanitize_model_validation_issues(items: list[str]) -> list[str]:
    """Remove a known validator false-positive: contract location treated as party address."""
    clean: list[str] = []
    for item in items:
        lowered = item.lower()
        if "адрес" in lowered and any(marker in lowered for marker in _NON_PARTY_LOCATION_MARKERS):
            continue
        clean.append(item)
    return clean


class ProductionOpenAILegalService(VerifiedOpenAILegalService):
    """Source-bound service with strict court-document quality gates."""

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        verified_block = "\n".join(f"- {x}" for x in research.verified_claims) or "нет подтвержденных выводов"
        unverified_block = "\n".join(f"- {x}" for x in research.unverified_claims) or "нет"

        prompt = (
            "Сформируй СУДЕБНЫЙ ПРОЕКТ искового заявления для Республики Казахстан. "
            "Результат будет автоматически помещен в Word-файл, поэтому судебные поля должны содержать только текст самого иска.\n\n"
            "ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА КАЧЕСТВА:\n"
            "1. Используй ВСЕ известные из материалов реквизиты сторон: ФИО, ИИН/БИН, адрес, телефон, e-mail. "
            "Нельзя заменять известное значение заглушкой. Место заключения/подписания/исполнения договора не является адресом стороны, "
            "если материалы прямо не связывают его с местом жительства, регистрации или нахождения этой стороны.\n"
            "2. Не придумывай неизвестное. Для реально отсутствующего обязательного реквизита используй только '[ТРЕБУЕТ УТОЧНЕНИЯ: ...]'.\n"
            "3. Факты изложи хронологично: договор, исполнение истцом, срок исполнения ответчиком, нарушение. Не выдумывай претензии, переписку или платежи.\n"
            "4. Правовое обоснование строй ТОЛЬКО на VERIFIED-выводах. Если для займа VERIFIED статьи 715 и/или 722 ГК РК, обязательно используй их.\n"
            "5. Процессуальные нормы включай только если они подтверждены и действительно нужны для иска.\n"
            "6. В судебных полях запрещены: NEEDS_VERIFICATION, советы пользователю, 'можно адаптировать', 'при наличии', 'если нужно', "
            "'если отправите', 'могу доработать', URL, Markdown и служебные списки проверки.\n"
            "7. Непроверенные вопросы помещай ТОЛЬКО в verification_notes — они показываются отдельно в Telegram.\n"
            "8. В attachments перечисляй конкретные документы, реально присутствующие в материалах. Если обязательного приложения нет — '[ТРЕБУЕТ ДОБАВИТЬ: ...]'.\n"
            "9. Не включай доверенность, расходы представителя, претензию, копию удостоверения или иные условные документы, если материалы не подтверждают их наличие/необходимость.\n"
            "10. Известную цену иска заполняй точно.\n"
            "11. Если точный суд не подтвержден, court = '[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда по месту жительства ответчика]'. Не выдумывай суд.\n"
            "12. Размер госпошлины не указывай вообще: он рассчитывается системой детерминированно по действующей ставке "
            "и подставляется в документ автоматически. Не пиши сумму пошлины и не добавляй пояснений о ней.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified_block}\n\n"
            f"НЕ ПОДТВЕРЖДЕНО (только для verification_notes):\n{unverified_block}"
        )

        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший судебный юрист KORGAN по праву Республики Казахстан. "
                "Пиши готовый к вычитке судебный документ, без чатовых пояснений и без правовой фантазии. "
                f"Язык документа: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_claim",
            schema=_CLAIM_SCHEMA,
        )

        draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **payload)
        validation = await self.validate_claim(case_context, research, draft)
        model_problems = (
            validation["critical_errors"]
            + validation["unsupported_legal_claims"]
            + validation["missing_required_fields"]
        )
        hard_problems = _hard_quality_issues(case_context, draft)
        problems = list(dict.fromkeys(model_problems + hard_problems))

        # One repair pass is mandatory if either the independent validator or
        # deterministic gate sees a defect.
        if problems:
            repair_prompt = (
                "Перепиши проект иска так, чтобы он прошел все замечания. Сохрани fail-closed режим. "
                "Не добавляй новых фактов или норм. Верни полностью исправленную структуру иска.\n\n"
                f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
                f"VERIFIED:\n{verified_block}\n\n"
                f"ЗАМЕЧАНИЯ:\n{json.dumps(problems, ensure_ascii=False)}\n\n"
                f"ТЕКУЩИЙ ПРОЕКТ:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            repaired_payload, _ = await self._structured_response(
                model=self.settings.openai_model,
                instructions=(
                    "Ты редактор судебных документов KORGAN. Удали весь чатовый/служебный текст, восстанови известные реквизиты из материалов, "
                    "исправь только выявленные дефекты и не добавляй неподтвержденное право."
                ),
                content=[{"role": "user", "content": [{"type": "input_text", "text": repair_prompt}]}],
                schema_name="korgan_repaired_claim",
                schema=_CLAIM_SCHEMA,
            )
            draft = ClaimDraft(status=research.status, source_urls=research.source_urls, **repaired_payload)
            validation = await self.validate_claim(case_context, research, draft)
            hard_problems = _hard_quality_issues(case_context, draft)

            # Critical legal/factual errors and deterministic contamination are a hard stop.
            blocking = list(dict.fromkeys(
                validation["critical_errors"]
                + validation["unsupported_legal_claims"]
                + hard_problems
            ))
            if blocking:
                raise CourtDocumentQualityError("; ".join(blocking[:12]))

            remaining = list(validation["missing_required_fields"])
            if remaining:
                draft.verification_notes.extend(x for x in remaining if x not in draft.verification_notes)

        # Deterministic fields are decided by code, after every model pass:
        # the duty is calculated, the court is never guessed.
        _apply_state_duty(case_context, draft)
        _enforce_court_verification(case_context, draft)

        if research.unverified_claims or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        return draft

    async def validate_claim(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
    ) -> dict[str, list[str]]:
        draft_text = json.dumps(
            {
                "title": draft.title,
                "court": draft.court,
                "claimant": draft.claimant,
                "defendant": draft.defendant,
                "price_of_claim": draft.price_of_claim,
                "facts": draft.facts,
                "legal_basis": draft.legal_basis,
                "requests": draft.requests,
                "attachments": draft.attachments,
            },
            ensure_ascii=False,
        )
        prompt = (
            "Проверь проект иска как строгий редактор перед выдачей клиенту. Найди:\n"
            "1) факты, которых нет в материалах (включая выдуманные претензии, переписку или платежи);\n"
            "2) правовые утверждения, которых нет в VERIFIED;\n"
            "3) известные в материалах ФИО/ИИН/адрес/контакт/сумму, которые проект потерял или заменил заглушкой;\n"
            "КРИТИЧЕСКОЕ ПРАВИЛО: место заключения, подписания, исполнения договора, передачи денег или совершения сделки само по себе НЕ является адресом стороны. "
            "НИКОГДА не сообщай о потере адреса только потому, что в материалах указано такое место. Считай адрес известным только при явной привязке "
            "к месту жительства, регистрации, нахождения либо к реквизитам конкретной стороны.\n"
            "4) загруженный/подтвержденный документ, ошибочно названный 'при наличии';\n"
            "5) прямо применимую VERIFIED-норму материального права, необоснованно отсутствующую в legal_basis;\n"
            "6) любой служебный/чатовый текст: NEEDS_VERIFICATION, советы, URL, Markdown, 'можно адаптировать', 'если нужно', 'при наличии';\n"
            "7) условные требования/приложения без фактического основания;\n"
            "8) иные обязательные поля, которые нельзя безопасно восстановить.\n"
            "Не требуй придумывать неизвестный точный суд или неподтвержденную госпошлину: для них допустима краткая пометка об уточнении вне правового обоснования.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:40000]}\n\n"
            f"VERIFIED:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
            f"ПРОЕКТ:\n{draft_text}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_validation_model,
            instructions="Ты независимый валидатор судебных документов KORGAN. Будь строгим и fail-closed.",
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_validation",
            schema=_VALIDATION_SCHEMA,
        )
        return {
            "critical_errors": _sanitize_model_validation_issues(list(payload.get("critical_errors", []))),
            "unsupported_legal_claims": _sanitize_model_validation_issues(list(payload.get("unsupported_legal_claims", []))),
            "missing_required_fields": _sanitize_model_validation_issues(list(payload.get("missing_required_fields", []))),
        }
