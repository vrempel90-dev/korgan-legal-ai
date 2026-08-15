from __future__ import annotations

import json
import re

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
    """Deterministically catch loss of identifiers, e-mail, phones and explicit party addresses."""
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

    # Extraction context contains a dedicated party-address line. Every explicit value there
    # should survive into claimant/defendant unless the extractor marked it unknown.
    for line in case_context.splitlines():
        if not line.startswith("Адреса:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if not raw or raw == "не установлено":
            continue
        for value in raw.split(";"):
            candidate = value.strip()
            # Strip role labels such as «Истец:», «Ответчик:», «Займодавец:».
            if ":" in candidate:
                prefix, remainder = candidate.split(":", 1)
                if any(word in prefix.lower() for word in ("истец", "ответчик", "займодав", "заемщик", "заёмщик", "адрес")):
                    candidate = remainder.strip()
            norm = _normalize(candidate)
            if len(norm) >= 8 and norm not in normalized_party:
                issues.append(f"известный адрес «{candidate}» потерян в реквизитах сторон")
    return issues


def _hard_quality_issues(case_context: str, draft: ClaimDraft) -> list[str]:
    body = _court_body_text(draft)
    lowered = body.lower()
    issues = [description for needle, description in _FORBIDDEN_COURT_PATTERNS if needle in lowered]
    issues.extend(_known_party_data_issues(case_context, draft))
    return list(dict.fromkeys(issues))


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
            "Нельзя заменять известное значение заглушкой.\n"
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
            "12. Если госпошлина не VERIFIED, не вставляй ее размер или служебное пояснение в тело иска; вынеси вопрос в verification_notes.\n\n"
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
            "critical_errors": list(payload.get("critical_errors", [])),
            "unsupported_legal_claims": list(payload.get("unsupported_legal_claims", [])),
            "missing_required_fields": list(payload.get("missing_required_fields", [])),
        }
