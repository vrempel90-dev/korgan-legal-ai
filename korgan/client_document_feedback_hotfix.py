"""Pure client-document quality helpers used by the production-safe installers."""

from __future__ import annotations

import io
import re
from typing import Any

_PROCEDURAL_MARKERS = ("гпк", "аппк", "упк")
_PRIVATE_DISPUTE_RE = re.compile(
    r"(?i)(договор|обязательств|задолж|оплат|аванс|неустой|пен[яию]\b|подряд|работ|услуг|постав|товар|возврат|убыт|взыск|шарт|міндеттем|берешек|төлем|жұмыс|қызмет|тауар)"
)
_PENALTY_TERM_RE = re.compile(r"(?i)(неустой\w*|пен[яию]\b|штраф\w*|тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)")
_PENALTY_NEGATION_RE = re.compile(
    r"(?i)(?:не\s+(?:подлежит\s+взыскан\w*|начислен\w*|требу\w*|прос\w*|заявля\w*)|"
    r"(?:не\s+требу\w*|не\s+прос\w*|не\s+заявля\w*)[^.!?\n]{0,90}(?:неустой\w*|пен[яию]\b|штраф\w*)|"
    r"(?:неустой\w*|пен[яию]\b|штраф\w*)[^.!?\n]{0,90}(?:не\s+требу\w*|не\s+прос\w*|не\s+заявля\w*))"
)
_PENALTY_POSITIVE_RE = re.compile(
    r"(?i)(?:"
    r"(?:неустой\w*|пен[яию]\b|штраф\w*)[^.!?\n]{0,100}(?:подлежит\s+взыскан\w*|начислен\w*|обязан\w*\s+уплат\w*)|"
    r"(?:требу\w*|прос\w*|заявля\w*)[^.!?\n]{0,70}взыск\w*[^.!?\n]{0,70}(?:неустой\w*|пен[яию]\b|штраф\w*)|"
    r"взыск\w*[^.!?\n]{0,70}(?:неустой\w*|пен[яию]\b|штраф\w*)|"
    r"(?:тұрақсыздық\s+айыб\w*|өсімпұл\w*|айыппұл\w*)[^.!?\n]{0,100}(?:өндір\w*|есептел\w*)"
    r")"
)
_MONEY_RE = re.compile(r"(?i)\b\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:₸|тг\b|тенге\b)")
_RATE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_BASIS_RE = re.compile(r"(?i)\[основание:\s*([^;\]]+)")
_GENERIC_LEGAL_BASIS_RE = re.compile(
    r"(?i)(?:стать[ьяи]\s*\d+(?:-\d+)?|ст\.\s*\d+(?:-\d+)?)\s+([^.;\n]{2,140})"
)

_REMEDY_PATTERNS: dict[str, re.Pattern[str]] = {
    "penalty": re.compile(r"(?i)(неустой|пен[яию]\b|штраф|тұрақсыздық\s+айыб|өсімпұл|айыппұл)"),
    "damages": re.compile(r"(?i)(убыт|ущерб|залал|зиян)"),
    "interest": re.compile(r"(?i)(процент|сыйақ|пайыз)"),
    "moral": re.compile(r"(?i)(моральн\w*\s+вред|моральдық\s+зиян)"),
    "termination": re.compile(r"(?i)(расторг|прекрат|признать\s+недейств|бұз|тоқтат|жарамсыз)"),
    "principal": re.compile(r"(?i)(взыск|вернут|возврат|долг|задолж|оплат|аванс|өндір|қайтар|берешек|төлем)"),
}
_SPECIALIZED_REMEDIES = frozenset({"penalty", "damages", "interest", "moral", "termination"})

_RESEARCH_SUFFIX = (
    "\n\nМАТЕРИАЛЬНО-ПРАВОВОЕ ПОКРЫТИЕ ДОКУМЕНТА:\n"
    "25. В частноправовом споре нельзя ограничиваться ГПК/процессуальными нормами: source-bound проверь материально-правовую основу самого требования.\n"
    "26. Для КАЖДОГО самостоятельного способа защиты или денежного требования (долг/возврат, неустойка/пеня, убытки, проценты, компенсация и т.п.) найди отдельную действующую VERIFIED-норму, прямо поддерживающую именно этот способ защиты. Процессуальная норма не заменяет материальную.\n"
    "27. Если факты указывают на специальный закон, правила, постановление или иной нормативный акт, используй его только после source-bound VERIFIED-подтверждения применимости. Не добавляй специальные акты по памяти.\n"
    "28. Разделяй материальные и процессуальные основания. Если материальная норма для самостоятельного требования не подтверждена, не выдумывай статью и не представляй такое требование как filing-ready."
)

