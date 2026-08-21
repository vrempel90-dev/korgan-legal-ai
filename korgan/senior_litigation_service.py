from __future__ import annotations

import json
import logging
from typing import Any

from korgan.document_quality import assess_document_quality
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.professional_service import ProfessionalRKProductionService, _claim_strategy_block
from korgan.provision_check import paraphrase_defects, verified_claim_line
from korgan.robust_production_legal import _is_adilet_source, _is_court_source
from korgan.senior_claim_preflight import (
    SENIOR_CLAIM_REVIEW_SCHEMA,
    SeniorClaimReview,
    claim_review_payload,
    deterministic_claim_preflight,
)
from korgan.verified_openai import _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)

_SENIOR_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "superseded_verified_indexes": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
        },
        "verified_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "article": {"type": "string"},
                    "provision_text": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["statement", "article", "provision_text", "source_url"],
                "additionalProperties": False,
            },
        },
        "procedure_analysis": {"type": "array", "items": {"type": "string"}},
        "remedy_decisions": {"type": "array", "items": {"type": "string"}},
        "corrections": {"type": "array", "items": {"type": "string"}},
        "unverified_claims": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "superseded_verified_indexes",
        "verified_points",
        "procedure_analysis",
        "remedy_decisions",
        "corrections",
        "unverified_claims",
        "notes",
    ],
    "additionalProperties": False,
}


def _as_strings(values: Any) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def _numbered(values: list[str]) -> str:
    return "\n".join(f"[{index}] {value}" for index, value in enumerate(values)) or "[нет]"


def _senior_research_prompt(case_context: str, research: LegalResearch, *, max_chars: int) -> str:
    return (
        "Проведи ADVERSARIAL SENIOR REVIEW уже выполненного legal research по делу в Республике Казахстан. "
        "Не доверяй первоначальной квалификации автоматически: твоя задача — найти судебно значимые ошибки до составления иска.\n\n"
        "ОБЯЗАТЕЛЬНЫЕ ПРОВЕРКИ:\n"
        "1. ПРЕДМЕТНАЯ КОМПЕТЕНЦИЯ: сначала установи процессуальный статус КАЖДОЙ стороны из фактов, затем сопоставь его с буквальным составом субъектов в применимой норме ГПК. "
        "Наличие одного ТОО/юрлица само по себе не означает компетенцию экономического суда. Для специализированного суда должны быть выполнены все предусмотренные законом условия либо отдельное специальное основание.\n"
        "2. ТЕРРИТОРИАЛЬНАЯ ПОДСУДНОСТЬ: проверь общее правило и все специальные/альтернативные варианты, реально применимые по фактам. Если закон дает истцу выбор, не выдавай один вариант за единственно возможный.\n"
        "3. ТОЧНЫЙ СУД: сначала установи правильный тип суда по ГПК, и только после этого используй gov.kz/sud.gov.kz для подтверждения официального наименования/территории. Справочник судов не доказывает предметную компетенцию.\n"
        "4. МАТЕРИАЛЬНАЯ ТЕОРИЯ: проверь, поддерживает ли каждая выбранная норма именно требуемое юридическое последствие, а не просто относится к той же главе/договору.\n"
        "5. СПОСОБЫ ЗАЩИТЫ: для каждого основного и дополнительного требования клиента дай решение в remedy_decisions в формате "
        "'INCLUDE | <требование> | <основание и факты>', 'EXCLUDE | ... | <почему>', либо 'NEEDS_FACTS | ... | <каких фактов не хватает>'. "
        "Особенно проверь все дополнительные денежные требования, которые пользователь прямо просил оценить.\n"
        "6. Не добавляй самостоятельное декларативное требование (признать прекращенным/расторгнуть/признать право), если правовой эффект уже наступил во внесудебном порядке и отдельный судебный способ защиты не подтвержден VERIFIED-нормой как необходимый или полезный.\n"
        "7. ПРОЦЕСС: форма/содержание иска, обязательные приложения, досудебный порядок только при прямом основании, сроки, госпошлина/льгота. Внешнее действие клиента (оплатить пошлину, подписать, приложить квитанцию) отличай от дефекта текста иска.\n"
        "8. Если первоначальный VERIFIED-вывод неверно пересказывает собственный provision_text или противоречит новой официальной норме, укажи его индекс в superseded_verified_indexes.\n\n"
        "SOURCE LOCK:\n"
        "9. Нормы права — только adilet.zan.kz. gov.kz/sud.gov.kz — только наименование/территория суда. Каждый новый verified_point должен иметь точный текст нормы и URL реально открытой страницы.\n"
        "10. Не исправляй первоначальную ошибку другой догадкой. Если точного подтверждения нет — unverified_claims.\n\n"
        f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:max_chars]}\n\n"
        f"ПЕРВИЧНЫЕ VERIFIED (индексы для superseded):\n{_numbered(research.verified_claims)}\n\n"
        f"ПЕРВИЧНЫЕ UNVERIFIED:\n{json.dumps(research.unverified_claims, ensure_ascii=False)}\n\n"
        f"ПЕРВИЧНАЯ СТРАТЕГИЯ/NOTES:\n{json.dumps(research.notes, ensure_ascii=False)}"
    )


