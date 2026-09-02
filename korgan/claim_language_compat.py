from __future__ import annotations

import re
from dataclasses import replace


def install_claim_language_compat() -> None:
    """Teach deterministic claim gates common Russian legal inflections.

    Official provisions naturally use declined forms (for example, «одного
    процента»), while terse search signatures often use the nominative («один
    процент»).  A filing-critical rule must not disappear because of grammar.
    Keep this compatibility layer deterministic and limited to semantic patterns;
    it does not add or infer any legal proposition by itself.
    """
    from korgan import claim_material_law_rescue as rescue
    from korgan import claim_requested_remedies as remedies

    rule = rescue._CONSUMER_STATUTORY_PENALTY
    rescue._CONSUMER_STATUTORY_PENALTY = replace(
        rule,
        required_groups=(
            (r"неустойк",),
            (r"одн\w*\s+процент\w*", r"1\s*(?:%|процент\w*)"),
            (r"кажд\w*\s+день",),
            (r"срок",),
        ),
        preferred=(
            r"начал\w*\s+и\s+окончан",
            r"одн\w*\s+процент\w*",
            r"кажд\w*\s+день",
        ),
    )

    remedies._PENALTY_NORM_RE = re.compile(
        r"(?is)(?:неустойк\w*|тұрақсыздық\s+айыб\w*).{0,300}"
        r"(?:одн\w*\s+процент\w*|1\s*(?:%|процент\w*)|бір\s+пайыз)"
    )