_CHECKLIST_RU = {
    "claim": "📋 Для максимально готового ИСКА укажите: стороны и реквизиты; договор/событие и даты; нарушение; суммы и расчёт каждого требования (включая неустойку/пеню, если требуете); что именно просите суд; доказательства и приложения; суд/номер дела — если известны.",
    "pretrial": "📋 Для максимально готовой ПРЕТЕНЗИИ укажите: отправителя и адресата; договор/правоотношение; нарушение и даты; основной долг/возврат; расчёт неустойки/пени, если заявляется; конкретное требование и срок; доказательства и переписку.",
    "pretrial_response": "📋 Для максимально готового ОТВЕТА НА ПРЕТЕНЗИЮ пришлите: саму претензию, дату/номер и все требования; стороны; вашу позицию по каждому требованию; спорные факты; договор, акты, платежи, переписку и иные доказательства; желаемый итог — только если это ваша позиция.",
    "contract": "📋 Для максимально готового ДОГОВОРА укажите: вид/цель; стороны и реквизиты; предмет; цену и оплату; сроки; ответственность/неустойку и приёмку — если нужны; расторжение, особые условия и приложения.",
    "response": "📋 Для максимально готового ОТЗЫВА НА ИСК пришлите: иск, суд и номер дела; стороны; все требования и суммы; вашу позицию по каждому требованию; возражения и расчёты; договоры, акты, платежи, переписку и иные доказательства.",
}
_CHECKLIST_KK = {
    "claim": "📋 Талап қою арызын барынша толық дайындау үшін: тараптар мен деректемелерді; шарт/оқиға мен күндерді; бұзушылықты; әр талаптың сомасы мен есебін (өсімпұл/тұрақсыздық айыбы талап етілсе); соттан нақты не сұрайтыныңызды; дәлелдер мен қосымшаларды көрсетіңіз.",
    "pretrial": "📋 Сотқа дейінгі талап үшін: жіберуші/алушы; шарт; бұзушылық пен күндер; негізгі сома; талап етілсе өсімпұл есебі; нақты талап пен мерзім; дәлелдер мен хат алмасуды көрсетіңіз.",
    "pretrial_response": "📋 Сотқа дейінгі ТАЛАПҚА ЖАУАП үшін: талаптың өзін, күні/нөмірін және барлық талаптарын; тараптарды; әр талап бойынша ұстанымды; даулы фактілерді; шарт, акт, төлем, хат алмасу және өзге дәлелдерді жіберіңіз.",
    "contract": "📋 Шарт үшін: түрі/мақсаты; тараптар мен деректемелер; пәні; баға/төлем; мерзімдер; қажет болса жауапкершілік/тұрақсыздық айыбы; бұзу тәртібі, ерекше талаптар және қосымшаларды көрсетіңіз.",
    "response": "📋 Талап қою арызына ПІКІР үшін: талап арызын, сот пен іс нөмірін; тараптарды; барлық талаптар мен сомаларды; әр талап бойынша ұстанымды; қарсылықтар/есептерді; шарт, акт, төлем және өзге дәлелдерді жіберіңіз.",
}


def checklist_text(kind: str, language: str = "ru") -> str:
    """Return localized completion guidance; unknown data stays optional."""
    mapping = _CHECKLIST_KK if language == "kk" else _CHECKLIST_RU
    text = mapping[kind]
    tail = (
        "\n\nФайлдарды алдымен тіркеп, кейін жетіспейтін мәліметтерді бір хабарламада жібере аласыз. Белгісіз деректерді KORGAN ойдан шығармайды."
        if language == "kk"
        else "\n\nМожно сначала приложить все файлы, затем одним сообщением добавить недостающие сведения. Неизвестные данные KORGAN не будет придумывать."
    )
    return text + tail


