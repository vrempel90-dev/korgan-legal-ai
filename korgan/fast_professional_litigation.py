from __future__ import annotations

import logging
from datetime import date

from korgan.document_quality import assess_document_quality
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.professional_service import (
    ProfessionalRKProductionService,
    _PROFESSIONAL_RESEARCH_SCHEMA,
    _claim_strategy_block,
    _professional_research_prompt,
    _strategy_notes,
)
from korgan.professional_claim_finalizer import bind_verified_legal_basis
from korgan.provision_check import paraphrase_defects, verified_claim_line
from korgan.robust_production_legal import _is_adilet_source, _is_court_source
from korgan.senior_claim_preflight import deterministic_claim_preflight
from korgan.verified_openai import _actual_response_urls, _canonical_url
from korgan.pro_claim_sections import PRO_CLAIM_PROMPT, pro_payload

LOGGER = logging.getLogger(__name__)


_EXTERNAL_INPUT_ISSUES = (
    "точное наименование суда не подтверждено",
    "не определено конкретное наименование суда",
    "наименование суда не подтверждено",
    "не определена госпошлина",
    "не заполнены данные истца",
    "не заполнены данные ответчика",
    "нет source-bound подтвержденной материально-правовой основы",
    "есть verified-нормы, но документ не содержит конкретной статьи",
    "отсутствует правовое обоснование",
    "вопросы к проверке перед подачей",
)


def claim_repair_has_actionable_issue(issues: list[str]) -> bool:
    """Whether one model edit can safely fix at least one listed defect.

    A model cannot discover an unknown party, court, duty basis or missing
    source-bound law during a no-search repair call. Sending those gaps through
    another full drafting pass adds latency and invites fabricated replacements.
    """
    for issue in issues:
        lowered = str(issue or "").strip().lower()
        if lowered and not any(marker in lowered for marker in _EXTERNAL_INPUT_ISSUES):
            return True
    return False


