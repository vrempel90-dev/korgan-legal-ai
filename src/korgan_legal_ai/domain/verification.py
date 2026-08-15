from __future__ import annotations

# The pipeline names verification gaps with internal identifiers so that code can match on them.
# A reader needs legal language instead: "state_duty" tells a lawyer nothing about what they are
# being asked to check.
#
# This vocabulary belongs to the legal domain, not to any delivery channel. Keeping it here means
# the Telegram transport relays a gap without holding legal wording of its own, and any future
# channel describes the same gap the same way.
VERIFICATION_LABELS: dict[str, dict[str, str]] = {
    "ru": {
        "jurisdiction": "подсудность и компетентный суд",
        "pretrial": "досудебный (претензионный) порядок",
        "limitation": "срок исковой давности",
        "state_duty": "размер государственной пошлины",
        "authority": "полномочия подписанта",
        "attachments": "комплект приложений",
        "evidence_gaps": "доказательства по отдельным обстоятельствам",
        "claim_total_mismatch": "расхождение с названной вами общей суммой",
        "principal_conflicts_with_payments": "расхождение суммы долга с историей оплат",
        "other_amount_duplicated_debt": "«иные суммы» дублируют уже учтённый долг",
        "penalty_cap_base": "база договорного потолка неустойки (долг на дату просрочки или остаток)",
    },
    "kk": {
        "jurisdiction": "соттылық және құзыретті сот",
        "pretrial": "сотқа дейінгі (наразылық) тәртіп",
        "limitation": "талап қою мерзімі",
        "state_duty": "мемлекеттік баж мөлшері",
        "authority": "қол қоюшының өкілеттігі",
        "attachments": "қосымшалар топтамасы",
        "evidence_gaps": "жекелеген мән-жайлар бойынша дәлелдемелер",
        "claim_total_mismatch": "сіз атаған жалпы сомамен алшақтық",
        "principal_conflicts_with_payments": "борыш сомасы мен төлем тарихының алшақтығы",
        "other_amount_duplicated_debt": "«өзге сомалар» есепке алынған борышты қайталайды",
        "penalty_cap_base": "тұрақсыздық айыбы шегінің базасы (мерзім өткендегі борыш па, қалдық па)",
    },
}


def verification_label(item: str, language: str = "ru") -> str:
    """Human-readable name for a verification gap.

    An unrecognised identifier is returned unchanged rather than dropped: a gap the reader cannot
    name is still a gap they must be told about.
    """
    labels = VERIFICATION_LABELS.get(language) or VERIFICATION_LABELS["ru"]
    return labels.get(item, item)