def progress_text(kind: str, language: str = "ru") -> str:
    """Return a visible status message for an actually authorized generation."""
    if language == "kk":
        return "⏳ Құжат өңделуде. KORGAN қолданылатын құқықты, талаптарды және дәлелдерді тексеріп, Word-файлды қалыптастырып жатыр. Күрделі іс бірнеше минут алуы мүмкін."
    return "⏳ Документ в работе. KORGAN проверяет применимое право, требования и доказательства и формирует Word-файл. По сложному делу это может занять несколько минут."


async def send_checklist_once(message: Any, state: Any, kind: str) -> bool:
    """Send only the active request's checklist, once per immutable request."""
    data = await state.get_data()
    request_id = str(data.get("request_id") or "")
    if not request_id or str(data.get("request_kind") or "") != kind:
        return False
    if (
        str(data.get("client_checklist_request_id") or "") == request_id
        and str(data.get("client_checklist_kind") or "") == kind
    ):
        return False
    language = "kk" if str(data.get("language") or "ru") == "kk" else "ru"
    await message.answer(checklist_text(kind, language))
    latest = await state.get_data()
    if str(latest.get("request_id") or "") != request_id or str(latest.get("request_kind") or "") != kind:
        return False
    await state.update_data(client_checklist_request_id=request_id, client_checklist_kind=kind)
    return True


def affirmative_penalty_statement(text: str) -> bool:
    """Recognize a genuinely claimed/accrued penalty while excluding negation/rate clauses."""
    for sentence in re.split(r"(?<=[.!?\n])\s*", text or ""):
        if not _PENALTY_TERM_RE.search(sentence):
            continue
        if _PENALTY_NEGATION_RE.search(sentence):
            continue
        if _PENALTY_POSITIVE_RE.search(sentence):
            return True
        if re.search(r"(?i)(неустой\w*|пен[яию]\b|штраф\w*)[^.!?\n]{0,50}составля\w*", sentence):
            if _MONEY_RE.search(sentence) and not (_RATE_RE.search(sentence) and not _MONEY_RE.search(sentence)):
                return True
    return False


def _basis_label(line: str) -> str:
    match = _BASIS_RE.search(str(line))
    if match:
        return match.group(1).strip()
    generic = _GENERIC_LEGAL_BASIS_RE.search(str(line))
    return generic.group(0).strip() if generic else ""


def _is_procedural_basis(label: str) -> bool:
    value = " ".join(label.lower().split())
    return bool(value and any(marker in value for marker in _PROCEDURAL_MARKERS))


