from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from korgan_legal_ai.procedural_rules.models import (
    DeadlineRule,
    JurisdictionRule,
    MrpValue,
    RuleBasis,
    StateDutyRule,
    StructuredRuleStatus,
)
from korgan_legal_ai.procedural_rules.repository import ProceduralRuleRepository


def load_procedural_rule_seed(path: str | Path, repository: ProceduralRuleRepository) -> int:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    reviewed_by = payload["reviewed_by"]
    reviewed_at = datetime.fromisoformat(payload["reviewed_at"])
    count = 0

    common = {
        "status": StructuredRuleStatus.CANONICAL,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
    }
    for raw in payload.get("state_duty_rules", []):
        data = dict(raw)
        data["basis"] = RuleBasis(**data["basis"])
        repository.upsert_state_duty(StateDutyRule(**data, **common))
        count += 1
    for raw in payload.get("mrp_values", []):
        data = dict(raw)
        data["basis"] = RuleBasis(**data["basis"])
        repository.upsert_mrp(MrpValue(**data, **common))
        count += 1
    for raw in payload.get("jurisdiction_rules", []):
        data = dict(raw)
        data["basis"] = RuleBasis(**data["basis"])
        repository.upsert_jurisdiction(JurisdictionRule(**data, **common))
        count += 1
    for raw in payload.get("deadline_rules", []):
        data = dict(raw)
        data["bases"] = [RuleBasis(**item) for item in data["bases"]]
        repository.upsert_deadline(DeadlineRule(**data, **common))
        count += 1
    return count
