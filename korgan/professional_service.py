from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from korgan.document_quality import assess_document_quality
from korgan.fast_v2_production_legal import _deterministic_pre_qa
from korgan.late_interest_hotfix import _apply_verified_article_353, _today_kz
from korgan.legal_types import ClaimDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _CLAIM_SCHEMA
from korgan.provision_check import paraphrase_defects, verified_claim_line
from korgan.robust_production_legal import _is_adilet_source, _is_court_source
from korgan.universal_quality_service import UniversalQualityProductionService, _quality_note
from korgan.verified_openai import _actual_response_urls, _canonical_url

LOGGER = logging.getLogger(__name__)


_PROFESSIONAL_RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "applicable_law": {"type": "array", "items": {"type": "string"}},
        "procedural_requirements": {"type": "array", "items": {"type": "string"}},
        "case_theory": {"type": "array", "items": {"type": "string"}},
        "remedies": {"type": "array", "items": {"type": "string"}},
        "evidence_map": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
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
        "unverified_claims": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "applicable_law",
        "procedural_requirements",
        "case_theory",
        "remedies",
        "evidence_map",
        "risks",
        "verified_points",
        "unverified_claims",
        "notes",
    ],
    "additionalProperties": False,
}


def _professional_research_prompt(case_context: str, *, max_chars: int, checked_on: str) -> str:
    return (
        f"Дата проверки: {checked_on}. Проведи профессиональное исследование дела исключительно по действующему праву Республики Казахстан.\n\n"
        "РАБОТАЙ КАК СУДЕБНЫЙ ЮРИСТ, А НЕ КАК ГЕНЕРАТОР ТЕКСТА. Сначала построй юридическую теорию дела, затем проверяй право.\n\n"
        "ЭТАПЫ АНАЛИЗА:\n"
        "1. Определи из фактов юридические отношения сторон и реальную цель клиента. Не принимай бытовое название договора или требования за правильную квалификацию без проверки.\n"
        "2. Для каждого возможного основания требования разложи состав на юридически значимые элементы: что должно быть доказано, кем и каким фактом.\n"
        "3. Выбери основной способ защиты и допустимые альтернативные способы. Не смешивай несовместимые конструкции; альтернативное основание помечай как альтернативное.\n"
        "4. Найди точные материальные нормы, которые поддерживают каждый элемент и каждый способ защиты. Общие статьи без связи с требованием недостаточны.\n"
        "5. Отдельно проверь процесс: родовую/предметную и территориальную подсудность, обязательный досудебный порядок только если он прямо установлен, сроки обращения/исковой давности, требования к содержанию и приложениям, госпошлину или льготу.\n"
        "6. Построй evidence_map: юридический элемент -> какой факт из материалов его подтверждает -> какое доказательство уже есть -> чего объективно не хватает. Не придумывай доказательства.\n"
        "7. В risks перечисли только реальные юридические риски: конкурирующая квалификация, отсутствие элемента состава, проблема с доказательством, сроком, подсудностью или предпосылкой требования.\n\n"
        "SOURCE-BOUND ПРАВИЛА:\n"
        "8. Материальное и процессуальное право подтверждай только по adilet.zan.kz. gov.kz/sud.gov.kz допустимы только для официального наименования и территории конкретного суда.\n"
        "9. Каждый verified_point обязан содержать применимый вывод, точную статью/пункт, дословный provision_text и URL страницы, реально открытой через web search.\n"
        "10. statement должен следовать из provision_text без расширения смысла. Если норма не подтверждает вывод прямо, вывод не VERIFIED.\n"
        "11. Не подбирай статьи по памяти и не подменяй точную норму соседней статьёй той же главы.\n"
        "12. Не делай вывод о наличии/отсутствии обязательного досудебного порядка, льготы, срока или подсудности из одного отсутствия результата поиска. Без прямой нормы это unverified_claims.\n"
        "13. Если точное официальное наименование суда подтверждено, добавь в notes строку ровно вида 'VERIFIED_COURT: <официальное наименование суда>'.\n"
        "14. case_theory, remedies, evidence_map и risks должны опираться только на факты пользователя и VERIFIED-нормы. Если для вывода права не хватает — прямо обозначь это.\n\n"
        f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:max_chars]}"
    )


