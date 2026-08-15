"""House-style layer: how a verified document is presented, never what it asserts.

The style rules are derived from KORGAN's filed claims, which are held in a private corpus
outside this repository. Only the derived rule identifiers and their observed frequency ship
here — no client text, parties or identifiers.

The separation this package enforces:

- Fact Lock owns the facts;
- Legal RAG owns which norms apply and in which effective wording;
- the deterministic calculation layer owns amounts, state duty and deadlines;
- house style owns only presentation.

A style rule can therefore never promote NEEDS_VERIFICATION to VERIFIED, and the frequency
with which an article appears in the reference corpus is an observation about drafting habit,
not a reason to cite it.
"""

from korgan_legal_ai.house_style.rules import (
    HouseStyleRule,
    HouseStyleRuleSet,
    load_rules,
)
from korgan_legal_ai.house_style.checklist import StyleFinding, review_claim_presentation
from korgan_legal_ai.house_style.provenance import (
    CorpusDocument,
    CorpusProvenance,
    RuleProvenance,
    load_provenance,
)

__all__ = [
    "HouseStyleRule",
    "HouseStyleRuleSet",
    "load_rules",
    "StyleFinding",
    "review_claim_presentation",
    "CorpusDocument",
    "CorpusProvenance",
    "RuleProvenance",
    "load_provenance",
]
