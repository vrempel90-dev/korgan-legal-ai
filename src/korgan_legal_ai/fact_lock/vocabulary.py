from __future__ import annotations

import re

from korgan_legal_ai.domain.models import (
    EvidenceKind,
    FilingMode,
    PartyRole,
    RepresentativeKind,
)

# The extractor reads Russian case descriptions, so it returns Russian words. Accepting only the
# internal English enum codes made the dialogue unanswerable: the bot asked "уточните роль стороны"
# and then rejected the word "истец" — the very term its own question used. These tables map what a
# person actually writes onto the codes the pipeline stores.
#
# Direct procedural terms are authoritative. Contract-role words are a fallback below, because a
# contract role does not by itself say who is suing whom.
_PARTY_DIRECT: dict[str, PartyRole] = {
    "истец": PartyRole.CLAIMANT,
    "истцом": PartyRole.CLAIMANT,
    "заявитель": PartyRole.CLAIMANT,
    "взыскатель": PartyRole.CLAIMANT,
    "ответчик": PartyRole.DEFENDANT,
    "ответчиком": PartyRole.DEFENDANT,
    "заинтересованное лицо": PartyRole.DEFENDANT,
    "кредитор": PartyRole.CREDITOR,
    "должник": PartyRole.DEBTOR,
    "работодатель": PartyRole.EMPLOYER,
    "работник": PartyRole.EMPLOYEE,
    "сотрудник": PartyRole.EMPLOYEE,
    "третье лицо": PartyRole.OTHER,
    "иное лицо": PartyRole.OTHER,
}

# Contract-role pairs, mapped along the direction money flows in a payment claim: the side that
# performed and was not paid is the creditor, the side that owes payment is the debtor. Used only
# when the answer carries no direct procedural term, and never overrides one.
_PARTY_CONTRACT: dict[str, PartyRole] = {
    "исполнитель": PartyRole.CREDITOR,
    "подрядчик": PartyRole.CREDITOR,
    "поставщик": PartyRole.CREDITOR,
    "продавец": PartyRole.CREDITOR,
    "арендодатель": PartyRole.CREDITOR,
    "наймодатель": PartyRole.CREDITOR,
    "лизингодатель": PartyRole.CREDITOR,
    "займодавец": PartyRole.CREDITOR,
    "заимодавец": PartyRole.CREDITOR,
    "перевозчик": PartyRole.CREDITOR,
    "заказчик": PartyRole.DEBTOR,
    "покупатель": PartyRole.DEBTOR,
    "арендатор": PartyRole.DEBTOR,
    "наниматель": PartyRole.DEBTOR,
    "лизингополучатель": PartyRole.DEBTOR,
    "заемщик": PartyRole.DEBTOR,
    "заёмщик": PartyRole.DEBTOR,
    "плательщик": PartyRole.DEBTOR,
    "грузополучатель": PartyRole.DEBTOR,
}

_REPRESENTATIVE: dict[str, RepresentativeKind] = {
    "директор": RepresentativeKind.DIRECTOR,
    "генеральный директор": RepresentativeKind.DIRECTOR,
    "руководитель": RepresentativeKind.DIRECTOR,
    "первый руководитель": RepresentativeKind.DIRECTOR,
    "председатель правления": RepresentativeKind.DIRECTOR,
    "по уставу": RepresentativeKind.DIRECTOR,
    "на основании устава": RepresentativeKind.DIRECTOR,
    "устав": RepresentativeKind.DIRECTOR,
    "адвокат": RepresentativeKind.ADVOCATE,
    "юридический консультант": RepresentativeKind.LEGAL_CONSULTANT,
    "юрконсультант": RepresentativeKind.LEGAL_CONSULTANT,
    "юрист-консультант": RepresentativeKind.LEGAL_CONSULTANT,
    "штатный работник": RepresentativeKind.EMPLOYEE,
    "штатный юрист": RepresentativeKind.EMPLOYEE,
    "работник": RepresentativeKind.EMPLOYEE,
    "сотрудник": RepresentativeKind.EMPLOYEE,
    "представитель": RepresentativeKind.OTHER,
    "по доверенности": RepresentativeKind.OTHER,
    "иное лицо": RepresentativeKind.OTHER,
}

_FILING: dict[str, FilingMode] = {
    "электронно": FilingMode.ELECTRONIC,
    "электронный": FilingMode.ELECTRONIC,
    "электронная": FilingMode.ELECTRONIC,
    "судебный кабинет": FilingMode.ELECTRONIC,
    "онлайн": FilingMode.ELECTRONIC,
    "эцп": FilingMode.ELECTRONIC,
    "на бумаге": FilingMode.PAPER,
    "бумажно": FilingMode.PAPER,
    "бумажный": FilingMode.PAPER,
    "нарочно": FilingMode.PAPER,
    "почтой": FilingMode.PAPER,
    "канцелярия": FilingMode.PAPER,
}