def _strategy_notes(payload: dict[str, Any]) -> list[str]:
    notes = [str(x).strip() for x in payload.get("notes", []) if str(x).strip()]
    for key, prefix in (
        ("case_theory", "CASE_THEORY"),
        ("remedies", "REMEDY"),
        ("evidence_map", "EVIDENCE_MAP"),
        ("risks", "RISK"),
    ):
        for value in payload.get(key, []) or []:
            text = str(value).strip()
            if text:
                notes.append(f"{prefix}: {text}")
    return list(dict.fromkeys(notes))


def _claim_strategy_block(research: LegalResearch) -> str:
    values = [
        note for note in research.notes
        if str(note).startswith(("CASE_THEORY:", "REMEDY:", "EVIDENCE_MAP:", "RISK:", "VERIFIED_COURT:"))
    ]
    return "\n".join(f"- {item}" for item in values) or "- стратегия не сформирована отдельно; опирайся на VERIFIED и факты"


class ProfessionalRKProductionService(UniversalQualityProductionService):
    """Production legal core built around issue analysis instead of case-specific patches.

    Telegram/menu/runtime remain unchanged. This class replaces only the legal
    reasoning core: issue decomposition -> source-bound RK research -> coherent
    case theory -> court draft -> deterministic release/quality gate.
    """

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]
        prompt = _professional_research_prompt(
            case_context,
            max_chars=self.settings.max_case_text_chars,
            checked_on=date.today().isoformat(),
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты ведущий судебный юрист и legal researcher KORGAN по праву Республики Казахстан. "
                "Твоя задача — не перечислять статьи, а построить проверяемую теорию дела и подобрать нормы под юридические элементы и способы защиты. "
                "Работай fail-closed по праву и fact-locked по обстоятельствам. "
                f"Язык результата: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_professional_rk_research",
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
                        f"{statement} — не принят как VERIFIED: нет подтвержденной связи с реально открытым официальным источником."
                    )
                continue

            if _is_court_source(actual_url):
                if article.lower() != "официальный перечень судов":
                    rejected.append(
                        f"{statement} — не принят как VERIFIED: источник суда не подтверждает норму материального/процессуального права."
                    )
                    continue
                verified_claims.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            else:
                if not _is_adilet_source(actual_url):
                    rejected.append(f"{statement} — не принят как VERIFIED: источник не Adilet.")
                    continue
                drift = paraphrase_defects(statement, provision_text)
                if drift:
                    rejected.append(
                        f"{statement} — не принят как VERIFIED: {'; '.join(drift[:3])}"
                    )
                    continue
                verified_claims.append(
                    verified_claim_line(statement, article, provision_text, actual_url)
                )

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

        if not verified_claims:
            unverified.append("Не подтверждено ни одного source-bound правового вывода по существу дела.")
        if not used_urls:
            unverified.append("Не получено допустимого официального источника для VERIFIED-вывода.")

        research = LegalResearch(
            status=(
                VerificationStatus.VERIFIED
                if verified_claims and used_urls and not unverified
                else VerificationStatus.NEEDS_VERIFICATION
            ),
            applicable_law=[str(x).strip() for x in payload.get("applicable_law", []) if str(x).strip()],
            procedural_requirements=[
                str(x).strip() for x in payload.get("procedural_requirements", []) if str(x).strip()
            ],
            verified_claims=verified_claims,
            unverified_claims=list(dict.fromkeys(unverified)),
            source_urls=used_urls,
            notes=list(dict.fromkeys(clean_notes)),
        )
        LOGGER.info(
            "PROFESSIONAL_RK_RESEARCH verified=%d unverified=%d sources=%d strategy=%d",
            len(research.verified_claims),
            len(research.unverified_claims),
            len(research.source_urls),
            len([n for n in research.notes if n.startswith(("CASE_THEORY:", "REMEDY:", "EVIDENCE_MAP:", "RISK:"))]),
        )
        return research

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
            "ПОРЯДОК РАБОТЫ:\n"
            "1. FACT LOCK: ни одного нового факта, даты, суммы, документа, адреса, ИИН/БИН или события, которого нет в материалах.\n"
            "2. Построй иск вокруг одной связной юридической теории. Основное требование должно вытекать из фактов и VERIFIED. Альтернативные основания используй только если они действительно совместимы как альтернативные, а не одновременно взаимоисключающие утверждения.\n"
            "3. Для каждого существенного требования мысленно проверь цепочку: юридический элемент -> факт -> доказательство -> VERIFIED-норма -> просительная часть. Если звено отсутствует, не маскируй пробел общей юридической фразой.\n"
            "4. legal_basis должен содержать конкретные статьи только из VERIFIED и объяснять, какой именно элемент/способ защиты подтверждает каждая норма. Не вставляй статьи ради количества.\n"
            "5. Просительная часть должна быть процессуально исполнимой и логически соответствовать выбранному способу защиты. Если для денежного требования по VERIFIED предварительно требуется прекращение/расторжение/признание или иной самостоятельный способ защиты, отрази это согласованно; не придумывай такую предпосылку без VERIFIED.\n"
            "6. Фактическую часть изложи как профессиональную хронологию: отношения сторон -> исполнение истца -> обязанность ответчика -> нарушение -> досудебные действия, если они реально были -> последствия -> обращение в суд.\n"
            "7. Суд указывай только если он подтвержден материалами или строкой VERIFIED_COURT. Цена иска и госпошлина не должны угадываться моделью: детерминированный код обработает их после генерации.\n"
            "8. В приложениях перечисляй только реально имеющиеся у пользователя доказательства. Не придумывай квитанцию госпошлины, уведомление об отправке, доверенность, акт или иной документ.\n"
            "9. В тексте иска запрещены URL, Markdown, KORGAN, QA STATUS, PRELIMINARY, NEEDS_VERIFICATION, советы пользователю и внутренние комментарии. Неизвестные формальные данные оставляй пустыми/нейтральными в структуре; runtime сам добавит безопасную обработку.\n"
            "10. Стиль — как у практикующего судебного юриста: точные формулировки, без разговорной прозы, без повторов, без деклараций, не поддержанных нормой или фактом.\n\n"
            f"МАТЕРИАЛЫ ДЕЛА:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"ПРОФЕССИОНАЛЬНАЯ КАРТА ДЕЛА:\n{strategy}\n\n"
            f"VERIFIED ПРАВО:\n{verified}\n\n"
            f"НЕПОДТВЕРЖДЕННОЕ ПРАВО/РИСКИ (не выдавать как установленное):\n{unverified}"
        )

        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты ведущий судебный юрист KORGAN по Республике Казахстан. "
                "Пиши иск как документ, который будет читать судья: сначала связная теория дела, затем доказуемые факты, затем точное право и исполнимая просительная часть. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_professional_claim",
            schema=_CLAIM_SCHEMA,
        )

        draft = ClaimDraft(
            status=research.status,
            source_urls=list(research.source_urls),
            **payload,
        )
        _deterministic_pre_qa(case_context, research, draft)
        _apply_verified_article_353(case_context, research, draft, filing_date=_today_kz())

        first = assess_document_quality("claim", case_context, research, draft)
        LOGGER.info(
            "PROFESSIONAL_CLAIM_QUALITY stage=first score=%.1f ready=%s blockers=%s",
            first.score,
            first.ready,
            first.hard_blockers[:6],
        )
        if first.ready:
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
        }
        payload = await self._quality_repair(
            schema_name="korgan_professional_claim_repair",
            schema=_CLAIM_SCHEMA,
            case_context=case_context,
            research=research,
            current_payload=current,
            issues=first.repair_issues(),
            language=language,
            document_label="исковое заявление",
            extra_rules=(
                "8. Используй профессиональную карту дела ниже как обязательный план исправления; не своди ремонт к косметической правке.\n"
                + strategy
                + "\n9. Проверь связку 'элемент -> факт -> доказательство -> VERIFIED-норма -> требование' для каждого пункта просительной части."
            ),
        )
        repaired = ClaimDraft(
            status=research.status,
            source_urls=list(research.source_urls),
            **payload,
        )
        _deterministic_pre_qa(case_context, research, repaired)
        _apply_verified_article_353(case_context, research, repaired, filing_date=_today_kz())

        second = assess_document_quality("claim", case_context, research, repaired)
        LOGGER.info(
            "PROFESSIONAL_CLAIM_QUALITY stage=repaired score=%.1f ready=%s blockers=%s",
            second.score,
            second.ready,
            second.hard_blockers[:6],
        )
        if not second.ready:
            repaired.status = VerificationStatus.NEEDS_VERIFICATION
            note = _quality_note(second.score, second.repair_issues())
            if note not in repaired.verification_notes:
                repaired.verification_notes.append(note)
        return repaired
