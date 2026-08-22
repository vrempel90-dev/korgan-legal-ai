from __future__ import annotations

import asyncio
import inspect

from korgan.claim_intake_policy import inspect_claim_gaps
from korgan.citation_audit import ProvisionReference
from korgan.instant_claim_runtime import (
    InstantClaimProductionService,
    _send_claim,
    _strip_reference_token,
)


SCREENSHOT_CASE = """
Хочу подготовить иск.
Истец: Ахметова Гульнара Сериковна, ИИН 880512400156,
адрес: г. Алматы, Медеуский район, ул. Абая, 150, кв. 34,
телефон +7 701 234 56 78.
Ответчик: ТОО «КурылысСтройИнвест», БИН 150640012233,
адрес: г. Алматы, Алатауский район, ул. Момышулы, 5.
Требование: взыскать задолженность по договору подряда № 45 от 12.05.2025
на сумму 2 300 000 тенге — предоплата за ремонтные работы,
которые ответчик не выполнил и не вернул деньги.
"""


def test_sufficient_case_never_blocks_on_requisites() -> None:
    # Whatever the legacy preflight classifies as missing, the instant runtime
    # turns it into placeholders before generation instead of another dialogue.
    gaps = inspect_claim_gaps(SCREENSHOT_CASE).after_the_single_question()
    assert not gaps.blocks_drafting


def test_instant_validation_does_not_make_an_openai_call() -> None:
    service = object.__new__(InstantClaimProductionService)
    result = asyncio.run(service.validate_claim("case", None, None))  # type: ignore[arg-type]
    assert result == {
        "critical_errors": [],
        "unsupported_legal_claims": [],
        "missing_required_fields": [],
    }


def test_unverified_article_token_can_be_removed_without_losing_relief() -> None:
    text = "Взыскать с ответчика 2 300 000 тенге на основании статьи 630 ГК РК."
    cleaned = _strip_reference_token(text, ProvisionReference("ГК РК", "630"))
    assert "2 300 000" in cleaned
    assert "630" not in cleaned
    assert "ГК РК" not in cleaned


def test_normal_send_path_has_no_old_verification_dialogue() -> None:
    source = inspect.getsource(_send_claim)
    assert "_enter_verification_gate" not in source
    assert "Как поступить" not in source
    assert "Не удалось завершить юридическую проверку" not in source