def _senior_review_prompt(case_context: str, research: LegalResearch, draft: ClaimDraft) -> str:
    strategy = _claim_strategy_block(research)
    return (
        "Ты независимый старший судебный юрист. Проведи PRE-FILING REVIEW проекта иска по праву Республики Казахстан. "
        "Это не стилистическая редактура: проект должен быть сопоставим с работой практикующего судебного юриста.\n\n"
        "ОЦЕНИВАЙ СТРОГО ПО МАТЕРИАЛАМ И VERIFIED, БЕЗ ПРАВА ПО ПАМЯТИ.\n"
        "1. FACT INTEGRITY: каждое фактическое утверждение в facts, legal_basis и requests должно либо прямо следовать из материалов пользователя, либо быть юридическим выводом, прямо поддержанным VERIFIED. "
        "Запрещено придумывать стресс, переживания, медицинские последствия, расходы, получение документов, признание долга, действия представителя и любые иные факты.\n"
        "2. JURISDICTION: проверь предметную компетенцию через статус КАЖДОЙ стороны и буквальные условия VERIFIED-нормы; затем территориальную подсудность и право выбора истца. "
        "Нельзя считать экономический суд компетентным только потому, что одна сторона — юридическое лицо.\n"
        "3. LEGAL THEORY: для каждого требования должна существовать цепочка элемент -> факт -> доказательство -> VERIFIED-норма -> юридическое последствие. Общая статья или соседняя норма не заменяет профильную.\n"
        "4. REMEDIES: каждый пункт ПРОШУ СУД должен быть необходимым/допустимым, исполнимым и подтвержденным. Не добавляй лишнее декларативное требование, если правовой эффект уже наступил и отдельный исковой способ не нужен по VERIFIED. "
        "Каждое денежное требование должно иметь определенный размер или законный алгоритм расчета; пустые суммы запрещены.\n"
        "5. ADDITIONAL CLAIMS: если пользователь просил проверить дополнительные суммы/меры, убедись, что профессиональная карта содержит решение INCLUDE/EXCLUDE/NEEDS_FACTS по каждому реально рассмотренному виду. "
        "Не включай моральный вред только потому, что закон допускает его: нужны пользовательские факты о вреде; модель не имеет права их создавать.\n"
        "6. EVIDENCE: не утверждай наличие доказательства, которого нет в материалах; каждое ключевое обстоятельство должно иметь указанное фактическое подтверждение либо быть честно обозначено как риск.\n"
        "7. FORM: конкретный суд, обязательные реквизиты, цена и расчет, непротиворечивая просительная часть, чистый профессиональный текст. Внешние действия до подачи (подписать, оплатить пошлину, приложить платежный документ/копии) перечисляй только в filing_actions и не считай сами по себе дефектом юридического текста.\n"
        "8. SCORE: 8.5+ допускается только если нет ни одной ошибки в fact_integrity_errors, jurisdiction_errors, legal_theory_errors, remedy_errors, evidence_errors, document_form_errors. "
        "Неверный суд, выдуманный факт, неподдержанный способ защиты или пустая сумма — серьезный дефект и не может получить оценку около 8.\n\n"
        f"МАТЕРИАЛЫ:\n{case_context}\n\n"
        f"VERIFIED:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
        f"UNVERIFIED:\n{json.dumps(research.unverified_claims, ensure_ascii=False)}\n\n"
        f"ПРОФЕССИОНАЛЬНАЯ КАРТА:\n{strategy}\n\n"
        f"ПРОЕКТ ИСКА:\n{json.dumps(claim_review_payload(draft), ensure_ascii=False)}"
    )


