"""Professional pre-trial demand generation for RU/KK without field questionnaires."""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

from korgan.document_release import review_lines
from korgan.legal_types import LegalResearch, VerificationStatus
from korgan.stable_legal_release import StableLegalProductionService, clean_language_labels, sanitize_research_sources

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
    "required": ["title", "sender", "recipient", "facts", "legal_basis", "demands", "deadline", "consequences", "attachments", "verification_notes"],
    "additionalProperties": False,
}

_INTENT_RU = re.compile(r"(?i)\b(?:досудебн\w*\s+претензи\w*|претензи\w*)\b")
_INTENT_KK = re.compile(r"(?i)\b(?:сотқа\s+дейінгі\s+талап|талап\s+хат)\b")
_ACTION = re.compile(r"(?i)\b(?:подготов\w*|состав\w*|сформир\w*|сдел\w*|напиш\w*|дайында\w*|жаса\w*|әзірле\w*|құрастыр\w*)\b")
_ADVICE = re.compile(r"(?i)^\s*(?:как|қалай)\b")

_LANG_VERSION_RE = re.compile(r"(?i)английск\w*\s+верси\w*|англ\.?\s+ст\.|русск\w*\s+редакц\w*|english\s+version|russian\s+version")


def is_pretrial_request(text: str | None) -> bool:
    value = " ".join((text or "").split())
    if not value or _ADVICE.search(value):
        return False
    return bool((_INTENT_RU.search(value) or _INTENT_KK.search(value)) and _ACTION.search(value))


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
            self.title,
            *self.sender,
            *self.recipient,
            *self.facts,
            *self.legal_basis,
            *self.demands,
            self.deadline,
            *self.consequences,
            *self.attachments,
        ]


