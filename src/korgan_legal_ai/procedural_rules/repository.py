from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Engine, text

from korgan_legal_ai.procedural_rules.models import (
    DeadlineRule,
    JurisdictionRule,
    MrpValue,
    RuleBasis,
    StateDutyRule,
    StructuredRuleStatus,
)


class ProceduralRuleRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _base_params(rule) -> dict:
        data = rule.model_dump(mode="python", exclude={"basis", "bases"})
        data["status"] = rule.status.value
        return data

    def upsert_state_duty(self, rule: StateDutyRule) -> UUID:
        params = self._base_params(rule)
        params.update({
            "basis_code_id": rule.basis.code_id,
            "basis_article": rule.basis.article_number,
            "basis_part": rule.basis.part,
            "basis_point": rule.basis.point,
        })
        query = text("""
            INSERT INTO procedural_state_duty_rules (
                id, rule_code, claimant_type, claim_type, rate_percent, cap_mrp,
                basis_code_id, basis_article, basis_part, basis_point,
                effective_from, effective_to, status, reviewed_by, reviewed_at
            ) VALUES (
                :id, :rule_code, :claimant_type, :claim_type, :rate_percent, :cap_mrp,
                :basis_code_id, :basis_article, :basis_part, :basis_point,
                :effective_from, :effective_to, :status, :reviewed_by, :reviewed_at
            )
            ON CONFLICT (rule_code, effective_from) DO UPDATE SET
                claimant_type=EXCLUDED.claimant_type, claim_type=EXCLUDED.claim_type,
                rate_percent=EXCLUDED.rate_percent, cap_mrp=EXCLUDED.cap_mrp,
                basis_code_id=EXCLUDED.basis_code_id, basis_article=EXCLUDED.basis_article,
                basis_part=EXCLUDED.basis_part, basis_point=EXCLUDED.basis_point,
                effective_to=EXCLUDED.effective_to, status=EXCLUDED.status,
                reviewed_by=EXCLUDED.reviewed_by, reviewed_at=EXCLUDED.reviewed_at
            RETURNING id
        """)
        with self.engine.begin() as connection:
            return connection.execute(query, params).scalar_one()

    def upsert_mrp(self, value: MrpValue) -> UUID:
        params = self._base_params(value)
        params.update({
            "basis_code_id": value.basis.code_id,
            "basis_article": value.basis.article_number,
            "basis_part": value.basis.part,
            "basis_point": value.basis.point,
        })
        query = text("""
            INSERT INTO procedural_mrp_values (
                id, value_year, value_kzt, basis_code_id, basis_article, basis_part, basis_point,
                effective_from, effective_to, status, reviewed_by, reviewed_at
            ) VALUES (
                :id, :value_year, :value_kzt, :basis_code_id, :basis_article, :basis_part, :basis_point,
                :effective_from, :effective_to, :status, :reviewed_by, :reviewed_at
            )
            ON CONFLICT (value_year, effective_from) DO UPDATE SET
                value_kzt=EXCLUDED.value_kzt, basis_code_id=EXCLUDED.basis_code_id,
                basis_article=EXCLUDED.basis_article, basis_part=EXCLUDED.basis_part,
                basis_point=EXCLUDED.basis_point, effective_to=EXCLUDED.effective_to,
                status=EXCLUDED.status, reviewed_by=EXCLUDED.reviewed_by,
                reviewed_at=EXCLUDED.reviewed_at
            RETURNING id
        """)
        with self.engine.begin() as connection:
            return connection.execute(query, params).scalar_one()

    def upsert_jurisdiction(self, rule: JurisdictionRule) -> UUID:
        params = self._base_params(rule)
        params.update({
            "basis_code_id": rule.basis.code_id,
            "basis_article": rule.basis.article_number,
            "basis_part": rule.basis.part,
            "basis_point": rule.basis.point,
        })
        query = text("""
            INSERT INTO procedural_jurisdiction_rules (
                id, rule_code, dimension, plaintiff_type, defendant_type, dispute_type, result_code,
                basis_code_id, basis_article, basis_part, basis_point,
                effective_from, effective_to, status, reviewed_by, reviewed_at
            ) VALUES (
                :id, :rule_code, :dimension, :plaintiff_type, :defendant_type, :dispute_type, :result_code,
                :basis_code_id, :basis_article, :basis_part, :basis_point,
                :effective_from, :effective_to, :status, :reviewed_by, :reviewed_at
            )
            ON CONFLICT (rule_code, effective_from) DO UPDATE SET
                dimension=EXCLUDED.dimension, plaintiff_type=EXCLUDED.plaintiff_type,
                defendant_type=EXCLUDED.defendant_type, dispute_type=EXCLUDED.dispute_type,
                result_code=EXCLUDED.result_code, basis_code_id=EXCLUDED.basis_code_id,
                basis_article=EXCLUDED.basis_article, basis_part=EXCLUDED.basis_part,
                basis_point=EXCLUDED.basis_point, effective_to=EXCLUDED.effective_to,
                status=EXCLUDED.status, reviewed_by=EXCLUDED.reviewed_by,
                reviewed_at=EXCLUDED.reviewed_at
            RETURNING id
        """)
        with self.engine.begin() as connection:
            return connection.execute(query, params).scalar_one()

    def upsert_deadline(self, rule: DeadlineRule) -> UUID:
        params = self._base_params(rule)
        query = text("""
            INSERT INTO procedural_deadline_rules (
                id, rule_code, deadline_type, duration_value, duration_unit, trigger_event,
                start_offset_days, requires_workday_calendar,
                effective_from, effective_to, status, reviewed_by, reviewed_at
            ) VALUES (
                :id, :rule_code, :deadline_type, :duration_value, :duration_unit, :trigger_event,
                :start_offset_days, :requires_workday_calendar,
                :effective_from, :effective_to, :status, :reviewed_by, :reviewed_at
            )
            ON CONFLICT (rule_code, effective_from) DO UPDATE SET
                deadline_type=EXCLUDED.deadline_type, duration_value=EXCLUDED.duration_value,
                duration_unit=EXCLUDED.duration_unit, trigger_event=EXCLUDED.trigger_event,
                start_offset_days=EXCLUDED.start_offset_days,
                requires_workday_calendar=EXCLUDED.requires_workday_calendar,
                effective_to=EXCLUDED.effective_to, status=EXCLUDED.status,
                reviewed_by=EXCLUDED.reviewed_by, reviewed_at=EXCLUDED.reviewed_at
            RETURNING id
        """)
        with self.engine.begin() as connection:
            rule_id = connection.execute(query, params).scalar_one()
            connection.execute(
                text("DELETE FROM procedural_deadline_bases WHERE deadline_rule_id=:id"),
                {"id": rule_id},
            )
            for sequence, basis in enumerate(rule.bases, start=1):
                connection.execute(
                    text("""
                        INSERT INTO procedural_deadline_bases (
                            deadline_rule_id, sequence, code_id, article_number, part, point
                        ) VALUES (:deadline_rule_id, :sequence, :code_id, :article_number, :part, :point)
                    """),
                    {
                        "deadline_rule_id": rule_id,
                        "sequence": sequence,
                        "code_id": basis.code_id,
                        "article_number": basis.article_number,
                        "part": basis.part,
                        "point": basis.point,
                    },
                )
        return rule_id

    @staticmethod
    def _basis(row) -> RuleBasis:
        return RuleBasis(
            code_id=row["basis_code_id"], article_number=row["basis_article"],
            part=row["basis_part"], point=row["basis_point"]
        )

    def find_state_duty(self, *, claimant_type: str, claim_type: str, event_date: date) -> StateDutyRule | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT * FROM procedural_state_duty_rules
                WHERE status='canonical' AND claimant_type=:claimant_type AND claim_type=:claim_type
                  AND effective_from<=:event_date AND (effective_to IS NULL OR effective_to>=:event_date)
                ORDER BY effective_from DESC LIMIT 1
            """), {"claimant_type": claimant_type, "claim_type": claim_type, "event_date": event_date}).mappings().first()
        if row is None:
            return None
        data = dict(row)
        basis = self._basis(data)
        for key in ("basis_code_id","basis_article","basis_part","basis_point"):
            data.pop(key)
        data["status"] = StructuredRuleStatus(data["status"])
        return StateDutyRule(**data, basis=basis)

    def find_mrp(self, *, event_date: date) -> MrpValue | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT * FROM procedural_mrp_values
                WHERE status='canonical' AND effective_from<=:event_date
                  AND (effective_to IS NULL OR effective_to>=:event_date)
                ORDER BY effective_from DESC LIMIT 1
            """), {"event_date": event_date}).mappings().first()
        if row is None:
            return None
        data = dict(row)
        basis = self._basis(data)
        for key in ("basis_code_id","basis_article","basis_part","basis_point"):
            data.pop(key)
        data["status"] = StructuredRuleStatus(data["status"])
        return MrpValue(**data, basis=basis)

    def find_jurisdiction(
        self, *, dimension: str, plaintiff_type: str, defendant_type: str,
        dispute_type: str, event_date: date
    ) -> JurisdictionRule | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT * FROM procedural_jurisdiction_rules
                WHERE status='canonical' AND dimension=:dimension
                  AND plaintiff_type=:plaintiff_type AND defendant_type=:defendant_type
                  AND dispute_type=:dispute_type AND effective_from<=:event_date
                  AND (effective_to IS NULL OR effective_to>=:event_date)
                ORDER BY effective_from DESC LIMIT 1
            """), {
                "dimension": dimension, "plaintiff_type": plaintiff_type,
                "defendant_type": defendant_type, "dispute_type": dispute_type,
                "event_date": event_date,
            }).mappings().first()
        if row is None:
            return None
        data = dict(row)
        basis = self._basis(data)
        for key in ("basis_code_id","basis_article","basis_part","basis_point"):
            data.pop(key)
        data["status"] = StructuredRuleStatus(data["status"])
        return JurisdictionRule(**data, basis=basis)

    def find_deadline(self, *, rule_code: str, event_date: date) -> DeadlineRule | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT * FROM procedural_deadline_rules
                WHERE status='canonical' AND rule_code=:rule_code AND effective_from<=:event_date
                  AND (effective_to IS NULL OR effective_to>=:event_date)
                ORDER BY effective_from DESC LIMIT 1
            """), {"rule_code": rule_code, "event_date": event_date}).mappings().first()
            if row is None:
                return None
            bases = connection.execute(text("""
                SELECT code_id, article_number, part, point FROM procedural_deadline_bases
                WHERE deadline_rule_id=:id ORDER BY sequence
            """), {"id": row["id"]}).mappings().all()
        data = dict(row)
        data["status"] = StructuredRuleStatus(data["status"])
        return DeadlineRule(**data, bases=[RuleBasis(**dict(item)) for item in bases])
