from __future__ import annotations

from korgan_legal_ai.blueprints.models import (
    AddresseeKind,
    DocumentBlueprint,
    PartyPresentation,
    Section,
    SectionKind,
)
from korgan_legal_ai.domain.models import DocumentType, LegalArea, PartyRole

_CLAIMANT_ROLES = frozenset({PartyRole.CLAIMANT, PartyRole.CREDITOR})
_DEFENDANT_ROLES = frozenset({PartyRole.DEFENDANT, PartyRole.DEBTOR})

_COURT_SIDES = PartyPresentation(
    author_label="Истец",
    opponent_label="Ответчик",
    author_roles=_CLAIMANT_ROLES,
    opponent_roles=_DEFENDANT_ROLES,
)
# A response is authored by the defendant but describes the same two locked parties. Only the
# printing order changes; the role binding stays, so the sides can never be swapped by presentation.
_RESPONSE_SIDES = PartyPresentation(
    author_label="Ответчик",
    opponent_label="Истец",
    author_roles=_DEFENDANT_ROLES,
    opponent_roles=_CLAIMANT_ROLES,
)
_DEBT_SIDES = PartyPresentation(
    author_label="Кредитор",
    opponent_label="Должник",
    author_roles=_CLAIMANT_ROLES,
    opponent_roles=_DEFENDANT_ROLES,
)
_APPLICANT_SIDES = PartyPresentation(
    author_label="Заявитель",
    opponent_label="Заинтересованное лицо",
    author_roles=_CLAIMANT_ROLES,
    opponent_roles=_DEFENDANT_ROLES,
)
_CONTRACT_SIDES = PartyPresentation(
    author_label="Сторона 1",
    opponent_label="Сторона 2",
    author_roles=_CLAIMANT_ROLES,
    opponent_roles=_DEFENDANT_ROLES,
)

_ALL_CLAIM_ISSUES = (
    "jurisdiction",
    "pretrial",
    "limitation",
    "state_duty",
    "authority",
    "attachments",
)

# The KORGAN opening formula quotes ГПК РК статья 8 verbatim. It is resolved through the same
# fail-closed gateway as any other norm: if the canonical corpus cannot supply the effective
# wording, the formula is simply not printed rather than paraphrased from memory.
_OPENING_LOCATORS = (("GPK_RK", "8", "", ""),)

_MONEY_INTERVIEW = (
    "author_name",
    "author_bin",
    "author_address",
    "opponent_name",
    "opponent_bin",
    "opponent_address",
    "basis",
    "circumstances",
    "contract_amount",
    "payments",
    "obligation_due_date",
    "penalty_rate",
    "penalty_cap",
    "other_amount",
)

_COURT_FILING_INTERVIEW = (
    "representative_kind",
    "representative_name",
    "representative_can_sign",
    "filing_mode",
    "copies_prepared",
    "evidence_list",
)


CLAIM_DEBT_RECOVERY = DocumentBlueprint(
    key="claim.debt_recovery",
    file_slug="isk",
    document_type=DocumentType.CLAIM,
    legal_area=LegalArea.DEBT_RECOVERY,
    title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
    subject="о взыскании задолженности",
    addressee=AddresseeKind.COURT,
    parties=_COURT_SIDES,
    monetary=True,
    sections=(
        Section(SectionKind.ADDRESSEE),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TITLE, heading="ИСКОВОЕ ЗАЯВЛЕНИЕ"),
        Section(SectionKind.CLAIM_PRICE),
        Section(SectionKind.OPENING_FORMULA),
        Section(SectionKind.FACTS, heading="ОБСТОЯТЕЛЬСТВА ДЕЛА"),
        Section(SectionKind.PRETRIAL, heading="СВЕДЕНИЯ О ДОСУДЕБНОМ ПОРЯДКЕ"),
        Section(SectionKind.CALCULATION, heading="РАСЧЕТ ТРЕБОВАНИЙ"),
        Section(
            SectionKind.LEGAL_GROUNDS,
            heading="ПРАВОВОЕ ОБОСНОВАНИЕ",
            intro=(
                "Истец основывает требования на зафиксированных договорных обязательствах, факте "
                "их исполнения со своей стороны и наличии непогашенной задолженности. Точные нормы "
                "указываются только при наличии VERIFIED-источника."
            ),
        ),
        Section(SectionKind.CLOSING_FORMULA),
        Section(SectionKind.PRAYER, heading="ПРОШУ СУД:"),
        Section(SectionKind.ATTACHMENTS, heading="ПРИЛОЖЕНИЯ:"),
        Section(SectionKind.SIGNATURE, heading="ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ"),
    ),
    prayer_items=(
        "Взыскать с {opponent} в пользу {author} {claim_subject} в размере {total}.",
        "Взыскать с {opponent} в пользу {author} расходы по уплате государственной пошлины{duty_suffix}.",
    ),
    procedural_issues=_ALL_CLAIM_ISSUES,
    style_norm_locators=_OPENING_LOCATORS,
    interview_fields=_MONEY_INTERVIEW
    + ("pretrial_required", "pretrial_sent_date")
    + _COURT_FILING_INTERVIEW,
    summary="Сформирован проект иска о взыскании задолженности на основе зафиксированных фактов.",
)