_EVIDENCE: dict[str, EvidenceKind] = {
    "договор": EvidenceKind.CONTRACT,
    "контракт": EvidenceKind.CONTRACT,
    "соглашение": EvidenceKind.CONTRACT,
    "акт": EvidenceKind.PRIMARY_DOCUMENT,
    "накладная": EvidenceKind.PRIMARY_DOCUMENT,
    "счет-фактура": EvidenceKind.PRIMARY_DOCUMENT,
    "счёт-фактура": EvidenceKind.PRIMARY_DOCUMENT,
    "первичный документ": EvidenceKind.PRIMARY_DOCUMENT,
    "платежное поручение": EvidenceKind.PAYMENT,
    "платёжное поручение": EvidenceKind.PAYMENT,
    "выписка": EvidenceKind.PAYMENT,
    "оплата": EvidenceKind.PAYMENT,
    "претензия": EvidenceKind.PRETRIAL_DEMAND,
    "требование": EvidenceKind.PRETRIAL_DEMAND,
    "доказательство направления": EvidenceKind.PRETRIAL_DELIVERY,
    "квитанция об отправке": EvidenceKind.PRETRIAL_DELIVERY,
    "почтовая квитанция": EvidenceKind.PRETRIAL_DELIVERY,
    "доверенность": EvidenceKind.AUTHORITY,
    "приказ о назначении": EvidenceKind.AUTHORITY,
    "удостоверение адвоката": EvidenceKind.PROFESSIONAL_STATUS,
    "справка о регистрации": EvidenceKind.REGISTRATION,
    "госпошлина": EvidenceKind.STATE_DUTY_PAYMENT,
    "квитанция госпошлины": EvidenceKind.STATE_DUTY_PAYMENT,
    "акт сверки": EvidenceKind.RECONCILIATION,
}

# What the user is told when nothing matched. Naming the accepted words is the difference between a
# question a person can answer and one they cannot.
_EXPECTED: dict[type, str] = {
    PartyRole: "укажите одним словом: истец или ответчик (принимаются также кредитор, должник, "
    "заказчик, исполнитель, продавец, покупатель, арендодатель, арендатор, займодавец, заёмщик)",
    RepresentativeKind: "укажите одним словом: директор, адвокат, юридический консультант, "
    "штатный работник или представитель по доверенности",
    FilingMode: "укажите одним словом: электронно или на бумаге",
    EvidenceKind: "укажите вид документа: договор, акт, накладная, платёжный документ, претензия, "
    "доказательство направления, доверенность, справка о регистрации, квитанция госпошлины",
}

_TABLES: dict[type, tuple[dict[str, object], ...]] = {
    PartyRole: (_PARTY_DIRECT, _PARTY_CONTRACT),
    RepresentativeKind: (_REPRESENTATIVE,),
    FilingMode: (_FILING,),
    EvidenceKind: (_EVIDENCE,),
}

_WORD_SPLIT = re.compile(r"[^\wёЁ-]+", re.UNICODE)


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().replace("ё", "ё").split())


def expected_values(enum_type) -> str:
    """Human-readable list of what this field accepts."""
    hint = _EXPECTED.get(enum_type)
    if hint:
        return hint
    return "допустимые значения: " + ", ".join(item.value for item in enum_type)


def normalize_enum(enum_type, value: str | None):
    """Map a written answer onto an enum member, or return None if nothing matched.

    Matching runs from most to least specific: the internal code, then an exact term, then a term
    appearing as a phrase inside a longer sentence. A longer term wins over a shorter one so that
    "юридический консультант" is not read as "консультант"-less "юрист", and "заинтересованное
    лицо" is not shadowed by "лицо".
    """
    if value is None or not str(value).strip():
        return None

    text = _normalize_text(str(value))

    # The internal code, in case the extractor already produced one.
    try:
        return enum_type(text)
    except ValueError:
        pass

    tables = _TABLES.get(enum_type)
    if tables is None:
        return None

    for table in tables:
        # Exact match on the whole answer.
        if text in table:
            return table[text]

    words = {word for word in _WORD_SPLIT.split(text) if word}
    for table in tables:
        # Phrases first: a multi-word term is more specific than any single word inside it.
        phrases = sorted(
            (term for term in table if " " in term), key=len, reverse=True
        )
        for term in phrases:
            if term in text:
                return table[term]
        singles = sorted(
            (term for term in table if " " not in term), key=len, reverse=True
        )
        for term in singles:
            if term in words:
                return table[term]
    return None
