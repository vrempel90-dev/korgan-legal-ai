from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RULES_DIR = Path(__file__).parent
DEFAULT_VERSION = 1


@dataclass(frozen=True)
class HouseStyleRule:
    """One presentation rule extracted from the private reference corpus.

    ``source_count`` records how many corpus documents exhibited the pattern. It describes the
    firm's drafting habit and carries no legal weight: it must never be read as evidence that a
    norm applies to a new case.
    """

    id: str
    title: str
    source_count: int
    observed_in: str

    @property
    def is_legal_authority(self) -> bool:
        """Always False. Kept explicit so callers cannot mistake style for law."""
        return False


@dataclass(frozen=True)
class HouseStyleRuleSet:
    version: int
    rules: tuple[HouseStyleRule, ...]

    def get(self, rule_id: str) -> HouseStyleRule | None:
        return next((rule for rule in self.rules if rule.id == rule_id), None)

    def ids(self) -> tuple[str, ...]:
        return tuple(rule.id for rule in self.rules)


@lru_cache(maxsize=8)
def load_rules(version: int = DEFAULT_VERSION) -> HouseStyleRuleSet:
    """Load a pinned rule-set version so a generated document stays reproducible."""
    path = RULES_DIR / f"rules.v{version}.json"
    if not path.is_file():
        raise FileNotFoundError(f"House-style rule set v{version} is not bundled")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rules = tuple(
        HouseStyleRule(
            id=item["id"],
            title=item["title"],
            source_count=int(item["source_count"]),
            observed_in=item["observed_in"],
        )
        for item in payload["rules"]
    )
    return HouseStyleRuleSet(version=int(payload["version"]), rules=rules)