def _material_basis_labels(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines or []:
        label = _basis_label(str(line))
        if label and not _is_procedural_basis(label) and label not in result:
            result.append(label)
    return result


def _remedy_categories(lines: list[str]) -> set[str]:
    text = "\n".join(str(line) for line in lines or [])
    result = {name for name, pattern in _REMEDY_PATTERNS.items() if pattern.search(text)}
    # Specialized remedies should not also be treated as a generic principal merely
    # because the phrase contains «взыскать/өндіріп алу».
    if result & _SPECIALIZED_REMEDIES:
        specific_texts = [line for line in lines or [] if any(p.search(str(line)) for n, p in _REMEDY_PATTERNS.items() if n in _SPECIALIZED_REMEDIES)]
        remaining = [line for line in lines or [] if line not in specific_texts]
        if not any(_REMEDY_PATTERNS["principal"].search(str(line)) for line in remaining):
            result.discard("principal")
    return result


def _verified_support_by_category(verified_claims: list[str]) -> dict[str, list[str]]:
    support: dict[str, list[str]] = {name: [] for name in _REMEDY_PATTERNS}
    generic_material: list[str] = []
    for line in verified_claims or []:
        label = _basis_label(str(line))
        if not label or _is_procedural_basis(label):
            continue
        generic_material.append(label)
        statement = str(line).split("[основание:", 1)[0]
        matched = {name for name, pattern in _REMEDY_PATTERNS.items() if pattern.search(statement)}
        for name in matched:
            if label not in support[name]:
                support[name].append(label)
    # A generic verified obligation/debt provision may support the principal claim;
    # specialized remedies must always have category-specific VERIFIED support.
    if generic_material and not support["principal"]:
        support["principal"] = list(dict.fromkeys(generic_material))
    return support


def _basis_present_in_draft(label: str, legal_basis: list[str]) -> bool:
    target = re.sub(r"\W+", "", label.lower())
    if not target:
        return False
    joined = "\n".join(str(x) for x in legal_basis or []).lower()
    normalized = re.sub(r"\W+", "", joined)
    if target in normalized:
        return True
    # Compare article number + distinctive act/statute words so a verified special
    # statute remains recognizable even when the drafting sentence is paraphrased.
    article = re.search(r"\d+(?:-\d+)?", label)
    words = [w for w in re.findall(r"[а-яёәіңғүұқөһa-z]{4,}", label.lower()) if w not in {"статья", "статьи"}]
    return bool(article and article.group(0) in joined and any(word in joined for word in words))


def material_law_issue(
    legal_basis: list[str],
    verified_claims: list[str],
    *,
    context: str = "",
    require_for_private_dispute: bool = False,
) -> str | None:
    """Detect GPK-only/private-law drafts while recognizing VERIFIED special statutes."""
    material_draft = _material_basis_labels(legal_basis)
    material_verified = _material_basis_labels(verified_claims)
    if material_verified and not material_draft:
        return "Подтвержденные материально-правовые нормы не перенесены в документ: процессуальная норма не заменяет основание самого требования."
    if require_for_private_dispute and _PRIVATE_DISPUTE_RE.search(context or "") and not material_draft and not material_verified:
        return "Для частноправового/договорного требования source-bound исследование не подтвердило материально-правовую норму; документ нельзя считать полностью готовым только на основании ГПК."
    return None


def remedy_support_issues(demands: list[str], legal_basis: list[str], verified_claims: list[str]) -> list[str]:
    """Require VERIFIED material support separately for every independent remedy."""
    requested = _remedy_categories(demands)
    support = _verified_support_by_category(verified_claims)
    labels_in_draft = _material_basis_labels(legal_basis)
    issues: list[str] = []
    names = {
        "principal": "основного требования/долга/возврата",
        "penalty": "неустойки/пени/штрафа",
        "damages": "убытков/ущерба",
        "interest": "процентов",
        "moral": "компенсации морального вреда",
        "termination": "расторжения/прекращения/недействительности",
    }
    for category in sorted(requested):
        verified_labels = support.get(category, [])
        if not verified_labels:
            issues.append(f"Для самостоятельного требования {names[category]} нет отдельной source-bound VERIFIED материально-правовой нормы.")
            continue
        if not any(_basis_present_in_draft(label, legal_basis) for label in verified_labels):
            issues.append(f"VERIFIED материально-правовая норма для {names[category]} найдена, но не перенесена в правовое обоснование документа.")
    return issues


def install_research_prompt_patch() -> None:
    """Append per-remedy source-bound rules to the actual fast production prompt."""
    from korgan import fast_professional_litigation as litigation

    current = litigation._professional_research_prompt
    if getattr(current, "_korgan_client_material_law", False):
        return

    def material_prompt(case_context: str, *, max_chars: int, checked_on: str, **kwargs: object) -> str:
        return current(case_context, max_chars=max_chars, checked_on=checked_on, **kwargs) + _RESEARCH_SUFFIX

    material_prompt._korgan_client_material_law = True  # type: ignore[attr-defined]
    litigation._professional_research_prompt = material_prompt


def install_quality_patches() -> None:
    """Add deterministic material/per-remedy checks without weakening existing QA."""
    from korgan import pretrial, pretrial_response, senior_claim_preflight

    current_claim = senior_claim_preflight.deterministic_claim_preflight
    if not getattr(current_claim, "_korgan_client_remedy_support", False):
        def claim_preflight(case_context: str, research: Any, draft: Any) -> list[str]:
            errors = list(current_claim(case_context, research, draft))
            body = "\n".join([*[str(x) for x in draft.facts], *[str(x) for x in draft.legal_basis], str(draft.late_interest or "")])
            prayer = "\n".join(str(x) for x in draft.requests)
            if affirmative_penalty_statement(body) and not _PENALTY_TERM_RE.search(prayer):
                errors.append("Текст иска утверждает, что неустойка/пеня начислена, заявлена или подлежит взысканию, но отдельного требования о ней в разделе «ПРОШУ СУД» нет. Устраните противоречие без добавления неподтвержденного требования.")
            errors.extend(remedy_support_issues(list(draft.requests), list(draft.legal_basis), list(research.verified_claims)))
            issue = material_law_issue(list(draft.legal_basis), list(research.verified_claims), context=case_context, require_for_private_dispute=True)
            if issue:
                errors.append(issue)
            return list(dict.fromkeys(errors))

        claim_preflight._korgan_client_remedy_support = True  # type: ignore[attr-defined]
        senior_claim_preflight.deterministic_claim_preflight = claim_preflight

    current_pretrial = pretrial.pretrial_quality_issues
    if not getattr(current_pretrial, "_korgan_client_remedy_support", False):
        def pretrial_issues(draft: Any, research: Any) -> list[str]:
            issues = list(current_pretrial(draft, research))
            issues.extend(remedy_support_issues(list(draft.demands), list(draft.legal_basis), list(research.verified_claims)))
            issue = material_law_issue(list(draft.legal_basis), list(research.verified_claims), context="\n".join(draft.body_lines()), require_for_private_dispute=True)
            if issue:
                issues.append(issue)
            return list(dict.fromkeys(issues))

        pretrial_issues._korgan_client_remedy_support = True  # type: ignore[attr-defined]
        pretrial.pretrial_quality_issues = pretrial_issues

    current_response = pretrial_response.pretrial_response_quality_issues
    if not getattr(current_response, "_korgan_client_material_law", False):
        def response_issues(draft: Any, research: Any) -> list[str]:
            issues = list(current_response(draft, research))
            issue = material_law_issue(list(draft.legal_basis), list(research.verified_claims), context="\n".join(draft.body_lines()), require_for_private_dispute=True)
            if issue:
                issues.append(issue)
            return list(dict.fromkeys(issues))

        response_issues._korgan_client_material_law = True  # type: ignore[attr-defined]
        pretrial_response.pretrial_response_quality_issues = response_issues


def _reference_line(reference: str, kk: bool) -> str:
    from korgan import pretrial_response
    return pretrial_response._reference_line(reference, kk)


def build_pretrial_response_with_required_title(draft: Any, language: str = "ru") -> bytes:
    """Render the existing business-letter layout with an unconditional heading."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    from korgan import pretrial_response as source

    kk = language == "kk"
    doc = Document()
    section = doc.sections[0]
    section.top_margin, section.bottom_margin, section.left_margin, section.right_margin = Cm(2), Cm(2), Cm(2.5), Cm(1.5)
    doc.styles["Normal"].font.name, doc.styles["Normal"].font.size = "Times New Roman", Pt(12)
    head = doc.add_paragraph(); head.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    head.add_run("Алушы:\n" if kk else "Кому:\n").bold = True
    for value in draft.recipient or [("[Алушы деректері]" if kk else "[Данные адресата]")]: head.add_run(str(value) + "\n")
    head.add_run("Жіберуші:\n" if kk else "От:\n").bold = True
    for value in draft.sender or [("[Жіберуші деректері]" if kk else "[Данные отправителя]")]: head.add_run(str(value) + "\n")
    title = doc.add_paragraph(); title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("СОТҚА ДЕЙІНГІ ТАЛАПҚА ЖАУАП" if kk else "ОТВЕТ НА ПРЕТЕНЗИЮ"); run.bold = True; run.font.size = Pt(14)
    reference = _reference_line(draft.reference, kk)
    if reference:
        p = doc.add_paragraph(reference); p.paragraph_format.space_after = Pt(8)
    for collection in (draft.claim_summary, draft.position, draft.objections, draft.legal_basis, draft.response_terms):
        for item in collection: source._body_paragraph(doc, item)
    if draft.attachments:
        p = doc.add_paragraph(); p.add_run("Қосымшалар:" if kk else "Приложения:").bold = True
        for index, item in enumerate(draft.attachments, 1): doc.add_paragraph(f"{index}. {item}")
    doc.add_paragraph(); doc.add_paragraph(("Күні: " if kk else "Дата: ") + source._today()); doc.add_paragraph("Қолы: ____________________" if kk else "Подпись: ____________________")
    stream = io.BytesIO(); doc.save(stream); return stream.getvalue()


def install_response_title_patch() -> None:
    """Install the required response heading without changing delivery/payment."""
    from korgan import pretrial_response
    pretrial_response.build_pretrial_response_docx = build_pretrial_response_with_required_title
