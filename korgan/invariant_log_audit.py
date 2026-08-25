"""Audit KORGAN production logs against the 25.08.2026 I1-I10 contract.

Usage:
    python -m korgan.invariant_log_audit railway.log

The result is intentionally mechanical.  It never asks a model whether a run
"looks good"; it only consumes structured/legacy log evidence.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class InvariantFinding:
    invariant: str
    passed: bool = True
    violations: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        if reason not in self.violations:
            self.violations.append(reason)


@dataclass(slots=True)
class AuditResult:
    findings: dict[str, InvariantFinding]
    penalties: int
    penalty_reasons: list[str]

    @property
    def passed_count(self) -> int:
        return sum(1 for finding in self.findings.values() if finding.passed)

    @property
    def total(self) -> int:
        return len(self.findings)

    @property
    def accepted(self) -> bool:
        return self.passed_count == self.total and self.penalties == 0

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "invariants_passed": self.passed_count,
            "invariants_total": self.total,
            "penalties": self.penalties,
            "penalty_reasons": list(self.penalty_reasons),
            "findings": {key: asdict(value) for key, value in self.findings.items()},
        }


_WORD_QUALITY_RE = re.compile(r"UNIVERSAL_WORD_QUALITY\s+kind=(?P<kind>\S+).*?issues_after=(?P<issues>\d+)(?P<tail>.*)")
_FIELD_INT_RE = re.compile(r"(?P<key>[a-zA-Z_]+)=(?P<value>-?\d+)")
_REPAIRED_RE = re.compile(r"FAST_PROFESSIONAL_PREFLIGHT\s+stage=repaired\s+score=(?P<score>\d+(?:\.\d+)?)")
_FINALIZED_RE = re.compile(r"FINALIZED_PROFESSIONAL_CLAIM\s+score=(?P<score>\d+(?:\.\d+)?)")
_MONEY_RE = re.compile(r"CLAIM_MONEY_AUTHORITY\b(?P<tail>.*)")
_RESCUE_RE = re.compile(r"CLAIM_MATERIAL_LAW_RESCUE\b(?P<tail>.*)")
_REPAIR_RE = re.compile(r"(?i)REPAIR.*?(?:score=(?P<score>\d+(?:\.\d+)?)).*?blockers=(?P<blockers>\[[^\n]*\])")
_NORM_SET_RE = re.compile(
    r"RESEARCH_NORM_SET\b.*?input_hash=(?P<input>[0-9a-f]+).*?norm_hash=(?P<norm>[0-9a-f]+)"
)
_RESEARCH_BALANCE_RE = re.compile(r"RESEARCH_(?:INVARIANT|HIGH_CONTEXT_COMPARE)\b(?P<tail>.*)")
_FINAL_ONCE_RE = re.compile(r"FINALIZATION_ONCE\b(?P<tail>.*)")


def _fields(tail: str) -> dict[str, int]:
    return {match.group("key"): int(match.group("value")) for match in _FIELD_INT_RE.finditer(tail or "")}


def audit_log(log_text: str) -> AuditResult:
    findings = {f"I{i}": InvariantFinding(f"I{i}") for i in range(1, 11)}
    penalties = 0
    penalty_reasons: list[str] = []
    lines = [line.strip() for line in (log_text or "").splitlines() if line.strip()]

    # I1/I2: no issue may be delivered silently.  New v2 delivery logs make
    # visibility explicit via internal_markers/user_visible.
    for line in lines:
        match = _WORD_QUALITY_RE.search(line)
        if not match:
            continue
        issues = int(match.group("issues"))
        tail = match.group("tail")
        fields = _fields(tail)
        delivered = fields.get("delivered")
        markers = fields.get("internal_markers", fields.get("user_visible", 0))
        if issues > 0 and delivered == 1 and markers <= 0:
            reason = f"{match.group('kind')}: issues_after={issues} delivered=1 без видимого маркера"
            findings["I1"].fail(reason)
            findings["I2"].fail(reason)
            penalties -= 3
            penalty_reasons.append("известный системе дефект не доведён до пользователя: " + reason)

    # Legacy production evidence from 25.08: PRETRIAL_PRELIMINARY meant the
    # warning was only in logs while the file still went out with generic copy.
    for line in lines:
        if "PRETRIAL_PRELIMINARY issues=" in line:
            reason = "legacy PRETRIAL_PRELIMINARY: quality warning was not structurally disclosed"
            findings["I2"].fail(reason)
            penalties -= 3
            penalty_reasons.append("известный системе дефект не доведён до пользователя: " + reason)

    # I3: an internal citation/formulation defect may not become a dead-end user
    # gate.  The v2 runtime only logs blocker_class=NEEDS_USER_DATA for blocking.
    for line in lines:
        if "blocker_class=INTERNAL_QUALITY" in line and ("BLOCK" in line.upper() or "delivered=0" in line):
            reason = line[-500:]
            findings["I3"].fail(reason)
            penalties -= 3
            penalty_reasons.append("блокировка по причине, которую пользователь не может устранить: " + reason)
        if "CLAIM_FINAL_RELEASE_REPAIR_BLOCKED" in line and "citations=" in line:
            reason = "legacy claim release blocked on generated citation/formulation defect"
            findings["I3"].fail(reason)
            penalties -= 3
            penalty_reasons.append("блокировка INTERNAL_QUALITY: " + reason)

    # I4: every NEEDS_USER_DATA block must have exact reasons and actions in the
    # structured companion event.
    block_lines = [line for line in lines if "blocker_class=NEEDS_USER_DATA" in line and "UNIVERSAL_WORD_QUALITY" in line]
    reason_lines = [line for line in lines if "USER_BLOCK_REASON" in line and "reasons=" in line and "actions=" in line]
    if block_lines and not reason_lines:
        findings["I4"].fail("NEEDS_USER_DATA block exists without USER_BLOCK_REASON reasons/actions event")

    # I5: money input must reach the ledger and contractual arithmetic may not be
    # silently unresolved when the ledger claims a finished result.
    for line in lines:
        match = _MONEY_RE.search(line)
        if not match:
            continue
        fields = _fields(match.group("tail"))
        ledger_total = fields.get("ledger_total")
        input_amounts = fields.get("input_amounts")
        if ledger_total == 0 and (input_amounts is None or input_amounts > 0):
            reason = line[-500:]
            findings["I5"].fail(reason)
            penalties -= 3
            penalty_reasons.append("ledger_total=0 при денежном входе: " + reason)

    # I6: a logged rescue addition must have a concrete removed/rewritten mate.
    for line in lines:
        match = _RESCUE_RE.search(line)
        if not match:
            continue
        tail = match.group("tail")
        has_added = not re.search(r"added=\[\]", tail)
        removed_empty = bool(re.search(r"removed=\[\]", tail))
        rewritten_empty = bool(re.search(r"rewritten=\[\]", tail))
        if has_added and removed_empty and rewritten_empty:
            reason = line[-500:]
            findings["I6"].fail(reason)
            penalties -= 2
            penalty_reasons.append("rescue добавил норму без снятия/переписывания заменяемого фрагмента: " + reason)

    # I7: a repair iteration that leaves both score and blocker set unchanged is
    # itself a penalty; repeating it is also an invariant failure.
    previous: tuple[str, str] | None = None
    no_progress_count = 0
    for line in lines:
        match = _REPAIR_RE.search(line)
        if not match:
            continue
        current = (match.group("score"), match.group("blockers"))
        if previous == current:
            no_progress_count += 1
            findings["I7"].fail("repair повторил тот же score и blocker set")
        previous = current
    # Explicit guard stop is evidence the duplicate model call did NOT happen,
    # therefore it is not a violation by itself.
    if no_progress_count:
        penalties -= no_progress_count
        penalty_reasons.append(f"repair без прогресса: {no_progress_count} итерац.")

    # I8: compare each final score to the latest preceding repaired score.
    repaired_score: float | None = None
    for line in lines:
        repaired = _REPAIRED_RE.search(line)
        if repaired:
            repaired_score = float(repaired.group("score"))
            continue
        finalized = _FINALIZED_RE.search(line)
        if finalized and repaired_score is not None:
            final_score = float(finalized.group("score"))
            if final_score < repaired_score:
                findings["I8"].fail(f"finalized_score={final_score} < repaired_score={repaired_score}")
            repaired_score = None

    # I9: exact same input hash must never have two different provision-set hashes.
    norms_by_input: dict[str, str] = {}
    for line in lines:
        match = _NORM_SET_RE.search(line)
        if not match:
            continue
        key, value = match.group("input"), match.group("norm")
        previous_norm = norms_by_input.get(key)
        if previous_norm is not None and previous_norm != value:
            findings["I9"].fail(f"input_hash={key}: norm_hash {previous_norm} -> {value}")
        norms_by_input[key] = value

    # The balance condition is part of acceptance.  It is attached to I9 because
    # both are research-output invariants; an explicit invariant_ok=0 fails it.
    for line in lines:
        if "RESEARCH_HIGH_CONTEXT_COMPARE" in line and "invariant_ok=0" in line:
            findings["I9"].fail("research ended with verified < unverified after bounded high-context recovery")
        if "RESEARCH_INVARIANT" in line and "status=VIOLATED" in line:
            # Do not fail immediately if a later bounded retry recovered; handled
            # by the final compare event above when present.
            if not any("RESEARCH_HIGH_CONTEXT_COMPARE" in later and "invariant_ok=1" in later for later in lines):
                findings["I9"].fail("verified < unverified")

    # I10: delivery/finalization guard makes duplicates directly observable.
    for line in lines:
        match = _FINAL_ONCE_RE.search(line)
        if match and _fields(match.group("tail")).get("accepted") == 0:
            findings["I10"].fail("duplicate finalization/delivery was attempted")
        if "PIPELINE_INVARIANT_VIOLATION invariant=I10" in line:
            findings["I10"].fail(line[-500:])

    return AuditResult(findings=findings, penalties=penalties, penalty_reasons=penalty_reasons)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Audit KORGAN production logs against invariants I1-I10")
    parser.add_argument("logfile", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    result = audit_log(args.logfile.read_text(encoding="utf-8", errors="replace"))
    payload = result.as_dict()
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"KORGAN INVARIANTS: {payload['invariants_passed']}/{payload['invariants_total']} "
            f"penalties={payload['penalties']} accepted={payload['accepted']}"
        )
        for key, finding in payload["findings"].items():
            status = "OK" if finding["passed"] else "FAIL"
            print(f"{key}: {status}")
            for violation in finding["violations"]:
                print(f"  - {violation}")
        for reason in payload["penalty_reasons"]:
            print(f"PENALTY: {reason}")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(_main())
