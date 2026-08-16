from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from korgan.contract_numbering import count_literal_numbers
from korgan.contract_preamble import PREAMBLE_TEMPLATE, preamble_defects
from korgan.fast_v2_production_legal import ProductionOpenAILegalService as _FastV2
from korgan.legal_routing import ClaimProfile, detect_claim_profile, detect_contract_profile
from korgan.legal_types import ContractDraft, LegalResearch, VerificationStatus
from korgan.openai_legal import _VALIDATION_SCHEMA
from korgan.provision_check import paraphrase_defects, verified_claim_line
from korgan.verified_openai import (
    _VERIFIED_RESEARCH_SCHEMA,
    _actual_response_urls,
    _canonical_url,
)

LOGGER = logging.getLogger(__name__)


_CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contract_type": {"type": "string"},
        "title": {"type": "string"},
        "place_and_date": {"type": "string"},
        "party_a": {"type": "array", "items": {"type": "string"}},
        "party_b": {"type": "array", "items": {"type": "string"}},
        "preamble": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # Headings and clause texts carry NO numbers: numbering is
                    # generated at export time by korgan.contract_numbering.
                    "heading": {"type": "string"},
                    "clauses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "subclauses": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["text", "subclauses"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["heading", "clauses"],
                "additionalProperties": False,
            },
        },
        "requisites_a": {"type": "array", "items": {"type": "string"}},
        "requisites_b": {"type": "array", "items": {"type": "string"}},
        "verification_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "contract_type", "title", "place_and_date", "party_a", "party_b", "preamble",
        "sections", "requisites_a", "requisites_b", "verification_notes"
    ],
    "additionalProperties": False,
}

_CONTRACT_VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "critical_errors": {"type": "array", "items": {"type": "string"}},
        "unsupported_legal_claims": {"type": "array", "items": {"type": "string"}},
        "missing_essential_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["critical_errors", "unsupported_legal_claims", "missing_essential_terms"],
    "additionalProperties": False,
}

_FORBIDDEN_CONTRACT_TEXT = (
    "needs_verification",
    "http://",
    "https://",
    "можно адаптировать",
    "если нужно",
    "могу доработать",
    "официальные источники",
    "###",
    "**",
)


def _today_kz() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_court_source(url: str) -> bool:
    host = _host(url)
    return host in {"gov.kz", "sud.gov.kz"} or host.endswith(".gov.kz") or host.endswith(".sud.gov.kz")


def _is_adilet_source(url: str) -> bool:
    host = _host(url)
    return host == "adilet.zan.kz" or host.endswith(".adilet.zan.kz")


def _profile_has_material_support(profile: ClaimProfile, verified_claims: list[str]) -> bool:
    if not profile.required_article_hints:
        return True
    text = "\n".join(verified_claims).lower()
    return all(re.search(rf"(?<!\d){re.escape(article)}(?!\d)", text) for article in profile.required_article_hints)


def _contract_body(draft: ContractDraft) -> str:
    return "\n".join(draft.body_lines())


def _contract_hard_issues(draft: ContractDraft) -> list[str]:
    lowered = _contract_body(draft).lower()
    return [f"служебный/чатовый текст попал в договор: {needle}" for needle in _FORBIDDEN_CONTRACT_TEXT if needle in lowered]


def _contract_structure_issues(draft: ContractDraft) -> list[str]:
    """Structural defects worth a repair round but never worth killing the draft.

    A missing preamble is a document-integrity failure (final-legal-qa.md, H),
    yet it is recoverable: the export can always fall back to the placeholder
    identification block, so this must not fail the contract closed.
    """
    return [f"преамбула договора: {defect}" for defect in preamble_defects(draft.preamble)]


