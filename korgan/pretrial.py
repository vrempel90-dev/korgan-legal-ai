"""Source-bound pre-trial demand generation without changing claim logic."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.provision_check import paraphrase_defects, verified_claim_line
from korgan.response_legal import ProductionOpenAILegalService
from korgan.verified_openai import _VERIFIED_RESEARCH_SCHEMA, _actual_response_urls, _canonical_url

_PRETRIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "sender": {"type": "array", "items": {"type": "string"}},
        "recipient": {"type": "array", "items": {"type": "string"}},
        "facts": {"type": "array", "items": {"type": "string"}},
        "legal_basis": {"type": "array", "items": {"type": "string"}},
        "demands": {"type": "array", "items": {"type": "string"}},
        "deadline": {"type": "string"},
        "consequences": {"type": "array", "items": {"type": "string"}},
        "attachments": {"type": "array", "items": {"type": "string"}},
        "verification_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "sender", "recipient", "facts", "legal_basis", "demands",
        "deadline", "consequences", "attachments", "verification_notes"
    ],
    "additionalProperties": False,
}

_INTENT_RU = re.compile(r"(?i)\b(?:досудебн\w*\s+претензи\w*|претензи\w*)\b")
_INTENT_KK = re.compile(r"(?i)(?:сотқа\s+дейінгі\s+талап\w*|талап\s+хат\w*)")
_ACTION = re.compile(
    r"(?i)\b(?:подготов\w*|состав\w*|сформир\w*|сдел\w*|напиш\w*|"
    r"дайында\w*|жаса\w*|әзірле\w*|құрастыр\w*)\b"
)
_ADVICE_RU = re.compile(r"(?i)^\s*как\b")
_ADVICE_KK = re.compile(r"(?i)\bқалай\b")

_BASIS_RE = re.compile(r"\[основание:\s*(?P<article>.*?);", re.IGNORECASE | re.DOTALL)
_VERIFIED_LINE_RE = re.compile(
    r"^(?P<statement>.*?)\s*\[основание:\s*(?P<article>.*?);\s*текст\s+нормы:",
    re.IGNORECASE | re.DOTALL,
)
_GPK_RE = re.compile(r"(?i)\b(?:гпк\s*рк|гражданск\w*\s+процессуальн\w*\s+кодекс)\b")
_ADMIN_RE = re.compile(r"(?i)\b(?:аппк\s*рк|административн\w*\s+процедурн\w*.*процессуальн\w*)\b")
_COST_RE = re.compile(
    r"(?i)(?:госпошлин|судебн\w*\s+расход|расход\w*\s+по\s+оплате\s+помощи\s+представител|"
    r"возмещен\w*\s+расход\w*\s+.*представител)"
)
_SUBSTANTIVE_RE = re.compile(
    r"(?i)\b(?:долг\w*|задолженн\w*|обязательств\w*|договор\w*|шарт\w*|оплат\w*|"
    r"возврат\w*|взыска\w*|неустойк\w*|пен[яию]\b|процент\w*|убытк\w*|ущерб\w*|"
    r"услуг\w*|подряд\w*|работ\w*|поставк\w*|товар\w*|за[её]м\w*|аренд\w*|"
    r"трудов\w*|потребител\w*|расторг\w*|исполнени\w*|қарыз\w*|төлем\w*)\b"
)
_ARTICLE_TOKEN_RE = re.compile(
    r"(?i)(?:стать(?:я|и|е|ю|ёй|ей)|ст\.)\s*(\d+(?:-\d+)?)|\b(\d+(?:-\d+)?)\s*[-–]?\s*ба[пб]\w*"
)


def is_pretrial_request(text: str | None) -> bool:
    value = " ".join((text or "").split())
    if not value or _ADVICE_RU.search(value) or _ADVICE_KK.search(value):
        return False
    return bool((_INTENT_RU.search(value) or _INTENT_KK.search(value)) and _ACTION.search(value))


def requires_material_law(text: str | None) -> bool:
    return bool(_SUBSTANTIVE_RE.search(str(text or "")))


def _basis_label(line: str) -> str:
    match = _BASIS_RE.search(str(line or ""))
    return match.group("article").strip() if match else str(line or "")


def is_material_law_line(line: str | None) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    basis = _basis_label(text)
    if _GPK_RE.search(basis) or _ADMIN_RE.search(basis):
        return False
    if _COST_RE.search(text):
        return False
    return bool(re.search(r"\d", basis))


def material_verified_claims(research: LegalResearch) -> list[str]:
    return [str(line) for line in research.verified_claims if is_material_law_line(str(line))]


def _render_verified_material(line: str) -> str | None:
    match = _VERIFIED_LINE_RE.search(str(line or ""))
    if not match:
        return None
    statement = " ".join(match.group("statement").split()).strip(" .")
    article = " ".join(match.group("article").split()).strip(" .")
    if not statement or not article:
        return None
    return f"{statement}. Правовое основание: {article}."


def prioritize_material_basis(lines: list[str], research: LegalResearch) -> list[str]:
    """Put source-bound material law before any procedural/cost provisions."""
    additions: list[str] = []
    for verified in material_verified_claims(research):
        rendered = _render_verified_material(verified)
        if rendered and rendered not in additions:
            additions.append(rendered)
        if len(additions) >= 4:
            break

    current = [" ".join(str(line).split()).strip() for line in lines if str(line).strip()]
    material_current = [line for line in current if is_material_law_line(line)]
    procedural_current = [line for line in current if not is_material_law_line(line)]

    result: list[str] = []
    for line in [*additions, *material_current, *procedural_current]:
        key = re.sub(r"\W+", "", line.lower())
        if key and all(re.sub(r"\W+", "", x.lower()) != key for x in result):
            result.append(line)
    return result


def _article_tokens(text: str) -> set[str]:
    result: set[str] = set()
    for match in _ARTICLE_TOKEN_RE.finditer(text or ""):
        result.add(match.group(1) or match.group(2))
    return result


@dataclass(slots=True)
class PretrialDraft:
    status: VerificationStatus
    title: str
    sender: list[str]
    recipient: list[str]
    facts: list[str]
    legal_basis: list[str]
    demands: list[str]
    deadline: str
    consequences: list[str]
    attachments: list[str]
    verification_notes: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)

    def body_lines(self) -> list[str]:
        return [
            self.title, *self.sender, *self.recipient, *self.facts, *self.legal_basis,
            *self.demands, self.deadline, *self.consequences, *self.attachments,
        ]


def pretrial_release_blockers(draft: PretrialDraft, research: LegalResearch, case_context: str) -> list[str]:
    blockers: list[str] = []
    substantive_text = "\n".join([case_context, *draft.facts, *draft.demands])
    if not draft.facts:
        blockers.append("нет фактического основания требований")
    if not draft.demands:
        blockers.append("нет сформулированных требований")
    if requires_material_law(substantive_text):
        if not material_verified_claims(research):
            blockers.append("нет VERIFIED материально-правовой нормы под основное требование")
        if not any(is_material_law_line(line) for line in draft.legal_basis):
            blockers.append("материальная норма не перенесена в правовое обоснование претензии")

    verified_tokens = _article_tokens("\n".join(research.verified_claims))
    draft_tokens = _article_tokens("\n".join(draft.legal_basis))
    unsupported = sorted(draft_tokens - verified_tokens)
    if unsupported:
        blockers.append("в правовом обосновании есть неподтверждённые статьи: " + ", ".join(unsupported))
    return list(dict.fromkeys(blockers))


class PretrialProductionService(ProductionOpenAILegalService):
    """Current stable service plus pre-trial-only methods. Claim methods are inherited unchanged."""

    async def research_pretrial(self, case_context: str, language: str = "ru") -> LegalResearch:
        tools = [{
            "type": "web_search",
            "filters": {"allowed_domains": self.settings.legal_domains},
            "search_context_size": "high",
        }]
        prompt = (
            "Проведи source-bound исследование ТОЛЬКО для досудебной претензии по действующему праву Республики Казахстан.\n\n"
            "ПОРЯДОК ИССЛЕДОВАНИЯ:\n"
            "1. Сначала квалифицируй материальное правоотношение по фактам: услуги, подряд, поставка, заем, аренда, трудовое, потребительское или иное. Не угадывай вид договора.\n"
            "2. Для ОСНОВНОЙ задолженности/оплаты/возврата/исполнения сначала найди применимые действующие нормы ГК РК, если отношения регулируются гражданским правом.\n"
            "3. Затем найди специальные нормативные акты, если они применимы к конкретному виду отношений.\n"
            "4. ГПК РК, подсудность, госпошлина и расходы на представителя НЕ являются материально-правовым основанием основной задолженности. Они могут быть указаны только отдельно и только если действительно относятся к последующему судебному вопросу.\n"
            "5. Не используй норму о возмещении расходов на представителя как обоснование основной суммы долга.\n"
            "6. Каждый verified_point: точное применимое положение, точная статья/пункт, provision_text и URL реально открытого официального источника.\n"
            "7. Не придумывай право. Если материальная норма под основное требование не подтверждена — помести это в unverified_claims.\n"
            "8. Не превращай досудебную претензию в иск: процессуальные нормы вторичны, материальное право — основа требования.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}"
        )
        payload, response = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты практикующий юрист KORGAN по праву Республики Казахстан. Для досудебной претензии сначала устанавливай материально-правовую основу требования, затем только при необходимости процессуальные последствия. "
                "Работай строго source-bound по официальным источникам. "
                f"Язык результата: {'казахский' if language == 'kk' else 'русский'}."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_pretrial_research",
            schema=_VERIFIED_RESEARCH_SCHEMA,
            tools=tools,
        )

        actual_urls = [url for url in _actual_response_urls(response) if self._is_current_official_source(url)]
        actual_by_canonical = {_canonical_url(url): url for url in actual_urls if _canonical_url(url)}
        verified: list[str] = []
        rejected: list[str] = []
        used_urls: list[str] = []
        for point in payload.get("verified_points", []):
            statement = str(point.get("statement", "")).strip()
            article = str(point.get("article", "")).strip()
            provision_text = str(point.get("provision_text", "")).strip()
            claimed_url = str(point.get("source_url", "")).strip()
            actual_url = actual_by_canonical.get(_canonical_url(claimed_url))
            if not statement or not article or not provision_text or not actual_url:
                if statement:
                    rejected.append(f"{statement} — не принят как VERIFIED: нет source-bound официального источника.")
                continue
            drift = paraphrase_defects(statement, provision_text)
            if drift:
                rejected.append(f"{statement} — не принят как VERIFIED: {'; '.join(drift[:3])}")
                continue
            verified.append(verified_claim_line(statement, article, provision_text, actual_url))
            if actual_url not in used_urls:
                used_urls.append(actual_url)

        unverified = [str(x) for x in payload.get("unverified_claims", [])] + rejected
        research = LegalResearch(
            status=VerificationStatus.VERIFIED if verified and used_urls and not unverified else VerificationStatus.NEEDS_VERIFICATION,
            applicable_law=[str(x) for x in payload.get("applicable_law", [])],
            procedural_requirements=[str(x) for x in payload.get("procedural_requirements", [])],
            verified_claims=verified,
            unverified_claims=unverified,
            source_urls=used_urls,
            notes=[str(x) for x in payload.get("notes", [])],
        )
        if requires_material_law(case_context) and not material_verified_claims(research):
            research.status = VerificationStatus.NEEDS_VERIFICATION
            research.unverified_claims.append(
                "Не подтверждена материально-правовая основа основного требования досудебной претензии; процессуальные нормы её не заменяют."
            )
        return research

    async def draft_pretrial(self, case_context: str, research: LegalResearch, language: str = "ru") -> PretrialDraft:
        verified = "\n".join(f"- {x}" for x in research.verified_claims) or "- нет подтвержденных норм"
        prompt = (
            "Подготовь профессиональную ДОСУДЕБНУЮ ПРЕТЕНЗИЮ по праву Республики Казахстан. Используй только факты материалов и VERIFIED-нормы.\n\n"
            "ОБЯЗАТЕЛЬНО:\n"
            "1. Правовое обоснование основного долга/оплаты/возврата начинается с материального права: ГК РК и/или применимого специального нормативного акта.\n"
            "2. Нормы ГПК о судебных расходах, помощи представителя, госпошлине и иных процессуальных вопросах НЕ ставь вместо материального основания задолженности.\n"
            "3. Если ГПК действительно нужен для отдельного вопроса судебных расходов, поставь его ПОСЛЕ материально-правового обоснования и не называй основанием основной задолженности.\n"
            "4. Каждое требование должно следовать из фактов и иметь VERIFIED правовую опору. Никаких статей по памяти.\n"
            "5. Не придумывай стороны, реквизиты, договор, суммы, даты, доказательства или срок исполнения.\n"
            "6. Срок добровольного исполнения указывай только если он дан пользователем либо подтвержден VERIFIED нормой/условием; иначе формулируй без выдуманного количества дней.\n"
            "7. В последствиях можно нейтрально указать последующее обращение в суд/орган без гарантии результата.\n"
            f"8. Язык документа: {'казахский' if language == 'kk' else 'русский'}.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты практикующий юрист KORGAN в Казахстане. Досудебная претензия должна объяснять, почему основная обязанность существует по материальному праву. "
                "ГПК не заменяет ГК или специальный материальный акт. Не добавляй непроверенное право."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_pretrial_demand",
            schema=_PRETRIAL_SCHEMA,
        )
        draft = PretrialDraft(status=research.status, source_urls=list(research.source_urls), **payload)
        draft.legal_basis = prioritize_material_basis(draft.legal_basis, research)
        return draft


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Almaty")).strftime("%d.%m.%Y")


def build_pretrial_docx(draft: PretrialDraft, language: str = "ru") -> bytes:
    kk = language == "kk"
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(1.5)
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    head.add_run("Жіберуші:\n" if kk else "От:\n").bold = True
    for value in draft.sender or (["[Жіберуші деректері]"] if kk else ["[Данные отправителя]"]):
        head.add_run(str(value) + "\n")
    head.add_run("Алушы:\n" if kk else "Кому:\n").bold = True
    for value in draft.recipient or (["[Алушы деректері]"] if kk else ["[Данные адресата]"]):
        head.add_run(str(value) + "\n")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run(draft.title or ("СОТҚА ДЕЙІНГІ ТАЛАП" if kk else "ДОСУДЕБНАЯ ПРЕТЕНЗИЯ"))
    title_run.bold = True
    title_run.font.size = Pt(14)

    for fact in draft.facts:
        doc.add_paragraph(fact)

    if draft.legal_basis:
        heading = doc.add_paragraph()
        heading.add_run("Құқықтық негіздеме" if kk else "Правовое обоснование").bold = True
        for basis in draft.legal_basis:
            doc.add_paragraph(basis)

    demand_heading = doc.add_paragraph()
    demand_heading.add_run("ТАЛАП ЕТЕМІН:" if kk else "ТРЕБУЮ:").bold = True
    for index, demand in enumerate(draft.demands, 1):
        doc.add_paragraph(f"{index}. {demand}")

    if draft.deadline:
        doc.add_paragraph(("Орындау мерзімі: " if kk else "Срок исполнения: ") + draft.deadline)
    if draft.consequences:
        heading = doc.add_paragraph()
        heading.add_run("Орындалмаған жағдайда" if kk else "В случае неисполнения").bold = True
        for line in draft.consequences:
            doc.add_paragraph(line)
    if draft.attachments:
        heading = doc.add_paragraph()
        heading.add_run("Қосымшалар:" if kk else "Приложения:").bold = True
        for index, item in enumerate(draft.attachments, 1):
            doc.add_paragraph(f"{index}. {item}")

    doc.add_paragraph()
    doc.add_paragraph(("Күні: " if kk else "Дата: ") + _today())
    doc.add_paragraph("Қолы: ____________________" if kk else "Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