CLAIM_GENERIC = DocumentBlueprint(
    key="claim.default",
    file_slug="isk",
    document_type=DocumentType.CLAIM,
    legal_area=None,
    title="ИСКОВОЕ ЗАЯВЛЕНИЕ",
    subject="о защите нарушенного права",
    addressee=AddresseeKind.COURT,
    parties=_COURT_SIDES,
    monetary=True,
    sections=CLAIM_DEBT_RECOVERY.sections,
    prayer_items=CLAIM_DEBT_RECOVERY.prayer_items,
    procedural_issues=_ALL_CLAIM_ISSUES,
    style_norm_locators=_OPENING_LOCATORS,
    interview_fields=CLAIM_DEBT_RECOVERY.interview_fields,
    summary="Сформирован проект искового заявления на основе зафиксированных фактов.",
)

PRETRIAL_DEMAND = DocumentBlueprint(
    key="pretrial_demand.default",
    file_slug="pretenziya",
    document_type=DocumentType.PRETRIAL_DEMAND,
    legal_area=None,
    title="ПРЕТЕНЗИЯ",
    subject="о погашении задолженности в досудебном порядке",
    addressee=AddresseeKind.COUNTERPARTY,
    parties=_DEBT_SIDES,
    monetary=True,
    sections=(
        Section(SectionKind.ADDRESSEE),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TITLE, heading="ПРЕТЕНЗИЯ"),
        Section(SectionKind.FACTS, heading="ОБСТОЯТЕЛЬСТВА"),
        Section(SectionKind.CALCULATION, heading="РАСЧЕТ ТРЕБОВАНИЙ"),
        Section(SectionKind.LEGAL_GROUNDS, heading="ПРАВОВОЕ ОБОСНОВАНИЕ"),
        Section(SectionKind.TERMS, heading="СРОК И ПОРЯДОК ИСПОЛНЕНИЯ"),
        Section(SectionKind.CLOSING_FORMULA),
        Section(SectionKind.PRAYER, heading="ТРЕБУЮ:"),
        Section(SectionKind.ATTACHMENTS, heading="ПРИЛОЖЕНИЯ:"),
        Section(SectionKind.SIGNATURE, heading="ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ"),
    ),
    prayer_items=(
        "Погасить {claim_subject} в размере {total} в пользу {author}.",
    ),
    procedural_issues=("limitation",),
    interview_fields=_MONEY_INTERVIEW
    + ("demand_deadline_days", "representative_kind", "representative_name", "evidence_list"),
    summary="Сформирован проект досудебной претензии на основе зафиксированных фактов.",
)

RESPONSE = DocumentBlueprint(
    key="response.default",
    file_slug="otzyv",
    document_type=DocumentType.RESPONSE,
    legal_area=None,
    title="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ",
    subject="о несогласии с заявленными требованиями",
    addressee=AddresseeKind.COURT,
    parties=_RESPONSE_SIDES,
    monetary=False,
    sections=(
        Section(SectionKind.ADDRESSEE),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TITLE, heading="ОТЗЫВ НА ИСКОВОЕ ЗАЯВЛЕНИЕ"),
        Section(SectionKind.FACTS, heading="ОБСТОЯТЕЛЬСТВА ДЕЛА"),
        Section(SectionKind.POSITION, heading="ПОЗИЦИЯ ОТВЕТЧИКА"),
        Section(SectionKind.LEGAL_GROUNDS, heading="ПРАВОВОЕ ОБОСНОВАНИЕ"),
        Section(SectionKind.CLOSING_FORMULA),
        Section(SectionKind.PRAYER, heading="ПРОШУ СУД:"),
        Section(SectionKind.ATTACHMENTS, heading="ПРИЛОЖЕНИЯ:"),
        Section(SectionKind.SIGNATURE, heading="ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ"),
    ),
    prayer_items=("Отказать в удовлетворении исковых требований {opponent}.",),
    procedural_issues=("authority",),
    interview_fields=(
        "author_name",
        "author_bin",
        "author_address",
        "opponent_name",
        "opponent_address",
        "case_number",
        "basis",
        "circumstances",
        "response_position",
        "representative_kind",
        "representative_name",
        "representative_can_sign",
        "filing_mode",
        "evidence_list",
    ),
    summary="Сформирован проект отзыва на исковое заявление на основе зафиксированных фактов.",
)