class ProductionOpenAILegalService(_FastV2):
    """KORGAN production runtime: fast source-bound claims + source-bound contracts."""

    async def _structured_response(
        self,
        *,
        model: str,
        instructions: str,
        content: list[dict[str, Any]] | str,
        schema_name: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": content,
            "text": self._json_schema(schema_name, schema),
            "store": False,
            "prompt_cache_key": f"korgan:{schema_name}:v4",
        }

        if model == "gpt-5.1" or model.startswith("gpt-5.1-"):
            kwargs["reasoning"] = {"effort": "none"}

        # Normal path stays compact. Only a genuinely truncated JSON retries.
        output_limits = {
            "korgan_consult_research": 1600,
            "korgan_verified_legal_research": 2300,
            "korgan_court_ready_validation": 1300,
            "korgan_court_ready_claim": 4300,
            "korgan_repaired_claim": 4300,
            "korgan_contract_research": 2200,
            "korgan_contract_draft": 5200,
            "korgan_contract_validation": 1300,
            "korgan_contract_repair": 5200,
        }
        if schema_name in output_limits:
            kwargs["max_output_tokens"] = output_limits[schema_name]

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "required"
            kwargs["include"] = ["web_search_call.action.sources"]

        started = time.perf_counter()
        response = await self.client.responses.create(**kwargs)
        first_elapsed = time.perf_counter() - started

        try:
            payload = json.loads(response.output_text)
        except json.JSONDecodeError as exc:
            if schema_name not in output_limits:
                raise
            LOGGER.warning(
                "KORGAN structured JSON truncated: schema=%s chars=%d error=%s; retrying step only",
                schema_name,
                len(response.output_text or ""),
                exc,
            )
            retry_kwargs = dict(kwargs)
            retry_kwargs["max_output_tokens"] = 6200 if "contract" in schema_name else 4800
            retry_started = time.perf_counter()
            response = await self.client.responses.create(**retry_kwargs)
            retry_elapsed = time.perf_counter() - retry_started
            payload = json.loads(response.output_text)
            LOGGER.info(
                "KORGAN structured retry: schema=%s seconds=%.2f chars=%d",
                schema_name,
                retry_elapsed,
                len(response.output_text or ""),
            )

        LOGGER.info(
            "KORGAN OpenAI structured call: schema=%s seconds=%.2f actual_web_urls=%d",
            schema_name,
            first_elapsed,
            len(_actual_response_urls(response)),
        )
        return payload, response

    async def validate_claim(self, case_context: str, research: LegalResearch, draft) -> dict[str, list[str]]:
        """Compact independent FINAL LEGAL QA to keep latency under control."""
        draft_payload = {
            "title": draft.title,
            "court": draft.court,
            "claimant": draft.claimant,
            "defendant": draft.defendant,
            "price_of_claim": draft.price_of_claim,
            "facts": draft.facts,
            "legal_basis": draft.legal_basis,
            "requests": draft.requests,
            "attachments": draft.attachments,
            "state_duty": draft.state_duty,
        }
        prompt = (
            "FINAL LEGAL QA проекта иска. Верни только реальные дефекты, максимум 6 кратких пунктов на категорию.\n"
            "CRITICAL_ERRORS: только выдуманные/перепутанные факты, роли, суммы, даты или внутренний текст в судебном документе.\n"
            "UNSUPPORTED_LEGAL_CLAIMS: только юридические выводы/статьи, которых нет в VERIFIED. Если VERIFIED прямо подтверждает профильные нормы и квалификацию, не объявляй саму квалификацию ошибкой.\n"
            "MISSING_REQUIRED_FIELDS: только действительно отсутствующие обязательные реквизиты/приложения. Отсутствующая квитанция госпошлины — это missing field, НЕ critical error и не причина запрещать выдачу предварительного Word-проекта.\n"
            "Не считай место заключения/передачи денег адресом стороны. Не требуй телефон/e-mail ответчика, если закон не делает их обязательными при неизвестности. "
            "Не требуй, чтобы в приложениях был документ, которого пользователь ещё не загрузил; просто укажи его в missing_required_fields.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:36000]}\n\n"
            f"VERIFIED:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
            f"ПРОЕКТ:\n{json.dumps(draft_payload, ensure_ascii=False)}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_validation_model,
            instructions="Ты независимый финальный валидатор KORGAN. Строгий, но не создавай ложные блокировки.",
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_court_ready_validation",
            schema=_VALIDATION_SCHEMA,
        )
        return {
            "critical_errors": [str(x) for x in payload.get("critical_errors", [])],
            "unsupported_legal_claims": [str(x) for x in payload.get("unsupported_legal_claims", [])],
            "missing_required_fields": [str(x) for x in payload.get("missing_required_fields", [])],
        }

    async def _profiled_claim_research(
        self,
        case_context: str,
        language: str,
        *,
        search_context_size: str,
    ) -> LegalResearch:
        profile = detect_claim_profile(case_context)
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": search_context_size,
        }]

        prompt = (
            f"Дата проверки: {_today_kz()}. Исследуй правовую основу конкретного иска по действующему праву Республики Казахстан.\n\n"
            f"ПРЕДВАРИТЕЛЬНЫЙ ПРОФИЛЬ: {profile.label}. Это только маршрутизация поиска.\n"
            f"ОБЯЗАТЕЛЬНЫЙ ФОКУС: {profile.research_focus}\n\n"
            "ПРАВИЛА:\n"
            "1. Сначала установи по фактам требуемый способ судебной защиты и материально-правовую природу требования; затем найди именно профильные нормы.\n"
            "2. Каждый verified_point должен содержать конкретный применимый вывод, точную статью/пункт и URL реально открытой официальной страницы.\n"
            "3. Материальное и процессуальное право подтверждай только по Adilet. gov.kz/sud.gov.kz можно использовать только для точного наименования суда, article='официальный перечень судов'.\n"
            "4. Общая ссылка на ГК без профильной нормы не достаточна для квалификации конкретного договорного или внедоговорного требования.\n"
            "5. Для гражданского процесса проверяй только реально нужные нормы о компетенции, территориальной подсудности, форме и приложениях.\n"
            "6. Госпошлину проверяй по действующему Налоговому кодексу; не выдумывай ставку. Сумму затем считает код.\n"
            "7. Судебный приказ не предлагай без прямого действующего основания.\n"
            "8. При полном адресе ответчика проверь правило подсудности и, если официальный источник позволяет точно установить суд, добавь notes: 'VERIFIED_COURT: <точное название>'.\n"
            "9. Всё неподтвержденное помещай только в unverified_claims.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}"
        )

        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты юридический исследователь KORGAN. Работай fail-closed и source-bound. "
                "Не подменяй профильную материальную норму общими статьями. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_verified_legal_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [url for url in _actual_response_urls(response) if self._is_current_official_source(url)]
        actual_by_canonical = {_canonical_url(url): url for url in actual_urls if _canonical_url(url)}
        verified_claims: list[str] = []
        rejected: list[str] = []
        used_urls: list[str] = []

        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            provision_text = str(point.get("provision_text", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(f"{statement} — не принят как VERIFIED: нет source-bound официального источника.")
                continue
            if _is_court_source(actual_url) and article.lower() != "официальный перечень судов":
                rejected.append(f"{statement} — не принят как VERIFIED: источник суда не подтверждает норму права.")
                continue
            if not _is_court_source(actual_url) and not _is_adilet_source(actual_url):
                rejected.append(f"{statement} — не принят как VERIFIED: недопустимый источник нормы права.")
                continue
            # An official court listing confirms a court's name, not a provision,
            # so it is the one case with no provision text to compare against.
            if not _is_court_source(actual_url):
                drift = paraphrase_defects(statement, provision_text)
                if drift:
                    rejected.append(f"{statement} — не принят как VERIFIED: {'; '.join(drift[:3])}")
                    continue
                verified_claims.append(verified_claim_line(statement, article, provision_text, actual_url))
            else:
                verified_claims.append(f"{statement} [основание: {article}; источник: {actual_url}]")
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unverified = [str(x) for x in payload.get("unverified_claims", [])] + rejected
        notes = [str(x) for x in payload.get("notes", [])]
        clean_notes: list[str] = []
        for note in notes:
            if note.startswith("VERIFIED_COURT:"):
                court = note.split(":", 1)[1].strip()
                normalized = "".join(ch.lower() for ch in court if ch.isalnum())
                if normalized and any(normalized in "".join(ch.lower() for ch in claim if ch.isalnum()) for claim in verified_claims):
                    clean_notes.append(note)
                continue
            clean_notes.append(note)

        if not verified_claims:
            unverified.append("Не подтверждено ни одного source-bound правового вывода.")
        if not used_urls:
            unverified.append("Не получено допустимого официального источника для VERIFIED-вывода.")

        return LegalResearch(
            status=VerificationStatus.VERIFIED if verified_claims and used_urls and not unverified else VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[str(x) for x in payload.get("applicable_law", [])],
            procedural_requirements=[str(x) for x in payload.get("procedural_requirements", [])],
            verified_claims=verified_claims,
            unverified_claims=unverified,
            source_urls=used_urls,
            notes=clean_notes,
        )

    async def research_case(self, case_context: str, language: str = "ru") -> LegalResearch:
        profile = detect_claim_profile(case_context)
        cache_key = self._claim_cache_key(case_context, language)
        cached = self._claim_research_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] <= 15 * 60:
            LOGGER.info("KORGAN claim research cache HIT profile=%s", profile.code)
            return cached[1]

        started = time.perf_counter()
        research = await self._profiled_claim_research(
            case_context,
            language,
            search_context_size=profile.search_context_size,
        )

        # A known profile must have its material-law backbone. If a low/medium
        # web-search pass returned only generic law, repeat the SAME targeted
        # research once with high context instead of drafting on weak law.
        if not research.verified_claims or not research.source_urls or not _profile_has_material_support(profile, research.verified_claims):
            LOGGER.info("KORGAN claim research targeted fallback profile=%s", profile.code)
            research = await self._profiled_claim_research(case_context, language, search_context_size="high")

        self._claim_research_cache[cache_key] = (time.monotonic(), research)
        LOGGER.info(
            "KORGAN claim research total seconds=%.2f profile=%s sources=%d",
            time.perf_counter() - started,
            profile.code,
            len(research.source_urls),
        )
        return research

    async def research_contract(self, case_context: str, language: str = "ru") -> LegalResearch:
        profile = detect_contract_profile(case_context)
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": ["adilet.zan.kz"]},
            "search_context_size": profile.search_context_size,
        }]
        prompt = (
            f"Дата проверки: {_today_kz()}. Подготовь правовое исследование для составления договора по законодательству Республики Казахстан.\n\n"
            f"ПРЕДВАРИТЕЛЬНЫЙ ВИД: {profile.label}.\n"
            f"ФОКУС: {profile.research_focus}\n\n"
            "Проверь по Adilet: точный вид договора, обязательную форму, существенные/обязательные условия, ограничения закона, "
            "права и обязанности, порядок исполнения/приемки/оплаты, прекращение и ответственность. "
            "Не придумывай штрафы, проценты, сроки или коммерческие условия — они должны идти от пользователя либо от явно применимой диспозитивной/императивной нормы. "
            "Каждый verified_point — конкретный вывод + точная статья/пункт + URL реально открытой страницы."
            f"\n\nМАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}"
        )
        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты договорный юрист KORGAN по праву Республики Казахстан. Проверяй текущую редакцию только по Adilet. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_contract_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [
            url for url in _actual_response_urls(response)
            if _is_adilet_source(url) and self._is_current_official_source(url)
        ]
        actual_by_canonical = {_canonical_url(url): url for url in actual_urls if _canonical_url(url)}
        verified: list[str] = []
        rejected: list[str] = []
        used: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            provision_text = str(point.get("provision_text", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(str(point.get("source_url", "")).strip()))
            if not statement or not article or not actual_url:
                if statement:
                    rejected.append(f"{statement} — не принят как VERIFIED: нет source-bound Adilet источника.")
                continue
            drift = paraphrase_defects(statement, provision_text)
            if drift:
                rejected.append(f"{statement} — не принят как VERIFIED: {'; '.join(drift[:3])}")
                continue
            verified.append(verified_claim_line(statement, article, provision_text, actual_url))
            if actual_url not in used:
                used.append(actual_url)

        unverified = [str(x) for x in payload.get("unverified_claims", [])] + rejected
        return LegalResearch(
            status=VerificationStatus.VERIFIED if verified and used and not unverified else VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[str(x) for x in payload.get("applicable_law", [])],
            procedural_requirements=[str(x) for x in payload.get("procedural_requirements", [])],
            verified_claims=verified,
            unverified_claims=unverified,
            source_urls=used,
            notes=[str(x) for x in payload.get("notes", [])],
        )

    async def validate_contract(
        self,
        case_context: str,
        research: LegalResearch,
        draft: ContractDraft,
    ) -> dict[str, list[str]]:
        payload_for_qa = {
            "contract_type": draft.contract_type,
            "title": draft.title,
            "place_and_date": draft.place_and_date,
            "party_a": draft.party_a,
            "party_b": draft.party_b,
            "preamble": draft.preamble,
            "sections": [
                {
                    "heading": s.heading,
                    "clauses": [{"text": c.text, "subclauses": c.subclauses} for c in s.clauses],
                }
                for s in draft.sections
            ],
            "requisites_a": draft.requisites_a,
            "requisites_b": draft.requisites_b,
        }
        prompt = (
            "FINAL LEGAL QA договора. Верни только реальные дефекты, кратко.\n"
            "critical_errors: перепутанные стороны/роли, выдуманные суммы/сроки/штрафы, противоречивые условия, незаконная или внутренне невозможная конструкция.\n"
            "unsupported_legal_claims: ссылки/обязательные утверждения о праве, которых нет в VERIFIED.\n"
            "missing_essential_terms: только условия/реквизиты, без которых этот вид договора нельзя безопасно считать готовым к подписанию. "
            "Не блокируй сам Word-проект из-за missing_essential_terms — он может быть PRELIMINARY DRAFT.\n"
            "Отдельно проверь преамбулу: она обязана идентифицировать обе стороны, их роли по договору и основание полномочий "
            "каждого подписанта (устав / доверенность / свидетельство о государственной регистрации ИП). Реквизиты в конце документа "
            "преамбулу не заменяют. Неполная преамбула — missing_essential_terms.\n"
            "Нумерация в heading и clauses отсутствует намеренно: её проставляет экспорт. Не считай это дефектом.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:36000]}\n\n"
            f"VERIFIED:\n{json.dumps(research.verified_claims, ensure_ascii=False)}\n\n"
            f"ДОГОВОР:\n{json.dumps(payload_for_qa, ensure_ascii=False)}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_validation_model,
            instructions="Ты независимый договорный QA-юрист KORGAN. Не придумывай дефекты, но не пропускай реальные юридические риски.",
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_contract_validation",
            schema=_CONTRACT_VALIDATION_SCHEMA,
        )
        return {
            "critical_errors": [str(x) for x in payload.get("critical_errors", [])],
            "unsupported_legal_claims": [str(x) for x in payload.get("unsupported_legal_claims", [])],
            "missing_essential_terms": [str(x) for x in payload.get("missing_essential_terms", [])],
        }

    async def draft_contract(
        self,
        case_context: str,
        research: LegalResearch,
        language: str = "ru",
    ) -> ContractDraft:
        profile = detect_contract_profile(case_context)
        verified_block = "\n".join(f"- {x}" for x in research.verified_claims) or "нет подтвержденных выводов"
        unverified_block = "\n".join(f"- {x}" for x in research.unverified_claims) or "нет"
        prompt = (
            f"Составь профессиональный {profile.label} по законодательству Республики Казахстан. Верни структуру для Word.\n\n"
            "ПРАВИЛА:\n"
            "1. Стороны, роли, предмет, суммы, сроки, порядок оплаты/приемки и иные коммерческие условия бери только из материалов. Не придумывай.\n"
            "2. Юридическую конструкцию, обязательные условия и ограничения строй только на VERIFIED.\n"
            "3. Не придумывай пеню, штраф, проценты, обеспечение, автоматическую пролонгацию, подсудность или односторонние права, если этого нет в материалах или VERIFIED не делает это обязательным.\n"
            "4. Если существенного условия не хватает — используй '[ТРЕБУЕТ УТОЧНЕНИЯ: ...]' и продублируй вопрос в verification_notes.\n"
            "5. Сделай договор полноценным: предмет; права/обязанности; порядок исполнения/приемки; цена/оплата если применимо; ответственность без выдуманных ставок; срок/прекращение; форс-мажор при уместности; споры; заключительные положения; реквизиты и подписи. "
            "Не добавляй раздел, который не подходит этому виду договора.\n"
            "6. В тексте договора запрещены URL, NEEDS_VERIFICATION, Markdown и чатовые советы.\n"
            "7. Не вставляй статьи закона ради красоты: нормы используются как юридический контроль конструкции, а ссылки в тексте нужны только если действительно уместны.\n"
            "8. НУМЕРАЦИЯ: её полностью проставляет экспорт в Word. Пиши без единого номера. "
            "heading — только название раздела ('Предмет Договора', НЕ '1. Предмет Договора'). "
            "clauses[].text — только текст пункта ('По настоящему Договору Исполнитель обязуется...', НЕ '1.1. По настоящему Договору...'). "
            "Подпункт оформляй элементом clauses[].subclauses, а не номером '3.1.1.' внутри текста. "
            "Любой номер, написанный тобой, будет отброшен и приведёт к потере структуры.\n"
            "9. ПРЕАМБУЛА (поле preamble) обязательна и всегда идёт полным вводным абзацем, идентифицирующим обе стороны, "
            "их роли по договору и основание полномочий каждого подписанта (устав — для директора ТОО/АО, "
            "доверенность № и дата — для представителя, свидетельство о государственной регистрации ИП № и дата — для ИП). Формат:\n"
            f"«{PREAMBLE_TEMPLATE}»\n"
            "Если реквизиты стороны, ФИО подписанта или основание полномочий неизвестны — сохрани структуру абзаца целиком "
            "и подставь на соответствующее место '[ТРЕБУЕТ УТОЧНЕНИЯ: ...]'. Сокращать преамбулу до "
            "'совместно именуемые «Стороны», заключили настоящий Договор' запрещено: реквизиты в конце документа преамбулу не заменяют.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified_block}\n\n"
            f"НЕ ПОДТВЕРЖДЕНО:\n{unverified_block}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты старший договорный юрист KORGAN. Пиши сбалансированный, практически применимый договор без выдуманных условий. "
                f"Язык: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_contract_draft",
            schema=_CONTRACT_SCHEMA,
        )
        self._log_numbering_conflicts(payload, "draft")
        draft = ContractDraft.from_payload(status=research.status, source_urls=research.source_urls, payload=payload)

        hard = _contract_hard_issues(draft)
        structural = _contract_structure_issues(draft)
        validation = await self.validate_contract(case_context, research, draft)
        blocking = list(dict.fromkeys(validation["critical_errors"] + validation["unsupported_legal_claims"] + hard))
        if blocking or structural:
            repair_prompt = (
                "Исправь договор только по перечисленным замечаниям. Не добавляй новых фактов, сумм, сроков, штрафов или правовых утверждений.\n"
                "Нумерацию не пиши: heading и clauses[].text идут без номеров, подпункты — только в clauses[].subclauses.\n"
                "Преамбула должна полностью идентифицировать обе стороны, их роли и основание полномочий подписантов "
                f"по формату: «{PREAMBLE_TEMPLATE}»\n\n"
                f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
                f"VERIFIED:\n{verified_block}\n\n"
                f"ЗАМЕЧАНИЯ:\n{json.dumps(blocking + structural, ensure_ascii=False)}\n\n"
                f"ТЕКУЩИЙ ПРОЕКТ:\n{json.dumps(payload, ensure_ascii=False)}"
            )
            repaired, _ = await self._structured_response(
                model=self.settings.openai_model,
                instructions="Ты редактор договоров KORGAN. Исправляй только указанные дефекты и ничего не выдумывай.",
                content=[{"role": "user", "content": [{"type": "input_text", "text": repair_prompt}]}],
                schema_name="korgan_contract_repair",
                schema=_CONTRACT_SCHEMA,
            )
            self._log_numbering_conflicts(repaired, "repair")
            draft = ContractDraft.from_payload(status=research.status, source_urls=research.source_urls, payload=repaired)
            hard = _contract_hard_issues(draft)
            structural = _contract_structure_issues(draft)
            validation = await self.validate_contract(case_context, research, draft)
            blocking = list(dict.fromkeys(validation["critical_errors"] + validation["unsupported_legal_claims"] + hard))
            if blocking:
                # Do not emit a legally unsafe contract as final. Missing terms
                # are allowed as PRELIMINARY; fabricated/unsupported content is not.
                raise RuntimeError("CONTRACT_QA_BLOCK: " + "; ".join(blocking[:10]))

        # A preamble the model would not repair is not fatal: the export
        # renders the identification block with visible gaps, and the defect is
        # surfaced to the user instead of being hidden.
        for item in structural:
            if item not in draft.verification_notes:
                draft.verification_notes.append(item)
        for item in validation["missing_essential_terms"]:
            if item not in draft.verification_notes:
                draft.verification_notes.append(item)
        if research.unverified_claims or draft.verification_notes:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
        return draft

    @staticmethod
    def _log_numbering_conflicts(payload: dict[str, Any], stage: str) -> None:
        conflicts = count_literal_numbers(payload)
        if conflicts:
            LOGGER.warning(
                "KORGAN contract numbering: model wrote %d literal number(s) at stage=%s; stripped on import",
                conflicts,
                stage,
            )