class SeniorLitigationProductionService(ProfessionalRKProductionService):
    """Professional RK litigation core with an adversarial senior-review layer.

    UI/Telegram routes are intentionally outside this class and stay unchanged.
    """

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        initial = await super().research_case(case_context, language=language)
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]
        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший судебный legal researcher KORGAN. Твоя функция — оспаривать первичное исследование, "
                "пока не устранены ошибки компетенции суда, способа защиты и неполного анализа требований. "
                "Право только Республики Казахстан и только source-bound официальные источники."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": _senior_research_prompt(case_context, initial, max_chars=self.settings.max_case_text_chars)}]}],
            schema_name="korgan_senior_rk_research",
            schema=_SENIOR_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [url for url in _actual_response_urls(response) if self._is_current_official_source(url)]
        actual_by_canonical = {_canonical_url(url): url for url in actual_urls if _canonical_url(url)}

        superseded = {
            int(index)
            for index in payload.get("superseded_verified_indexes", []) or []
            if isinstance(index, int) and 0 <= index < len(initial.verified_claims)
        }
        verified = [claim for index, claim in enumerate(initial.verified_claims) if index not in superseded]
        sources = list(initial.source_urls)
        rejected: list[str] = []

        for point in payload.get("verified_points", []) or []:
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            provision_text = str(point.get("provision_text", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(f"{statement} — senior research: нет source-bound официального источника.")
                continue
            if _is_court_source(actual_url):
                if article.lower() != "официальный перечень судов":
                    rejected.append(f"{statement} — источник суда не подтверждает норму права.")
                    continue
                line = f"{statement} [основание: {article}; источник: {actual_url}]"
            else:
                if not _is_adilet_source(actual_url):
                    rejected.append(f"{statement} — senior research: источник не Adilet.")
                    continue
                drift = paraphrase_defects(statement, provision_text)
                if drift:
                    rejected.append(f"{statement} — senior research: {'; '.join(drift[:3])}")
                    continue
                line = verified_claim_line(statement, article, provision_text, actual_url)
            if line not in verified:
                verified.append(line)
            if actual_url not in sources:
                sources.append(actual_url)

        notes = [note for note in initial.notes if not str(note).startswith(("SENIOR_", "PROCEDURE:", "REMEDY_DECISION:"))]
        notes.extend(f"PROCEDURE: {item}" for item in _as_strings(payload.get("procedure_analysis")))
        notes.extend(f"REMEDY_DECISION: {item}" for item in _as_strings(payload.get("remedy_decisions")))
        notes.extend(f"SENIOR_CORRECTION: {item}" for item in _as_strings(payload.get("corrections")))
        notes.extend(_as_strings(payload.get("notes")))

        # A VERIFIED_COURT note is accepted only when an actual court source was
        # opened in either pass and the same court identity appears in a verified
        # court statement. This prevents a model-only court name from becoming a
        # release credential.
        verified_court_lines = [line for line in verified if "официальный перечень судов" in line.lower()]
        clean_notes: list[str] = []
        for note in list(dict.fromkeys(notes)):
            if note.startswith("VERIFIED_COURT:"):
                court = note.split(":", 1)[1].strip()
                norm = "".join(ch.lower() for ch in court if ch.isalnum())
                if norm and any(norm in "".join(ch.lower() for ch in line if ch.isalnum()) for line in verified_court_lines):
                    clean_notes.append(note)
                continue
            clean_notes.append(note)

        unverified = list(initial.unverified_claims)
        unverified.extend(_as_strings(payload.get("unverified_claims")))
        unverified.extend(rejected)
        if superseded:
            unverified.append("Senior research superseded one or more primary VERIFIED conclusions after adversarial re-check.")

        merged = LegalResearch(
            status=VerificationStatus.VERIFIED if verified and sources and not unverified else VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=list(initial.applicable_law),
            procedural_requirements=list(dict.fromkeys([*initial.procedural_requirements, *_as_strings(payload.get("procedure_analysis"))])),
            verified_claims=list(dict.fromkeys(verified)),
            unverified_claims=list(dict.fromkeys(unverified)),
            source_urls=list(dict.fromkeys(sources)),
            notes=clean_notes,
        )
        LOGGER.info(
            "SENIOR_RK_RESEARCH primary=%d superseded=%d final_verified=%d remedies=%d procedure=%d",
            len(initial.verified_claims),
            len(superseded),
            len(merged.verified_claims),
            len([n for n in merged.notes if n.startswith("REMEDY_DECISION:")]),
            len([n for n in merged.notes if n.startswith("PROCEDURE:")]),
        )
        return merged

    async def _senior_review(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ClaimDraft,
        *,
        language: str,
    ) -> SeniorClaimReview:
        deterministic = deterministic_claim_preflight(case_context, research, draft)
        payload, _ = await self._structured_response(
            model=self.settings.openai_validation_model,
            instructions=(
                "Ты независимый senior litigation counsel KORGAN. Не защищай предыдущий ответ модели. "
                "Ищи причины, по которым практикующий судебный юрист не подал бы этот документ в текущем виде. "
                "Не используй право по памяти: юридические выводы оценивай только против предоставленного VERIFIED. "
                f"Язык проверки: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": _senior_review_prompt(case_context, research, draft)}]}],
            schema_name="korgan_senior_claim_preflight",
            schema=SENIOR_CLAIM_REVIEW_SCHEMA,
        )
        report = SeniorClaimReview.from_payload(payload, deterministic_errors=deterministic)
        LOGGER.info(
            "SENIOR_CLAIM_PREFLIGHT score=%.1f ready=%s blockers=%s filing_actions=%s",
            report.score,
            report.ready,
            report.hard_blockers[:8],
            report.filing_actions[:4],
        )
        return report

    @staticmethod
    def _drop_stale_quality_notes(draft: ClaimDraft) -> None:
        draft.verification_notes = [
            note
            for note in draft.verification_notes
            if not str(note).startswith(("KORGAN QUALITY:", "SENIOR_PREFLIGHT_SCORE:"))
        ]

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        # The professional base produces a first source-bound draft and applies
        # existing deterministic legal calculations. Senior review then acts as
        # a separate adversarial lawyer, not as the same model grading itself.
        draft = await super().draft_claim(case_context, research, language=language)
        self._drop_stale_quality_notes(draft)
        first_quality = assess_document_quality("claim", case_context, research, draft)
        first_senior = await self._senior_review(case_context, research, draft, language=language)

        if first_quality.ready and first_senior.ready:
            draft.status = VerificationStatus.VERIFIED
            return draft

        issues = list(
            dict.fromkeys(
                [
                    *first_senior.repair_list(),
                    *first_quality.repair_issues(),
                ]
            )
        )[:18]
        current = claim_review_payload(draft)
        strategy = _claim_strategy_block(research)
        payload = await self._quality_repair(
            schema_name="korgan_senior_litigation_repair",
            schema=_CLAIM_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=current,
            issues=issues,
            language=language,
            document_label="исковое заявление после senior pre-filing review",
            extra_rules=(
                "8. Это не косметический repair. Устрани каждый senior blocker до выпуска.\n"
                "9. Если senior выявил неверный суд — выбери суд ТОЛЬКО из подтвержденного VERIFIED_COURT; если такого суда нет, не выдумывай название.\n"
                "10. Удали каждый факт, отсутствующий в материалах пользователя. Право на моральный вред не является доказательством стресса/переживаний.\n"
                "11. Не оставляй денежные требования с пустой суммой. Если для дополнительного требования не хватает фактов/расчета, исключи его из ПРОШУ СУД вместо заполнения догадкой.\n"
                "12. Не добавляй отдельное требование о признании/прекращении/расторжении только для красоты: оно должно иметь самостоятельную правовую необходимость в VERIFIED.\n"
                "13. Выполни решения REMEDY_DECISION из профессиональной карты: INCLUDE включается только при достаточных фактах+VERIFIED; EXCLUDE не попадает в просительную часть; NEEDS_FACTS не превращается в выдуманный факт.\n"
                f"14. ПРОФЕССИОНАЛЬНАЯ КАРТА ДЕЛА:\n{strategy}"
            ),
        )
        repaired = ClaimDraft(status=research.status, source_urls=list(research.source_urls), **payload)
        self._drop_stale_quality_notes(repaired)
        _deterministic_pre_qa(case_context, research, repaired)
        _apply_verified_article_353(case_context, research, repaired, filing_date=_today_kz())

        second_quality = assess_document_quality("claim", case_context, research, repaired)
        second_senior = await self._senior_review(case_context, research, repaired, language=language)
        if second_quality.ready and second_senior.ready:
            repaired.status = VerificationStatus.VERIFIED
            self._drop_stale_quality_notes(repaired)
            return repaired

        repaired.status = VerificationStatus.NEEDS_VERIFICATION
        final_score = min(second_quality.score, second_senior.score)
        remaining = list(dict.fromkeys([*second_senior.hard_blockers, *second_quality.hard_blockers]))
        note = f"SENIOR_PREFLIGHT_SCORE: {final_score:.1f}/10 — " + ("; ".join(remaining[:6]) or "не достигнут профессиональный порог 8.5")
        if note not in repaired.verification_notes:
            repaired.verification_notes.append(note)
        LOGGER.warning(
            "SENIOR_CLAIM_NOT_READY score=%.1f quality=%.1f senior=%.1f blockers=%s",
            final_score,
            second_quality.score,
            second_senior.score,
            remaining[:8],
        )
        return repaired