def _dedupe(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        line = clean_language_labels(raw)
        key = re.sub(r"\W+", "", line.lower())
        if line and key not in seen:
            seen.add(key)
            result.append(line)
    return result


def normalize_pretrial(draft: PretrialDraft) -> None:
    draft.legal_basis = _dedupe(draft.legal_basis)
    draft.facts = _dedupe(draft.facts)
    draft.demands = _dedupe(draft.demands)
    draft.consequences = _dedupe(draft.consequences)
    if _LANG_VERSION_RE.search("\n".join(draft.body_lines())):
        draft.status = VerificationStatus.NEEDS_VERIFICATION
        draft.verification_notes.append("В документе обнаружена некорректная ссылка на языковую версию нормы.")


def pretrial_quality_issues(draft: PretrialDraft, research: LegalResearch) -> list[str]:
    issues: list[str] = []
    if not draft.sender:
        issues.append("не указан отправитель претензии")
    if not draft.recipient:
        issues.append("не указан адресат претензии")
    if not draft.facts:
        issues.append("нет фактического основания требований")
    if not draft.demands:
        issues.append("нет сформулированных требований")
    if not draft.legal_basis and research.verified_claims:
        issues.append("VERIFIED нормы не перенесены в правовое обоснование")
    report = review_lines(draft.body_lines(), verified_claims=research.verified_claims)
    issues.extend(report.blocking)
    return list(dict.fromkeys(issues))


class PretrialProductionService(StableLegalProductionService):
    async def research_pretrial(self, case_context: str, language: str = "ru") -> LegalResearch:
        # Reuse the proven professional source-bound pass. It already decomposes
        # remedies and checks mandatory pre-trial procedure; the dedicated draft
        # below simply omits court-only material from the client document.
        research = await self.research_case(case_context, language=language)
        return sanitize_research_sources(research)

    async def draft_pretrial(self, case_context: str, research: LegalResearch, language: str = "ru") -> PretrialDraft:
        verified = "\n".join(f"- {x}" for x in research.verified_claims) or "- нет подтвержденных норм"
        prompt = (
            "Подготовь профессиональную досудебную претензию по праву Республики Казахстан. "
            "Это не иск и не анкета. Используй только факты пользователя и VERIFIED-нормы.\n\n"
            "Правила:\n"
            "1. Не придумывай ФИО/БИН/ИИН, адрес, договор, даты, суммы, доказательства или факт направления прежней претензии.\n"
            "2. Каждое требование должно вытекать из факта и иметь правовое основание, если оно VERIFIED.\n"
            "3. Не пиши 'английская версия', 'русская редакция' и не представляй переводы одного акта как разные нормы.\n"
            "4. Одну статью не пересказывай несколько раз: один точный абзац на одну норму.\n"
            "5. Срок добровольного исполнения указывай только если он дан пользователем или VERIFIED законом/договором; иначе сформулируй нейтрально без выдуманного числа дней.\n"
            "6. В последствиях укажи возможное обращение в суд/уполномоченный орган только как следующий законный шаг, без угроз и без гарантии результата.\n"
            "7. В приложениях перечисляй только реально имеющиеся материалы.\n"
            f"8. Язык документа: {'казахский' if language == 'kk' else 'русский'}.\n\n"
            f"МАТЕРИАЛЫ:\n{case_context[:self.settings.max_case_text_chars]}\n\n"
            f"VERIFIED:\n{verified}"
        )
        payload, _ = await self._structured_response(
            model=self.settings.openai_model,
            instructions=(
                "Ты практикующий юрист KORGAN в Республике Казахстан. Составляй деловую, юридически точную досудебную претензию. "
                "Не добавляй непроверенное право и не задавай пользователю анкету."
            ),
            content=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            schema_name="korgan_pretrial_demand",
            schema=_PRETRIAL_SCHEMA,
        )
        draft = PretrialDraft(
            status=research.status,
            source_urls=list(research.source_urls),
            **payload,
        )
        normalize_pretrial(draft)
        issues = pretrial_quality_issues(draft, research)
        if issues:
            draft.status = VerificationStatus.NEEDS_VERIFICATION
            draft.verification_notes.extend(x for x in issues if x not in draft.verification_notes)
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
    head.add_run(("Жіберуші:\n" if kk else "От:\n")).bold = True
    for value in draft.sender or [("[Жіберуші деректері]" if kk else "[Данные отправителя]")]:
        head.add_run(str(value) + "\n")
    head.add_run(("Алушы:\n" if kk else "Кому:\n")).bold = True
    for value in draft.recipient or [("[Алушы деректері]" if kk else "[Данные адресата]")]:
        head.add_run(str(value) + "\n")

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(draft.title or ("СОТҚА ДЕЙІНГІ ТАЛАП" if kk else "ДОСУДЕБНАЯ ПРЕТЕНЗИЯ"))
    run.bold = True
    run.font.size = Pt(14)

    for fact in draft.facts:
        doc.add_paragraph(fact)

    if draft.legal_basis:
        p = doc.add_paragraph()
        p.add_run("Құқықтық негіздеме" if kk else "Правовое обоснование").bold = True
        for basis in draft.legal_basis:
            doc.add_paragraph(basis)

    p = doc.add_paragraph()
    p.add_run("ТАЛАП ЕТЕМІН:" if kk else "ТРЕБУЮ:").bold = True
    for index, demand in enumerate(draft.demands, 1):
        doc.add_paragraph(f"{index}. {demand}")

    if draft.deadline:
        doc.add_paragraph(("Орындау мерзімі: " if kk else "Срок исполнения: ") + draft.deadline)

    if draft.consequences:
        p = doc.add_paragraph()
        p.add_run("Орындалмаған жағдайда" if kk else "В случае неисполнения").bold = True
        for line in draft.consequences:
            doc.add_paragraph(line)

    if draft.attachments:
        p = doc.add_paragraph()
        p.add_run("Қосымшалар:" if kk else "Приложения:").bold = True
        for index, item in enumerate(draft.attachments, 1):
            doc.add_paragraph(f"{index}. {item}")

    doc.add_paragraph()
    doc.add_paragraph(("Күні: " if kk else "Дата: ") + _today())
    doc.add_paragraph("Қолы: ____________________" if kk else "Подпись: ____________________")

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()