class FastProfessionalLitigationService(ProfessionalRKProductionService):
    """Production litigation path optimized for professional quality without 5-minute chains.

    Maximum normal path:
      1) one source-bound research call (web search, medium context),
      2) one professional drafting call,
      3) one deterministic senior preflight,
      4) at most one targeted repair call.

    There is deliberately no second web research pass and no second LLM review.
    """

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "medium",
        }]
        prompt = _professional_research_prompt(
            case_context,
            max_chars=self.settings.max_case_text_chars,
            checked_on=date.today().isoformat(),
        ) + (
            "\n\nОБЯЗАТЕЛЬНЫЙ ADVERSARIAL PREFLIGHT В ЭТОМ ЖЕ ИССЛЕДОВАНИИ:\n"
            "15. До выбора суда установи статус КАЖДОЙ стороны. Одно ТОО среди сторон само по себе не означает компетенцию экономического суда. "
            "Если среди сторон есть обычное физическое лицо, отдельно проверь буквальный субъектный состав применимой нормы ГПК.\n"
            "16. Если из адресов и процессуальной нормы можно определить надлежащий суд, обязательно попытайся подтвердить его официальное наименование через gov.kz/sud.gov.kz в этом же поиске.\n"
            "17. Для каждого дополнительного требования, которое клиент просит проверить, запиши в remedies решение ровно одного вида: "
            "INCLUDE | требование | почему; EXCLUDE | требование | почему; NEEDS_FACTS | требование | каких фактов не хватает.\n"
            "18. Не считай право на моральный вред доказательством стресса/переживаний. Такие факты могут идти в иск только если их сообщил пользователь.\n"
            "19. Не добавляй отдельное требование о признании/расторжении/прекращении, если юридический эффект уже наступил внесудебно и VERIFIED не показывает самостоятельную необходимость судебного требования.\n"
            "20. Ограничь research только нормами, реально необходимыми для конечного иска: материальная квалификация, способ защиты, подсудность/компетенция, госпошлина/льгота и запрошенные дополнительные требования. Не собирай энциклопедию права."
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты ведущий судебный юрист KORGAN по праву Республики Казахстан. "
                "За ОДИН source-bound проход построй финальную профессиональную теорию дела, оспорь собственную первую гипотезу, "
                "проверь компетенцию суда и каждый способ защиты. Право только из официальных источников. "
                "Не трать поиск на общие статьи, если они не нужны для просительной части. "
                f"Язык результата: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_fast_professional_rk_research",
            schema=_PROFESSIONAL_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(response)
            if self._is_current_official_source(url)
        ]
        actual_by_canonical = {
            _canonical_url(url): url
            for url in actual_urls
            if _canonical_url(url)
        }

        verified_claims: list[str] = []
        rejected: list[str] = []
        used_urls: list[str] = []

        for point in payload.get("verified_points", []) or []:
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            provision_text = str(point.get("provision_text", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))

            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(
                        f"{statement} — не принят как VERIFIED: нет связи с реально открытым официальным источником."
                    )
                continue

            if _is_court_source(actual_url):
                if article.lower() != "официальный перечень судов":
                    rejected.append(
                        f"{statement} — источник суда не подтверждает норму материального/процессуального права."
                    )
                    continue
                line = f"{statement} [основание: {article}; источник: {actual_url}]"
            else:
                if not _is_adilet_source(actual_url):
                    rejected.append(f"{statement} — источник не Adilet.")
                    continue
                drift = paraphrase_defects(statement, provision_text)
                if drift:
                    rejected.append(f"{statement} — {'; '.join(drift[:3])}")
                    continue
                line = verified_claim_line(statement, article, provision_text, actual_url)

            if line not in verified_claims:
                verified_claims.append(line)
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unverified = [str(x).strip() for x in payload.get("unverified_claims", []) if str(x).strip()]
        unverified.extend(rejected)
        notes = _strategy_notes(payload)

        clean_notes: list[str] = []
        for note in notes:
            if note.startswith("VERIFIED_COURT:"):
                court = note.split(":", 1)[1].strip()
                normalized = "".join(ch.lower() for ch in court if ch.isalnum())
                if normalized and any(
                    normalized in "".join(ch.lower() for ch in claim if ch.isalnum())
                    for claim in verified_claims
                ):
                    clean_notes.append(note)
                continue
            clean_notes.append(note)

        research = LegalResearch(
            status=(
                VerificationStatus.VERIFIED
                if verified_claims and used_urls and not unverified
                else VerificationStatus.NEEDS_VERIFICATION
            ),
            applicable_law=[str(x).strip() for x in payload.get("applicable_law", []) if str(x).strip()],
            procedural_requirements=[str(x).strip() for x in payload.get("procedural_requirements", []) if str(x).strip()],
            verified_claims=list(dict.fromkeys(verified_claims)),
            unverified_claims=list(dict.fromkeys(unverified)),
            source_urls=list(dict.fromkeys(used_urls)),
            notes=list(dict.fromkeys(clean_notes)),
        )
        LOGGER.info(
            "FAST_PROFESSIONAL_RESEARCH verified=%d unverified=%d sources=%d remedies=%d",
            len(research.verified_claims),
            len(research.unverified_claims),
            len(research.source_urls),
            len([n for n in research.notes if n.startswith("REMEDY:")]),
        )
        return research

    @staticmethod
    def _drop_internal_quality_notes(draft: ClaimDraft) -> None:
        draft.verification_notes = [
            note for note in draft.verification_notes
            if not str(note).startswith(("KORGAN QUALITY", "SENIOR_PREFLIGHT_SCORE:"))
        ]

    async def draft_claim(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ClaimDraft:
        verified = "\n".join(f"- {item}" for item in research.verified_claims) or "- нет подтвержденных выводов"
        unverified = "\n".join(f"- {item}" for item in research.unverified_claims) or "- нет"
        strategy = _claim_strategy_block(research)

        prompt = (
            "Составь профессиональное исковое заявление для суда Республики Казахстан. Верни только структуру документа для Word.\n\n"
            "ОБЯЗАТЕЛЬНЫЙ PREFILING STANDARD:\n"
            "1. FACT LOCK: ни одного нового факта, даты, суммы, документа, эмоционального/медицинского последствия или события, которого нет в материалах пользователя.\n"
            "2. JURISDICTION: суд бери только из VERIFIED_COURT либо прямо из материалов. Не определяй экономический суд только по наличию ТОО; учитывай статус каждой стороны и VERIFIED ГПК.\n"
            "3. LEGAL THEORY: каждый пункт ПРОШУ СУД должен иметь цепочку факт -> доказательство -> VERIFIED-норма -> юридическое последствие.\n"
            "4. REMEDIES: решения REMEDY в карте обязательны. INCLUDE можно включать; EXCLUDE нельзя включать; NEEDS_FACTS нельзя превращать в выдуманный факт.\n"
            "5. Денежное требование не может содержать пустую сумму. Если для дополнительной суммы нет фактов/расчета, исключи её из просительной части.\n"
            "6. Не добавляй моральный вред только потому, что закон его допускает. Без пользовательских фактов о вреде — не заявляй его как установленный факт.\n"
            "7. Не добавляй декларативное требование о признании/расторжении/прекращении, если оно не нужно как самостоятельный способ защиты по VERIFIED.\n"
            "8. legal_basis содержит только конкретные статьи из VERIFIED и объясняет их связь с требованиями. Никаких URL и служебных комментариев.\n"
            "9. В приложениях только реальные доказательства из материалов. Не придумывай квитанцию госпошлины, доверенность, уведомление или акт.\n"
            "10. Цена и госпошлина могут быть исправлены детерминированным кодом после генерации; не угадывай их.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"ПРОФЕССИОНАЛЬНАЯ КАРТА:\n{strategy}\n\n"
            f"VERIFIED:\n{verified}\n\n"
            f"UNVERIFIED/РИСКИ:\n{unverified}"
            + PRO_CLAIM_PROMPT
        )

        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты практикующий судебный юрист KORGAN по Республике Казахстан. "
                "Пиши конечный судебный документ, а не юридическую консультацию. Перед возвратом структуры сам проверь суд, факты, способы защиты и просительную часть. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_fast_professional_claim",
            schema=_CLAIM_SCHEMA,
        )

        draft = ClaimDraft(status=research.status, source_urls=list(research.source_urls), **payload)
        self._drop_internal_quality_notes(draft)
        bind_verified_legal_basis(research, draft)
        _deterministic_pre_qa(case_context, research, draft)
        _apply_verified_article_353(case_context, research, draft, filing_date=_today_kz())

        deterministic = deterministic_claim_preflight(case_context, research, draft)
        quality = assess_document_quality("claim", case_context, research, draft)
        LOGGER.info(
            "FAST_PROFESSIONAL_PREFLIGHT stage=first score=%.1f deterministic=%s blockers=%s",
            quality.score,
            deterministic[:6],
            quality.hard_blockers[:6],
        )
        if quality.ready and not deterministic:
            draft.status = VerificationStatus.VERIFIED
            return draft

        issues = list(dict.fromkeys([*deterministic, *quality.repair_issues()]))[:16]
        if not claim_repair_has_actionable_issue(issues):
            # These gaps require a user fact or a new source-bound research
            # result. A no-search rewrite cannot resolve them safely.
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            final_score = min(quality.score, 6.9 if deterministic else quality.score)
            remaining = list(dict.fromkeys([*deterministic, *quality.hard_blockers]))
            note = (
                f"SENIOR_PREFLIGHT_SCORE: {final_score:.1f}/10 — "
                + ("; ".join(remaining[:6]) or "не достигнут порог 8.5")
            )
            draft.verification_notes.append(note)
            return draft

        current = {
            "title": draft.title,
            "court": draft.court,
            "claimant": draft.claimant,
            "defendant": draft.defendant,
            "price_of_claim": draft.price_of_claim,
            "facts": draft.facts,
            "legal_basis": draft.legal_basis,
            "requests": draft.requests,
            "attachments": draft.attachments,
            "verification_notes": draft.verification_notes,
            **pro_payload(draft),
        }
        repaired_payload = await self._quality_repair(
            schema_name="korgan_fast_professional_repair",
            schema=_CLAIM_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=current,
            issues=issues,
            language=language,
            document_label="исковое заявление после pre-filing проверки",
            extra_rules=(
                "8. Исправь каждый blocker. Не добавляй новый суд, факт или статью, которых нет в VERIFIED/материалах.\n"
                "9. Если дополнительное требование невозможно довести до готового вида без новых фактов пользователя — исключи его из ПРОШУ СУД.\n"
                "10. Суд можно исправить только на VERIFIED_COURT; если его нет, не выдумывай название.\n"
                "11. Удали любые придуманные переживания, стресс, расходы и иные обстоятельства.\n"
                f"12. Профессиональная карта:\n{strategy}"
            ),
        )
        repaired = ClaimDraft(status=research.status, source_urls=list(research.source_urls), **repaired_payload)
        self._drop_internal_quality_notes(repaired)
        bind_verified_legal_basis(research, repaired)
        _deterministic_pre_qa(case_context, research, repaired)
        _apply_verified_article_353(case_context, research, repaired, filing_date=_today_kz())

        deterministic2 = deterministic_claim_preflight(case_context, research, repaired)
        quality2 = assess_document_quality("claim", case_context, research, repaired)
        LOGGER.info(
            "FAST_PROFESSIONAL_PREFLIGHT stage=repaired score=%.1f deterministic=%s blockers=%s",
            quality2.score,
            deterministic2[:6],
            quality2.hard_blockers[:6],
        )
        if quality2.ready and not deterministic2:
            repaired.status = VerificationStatus.VERIFIED
            return repaired

        repaired.status = VerificationStatus.NEEDS_VERIFICATION
        final_score = min(quality2.score, 6.9 if deterministic2 else quality2.score)
        remaining = list(dict.fromkeys([*deterministic2, *quality2.hard_blockers]))
        note = f"SENIOR_PREFLIGHT_SCORE: {final_score:.1f}/10 — " + ("; ".join(remaining[:6]) or "не достигнут порог 8.5")
        repaired.verification_notes.append(note)
        return repaired