MOTION = DocumentBlueprint(
    key="motion.default",
    file_slug="hodataystvo",
    document_type=DocumentType.MOTION,
    legal_area=None,
    title="ХОДАТАЙСТВО",
    subject="по находящемуся в производстве делу",
    addressee=AddresseeKind.COURT,
    parties=_APPLICANT_SIDES,
    monetary=False,
    sections=(
        Section(SectionKind.ADDRESSEE),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TITLE, heading="ХОДАТАЙСТВО"),
        Section(SectionKind.GROUNDS, heading="ОБОСНОВАНИЕ ХОДАТАЙСТВА"),
        Section(SectionKind.LEGAL_GROUNDS, heading="ПРАВОВОЕ ОБОСНОВАНИЕ"),
        Section(SectionKind.CLOSING_FORMULA),
        Section(SectionKind.PRAYER, heading="ПРОШУ СУД:"),
        Section(SectionKind.ATTACHMENTS, heading="ПРИЛОЖЕНИЯ:"),
        Section(SectionKind.SIGNATURE, heading="ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ"),
    ),
    prayer_items=("{motion_request}",),
    procedural_issues=("authority",),
    interview_fields=(
        "author_name",
        "author_address",
        "opponent_name",
        "case_number",
        "motion_request",
        "circumstances",
        "representative_kind",
        "representative_name",
        "representative_can_sign",
        "filing_mode",
        "evidence_list",
    ),
    summary="Сформирован проект ходатайства на основе зафиксированных фактов.",
)

COMPLAINT = DocumentBlueprint(
    key="complaint.default",
    file_slug="zhaloba",
    document_type=DocumentType.COMPLAINT,
    legal_area=None,
    title="ЖАЛОБА",
    subject="на решение (действие) органа или должностного лица",
    addressee=AddresseeKind.COURT,
    parties=_APPLICANT_SIDES,
    monetary=False,
    sections=(
        Section(SectionKind.ADDRESSEE),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TITLE, heading="ЖАЛОБА"),
        Section(SectionKind.GROUNDS, heading="ОБЖАЛУЕМОЕ РЕШЕНИЕ (ДЕЙСТВИЕ)"),
        Section(SectionKind.FACTS, heading="ОБСТОЯТЕЛЬСТВА ДЕЛА"),
        Section(SectionKind.LEGAL_GROUNDS, heading="ПРАВОВОЕ ОБОСНОВАНИЕ"),
        Section(SectionKind.CLOSING_FORMULA),
        Section(SectionKind.PRAYER, heading="ПРОШУ:"),
        Section(SectionKind.ATTACHMENTS, heading="ПРИЛОЖЕНИЯ:"),
        Section(SectionKind.SIGNATURE, heading="ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ"),
    ),
    prayer_items=("Признать обжалуемое решение (действие) незаконным и отменить его.",),
    procedural_issues=("authority", "limitation"),
    interview_fields=(
        "author_name",
        "author_bin",
        "author_address",
        "opponent_name",
        "opponent_address",
        "contested_act",
        "circumstances",
        "obligation_due_date",
        "representative_kind",
        "representative_name",
        "representative_can_sign",
        "filing_mode",
        "evidence_list",
    ),
    summary="Сформирован проект жалобы на основе зафиксированных фактов.",
)

APPEAL = DocumentBlueprint(
    key="appeal.default",
    file_slug="apellyacionnaya_zhaloba",
    document_type=DocumentType.APPEAL,
    legal_area=None,
    title="АПЕЛЛЯЦИОННАЯ ЖАЛОБА",
    subject="на судебный акт суда первой инстанции",
    addressee=AddresseeKind.APPEAL_COURT,
    parties=_COURT_SIDES,
    monetary=False,
    sections=(
        Section(SectionKind.ADDRESSEE),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TITLE, heading="АПЕЛЛЯЦИОННАЯ ЖАЛОБА"),
        Section(SectionKind.GROUNDS, heading="ОБЖАЛУЕМЫЙ СУДЕБНЫЙ АКТ"),
        Section(SectionKind.FACTS, heading="ОБСТОЯТЕЛЬСТВА ДЕЛА"),
        Section(SectionKind.LEGAL_GROUNDS, heading="ПРАВОВОЕ ОБОСНОВАНИЕ"),
        Section(SectionKind.CLOSING_FORMULA),
        Section(SectionKind.PRAYER, heading="ПРОШУ СУД АПЕЛЛЯЦИОННОЙ ИНСТАНЦИИ:"),
        Section(SectionKind.ATTACHMENTS, heading="ПРИЛОЖЕНИЯ:"),
        Section(SectionKind.SIGNATURE, heading="ПОДПИСАНТ / ПРЕДСТАВИТЕЛЬ"),
    ),
    prayer_items=("Отменить обжалуемый судебный акт и принять новое решение по делу.",),
    procedural_issues=("authority", "limitation", "state_duty"),
    interview_fields=(
        "author_name",
        "author_bin",
        "author_address",
        "opponent_name",
        "opponent_address",
        "case_number",
        "contested_act",
        "circumstances",
        "representative_kind",
        "representative_name",
        "representative_can_sign",
        "filing_mode",
        "evidence_list",
    ),
    summary="Сформирован проект апелляционной жалобы на основе зафиксированных фактов.",
)

