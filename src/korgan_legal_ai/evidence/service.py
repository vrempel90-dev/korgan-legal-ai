from korgan_legal_ai.domain.models import EvidenceLink, EvidenceMap, LockedCase


class EvidenceMapBuilder:
    def build(self, case: LockedCase) -> EvidenceMap:
        links: list[EvidenceLink] = []
        for fact in case.facts:
            evidence_ids = [e.id for e in case.evidence if fact.id in e.supports_fact_ids]
            links.append(EvidenceLink(fact_id=fact.id, evidence_ids=evidence_ids, supported=bool(evidence_ids)))
        return EvidenceMap(links=links)