CONTRACT = DocumentBlueprint(
    key="contract.default",
    file_slug="dogovor",
    document_type=DocumentType.CONTRACT,
    legal_area=None,
    title="ДОГОВОР",
    subject="между сторонами",
    addressee=AddresseeKind.NONE,
    parties=_CONTRACT_SIDES,
    monetary=True,
    sections=(
        Section(SectionKind.TITLE, heading="ДОГОВОР"),
        Section(SectionKind.PARTIES),
        Section(SectionKind.TERMS, heading="1. ПРЕДМЕТ ДОГОВОРА"),
        Section(SectionKind.CALCULATION, heading="2. ЦЕНА ДОГОВОРА И ПОРЯДОК РАСЧЕТОВ"),
        Section(SectionKind.LEGAL_GROUNDS, heading="3. ОТВЕТСТВЕННОСТЬ СТОРОН И ПРИМЕНИМОЕ ПРАВО"),
        Section(SectionKind.SIGNATURE, heading="РЕКВИЗИТЫ И ПОДПИСИ СТОРОН"),
    ),
    procedural_issues=(),
    interview_fields=(
        "author_name",
        "author_bin",
        "author_address",
        "opponent_name",
        "opponent_bin",
        "opponent_address",
        "contract_subject",
        "contract_amount",
        "obligation_due_date",
        "penalty_rate",
        "penalty_cap",
    ),
    summary="Сформирован каркас договора; существенные условия требуют проверки юристом.",
)

CONSULTATION = DocumentBlueprint(
    key="consultation.default",
    file_slug="konsultaciya",
    document_type=DocumentType.CONSULTATION,
    legal_area=None,
    title="ПРАВОВАЯ КОНСУЛЬТАЦИЯ",
    subject="по представленным обстоятельствам",
    addressee=AddresseeKind.NONE,
    parties=_APPLICANT_SIDES,
    monetary=False,
    sections=(
        Section(SectionKind.TITLE, heading="ПРАВОВАЯ КОНСУЛЬТАЦИЯ"),
        Section(SectionKind.PARTIES),
        Section(SectionKind.FACTS, heading="ИСХОДНЫЕ ДАННЫЕ"),
        Section(SectionKind.LEGAL_GROUNDS, heading="ПРАВОВОЙ АНАЛИЗ"),
        Section(SectionKind.GROUNDS, heading="ВЫВОДЫ И ДАЛЬНЕЙШИЕ ШАГИ"),
    ),
    procedural_issues=("limitation",),
    interview_fields=("author_name", "opponent_name", "basis", "circumstances"),
    summary="Подготовлен правовой разбор по зафиксированным обстоятельствам.",
)


BLUEPRINTS: tuple[DocumentBlueprint, ...] = (
    CLAIM_DEBT_RECOVERY,
    CLAIM_GENERIC,
    PRETRIAL_DEMAND,
    RESPONSE,
    MOTION,
    COMPLAINT,
    APPEAL,
    CONTRACT,
    CONSULTATION,
)


def resolve_blueprint(
    document_type: DocumentType,
    legal_area: LegalArea | None = None,
) -> DocumentBlueprint | None:
    """Find the most specific blueprint for a routing decision.

    An exact ``(document_type, legal_area)`` blueprint wins over the document type's default. When
    neither exists the caller receives ``None`` and must refuse the request rather than substituting
    a document type the user did not ask for.
    """
    for blueprint in BLUEPRINTS:
        if blueprint.document_type == document_type and blueprint.legal_area == legal_area:
            return blueprint
    for blueprint in BLUEPRINTS:
        if blueprint.document_type == document_type and blueprint.legal_area is None:
            return blueprint
    return None


def blueprint_by_key(key: str) -> DocumentBlueprint:
    for blueprint in BLUEPRINTS:
        if blueprint.key == key:
            return blueprint
    raise KeyError(f"Unknown blueprint: {key}")


def supported_document_types() -> tuple[DocumentType, ...]:
    seen: list[DocumentType] = []
    for blueprint in BLUEPRINTS:
        if blueprint.document_type not in seen:
            seen.append(blueprint.document_type)
    return tuple(seen)
