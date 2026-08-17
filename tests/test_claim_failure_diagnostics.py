"""Диагностика отказа: конкретная причина вместо generic-сообщения."""

import io

from docx import Document

from korgan.claim_docx import QA_PRELIMINARY, build_claim_docx, missing_required_fields
from korgan.claim_failure import (
    ClaimFailure,
    ClaimFailureCode,
    ClaimPipelineError,
    ClaimStage,
    CourtDocumentQualityError,
    failure_from_exception,
)
from korgan.claim_qa_policy import apply_soft_qa_findings, split_qa_issues
from korgan.legal_routing import detect_claim_profile
from korgan.legal_types import ClaimDraft, VerificationStatus


def _draft(**overrides) -> ClaimDraft:
    base = dict(
        status=VerificationStatus.NEEDS_VERIFICATION,
        title="ИСКОВОЕ ЗАЯВЛЕНИЕ о взыскании долга по расписке",
        court="[ТРЕБУЕТ УТОЧНЕНИЯ: точное наименование суда]",
        claimant=["Ахметов Руслан Маратович, ИИН 000000000101"],
        defendant=["Садыков Тимур Ерланович"],
        price_of_claim="800 000 тенге",
        facts=["Ответчик получил 800 000 тенге наличными и выдал расписку."],
        legal_basis=["Заёмщик обязан возвратить сумму займа."],
        requests=["Взыскать с ответчика 800 000 тенге основного долга."],
        attachments=["Копия расписки"],
        verification_notes=[],
        source_urls=[],
        state_duty="8 000 тенге (1% от цены иска)",
    )
    base.update(overrides)
    return ClaimDraft(**base)


def test_receipt_debt_routes_to_loan_profile() -> None:
    context = (
        "Долг по расписке. Деньги 800 000 тенге передавал наличными, "
        "банковского перевода не было. Единственное доказательство — расписка."
    )
    profile = detect_claim_profile(context)
    assert profile.code == "loan_debt"
    assert profile.required_article_hints == ("715", "716", "722")


def test_loan_phrasings_are_recognized() -> None:
    for context in (
        "Я дал ответчику деньги в долг, он обещал вернуть через два месяца",
        "Ответчик взял у меня в долг наличными 500 000 тенге",
        "Передала ему в долг деньги под расписку",
    ):
        assert detect_claim_profile(context).code == "loan_debt", context


def test_wage_debt_is_not_captured_by_loan_profile() -> None:
    profile = detect_claim_profile(
        "Работодатель не выплатил заработную плату, долг по зарплате за три месяца"
    )
    assert profile.code == "labor"


def test_missing_evidence_does_not_block_the_document() -> None:
    blocking, evidence_gaps, unsupported = split_qa_issues(
        critical_errors=[
            "Факт передачи денег утверждается как доказанный, но расписка не приложена",
            "Претензия ответчику не направлялась, досудебный порядок не подтверждён",
        ],
        unsupported_legal_claims=[],
        hard_issues=[],
    )
    assert blocking == []
    assert len(evidence_gaps) == 2
    assert unsupported == []


def test_unsupported_law_never_blocks_the_document() -> None:
    blocking, _, unsupported = split_qa_issues(
        critical_errors=[],
        unsupported_legal_claims=["Ссылка на статью 716 ГК РК отсутствует в VERIFIED"],
        hard_issues=[],
    )
    assert blocking == []
    assert unsupported == ["Ссылка на статью 716 ГК РК отсутствует в VERIFIED"]


def test_fabrication_and_hard_issues_still_block() -> None:
    blocking, _, _ = split_qa_issues(
        critical_errors=[
            "Сумма 900 000 тенге выдумана и отсутствует в материалах",
            "Перепутаны роли сторон в просительной части",
        ],
        unsupported_legal_claims=[],
        hard_issues=["известный ИИН/БИН 000000000101 потерян в реквизитах сторон"],
    )
    assert len(blocking) == 3
    assert any("выдумана" in item for item in blocking)
    assert any("потерян" in item for item in blocking)


def test_fabricated_pretrial_claim_is_blocking_not_a_gap() -> None:
    blocking, evidence_gaps, _ = split_qa_issues(
        critical_errors=["В фактах указана выдуманная претензия, которой нет в материалах"],
        unsupported_legal_claims=[],
        hard_issues=[],
    )
    assert len(blocking) == 1
    assert evidence_gaps == []


def test_soft_findings_become_needs_verification_inside_the_document() -> None:
    draft = _draft()
    apply_soft_qa_findings(
        draft,
        evidence_gaps=["Расписка не приложена к иску"],
        unsupported_legal_claims=["Статья 716 ГК РК не подтверждена официальным источником"],
    )
    assert any("Расписка не приложена" in note for note in draft.verification_notes)
    assert any("716" in note for note in draft.verification_notes)
    assert any("[ТРЕБУЕТ УТОЧНЕНИЯ" in item for item in draft.legal_basis)
    header = Document(io.BytesIO(build_claim_docx(draft))).paragraphs[0].text
    assert QA_PRELIMINARY in header


def test_soft_findings_are_not_duplicated_on_repeated_application() -> None:
    draft = _draft()
    for _ in range(2):
        apply_soft_qa_findings(
            draft,
            evidence_gaps=["Расписка не приложена к иску"],
            unsupported_legal_claims=["Статья 716 ГК РК не подтверждена"],
        )
    assert len(draft.verification_notes) == 2
    assert sum("[ТРЕБУЕТ УТОЧНЕНИЯ" in item for item in draft.legal_basis) == 1


def test_complete_draft_has_no_missing_document_fields() -> None:
    assert missing_required_fields(_draft()) == []


def test_missing_party_is_named_explicitly() -> None:
    absent = missing_required_fields(_draft(defendant=[], requests=[]))
    assert any("данные ответчика" in item and "адрес" in item for item in absent)
    assert "требования к ответчику (просительная часть)" in absent


def test_unknown_court_does_not_block_rendering() -> None:
    assert missing_required_fields(_draft(court="")) == []


def test_log_line_is_structured_and_greppable() -> None:
    failure = ClaimFailure(
        stage=ClaimStage.RENDER,
        code=ClaimFailureCode.MISSING_DOCUMENT_FIELD,
        fields=["наименование суда"],
    )
    line = failure.log_line()
    assert line.startswith("CLAIM_FAIL stage=render")
    assert "code=MISSING_DOCUMENT_FIELD" in line
    assert "наименование суда" in line


def test_user_message_names_the_concrete_field() -> None:
    message = ClaimFailure(
        stage=ClaimStage.RENDER,
        code=ClaimFailureCode.MISSING_DOCUMENT_FIELD,
        fields=["наименование суда"],
    ).user_message()
    assert "наименование суда" in message
    assert "Проверьте материалы и повторите запрос" not in message


def test_qa_block_message_lists_the_failed_checks() -> None:
    message = ClaimFailure(
        stage=ClaimStage.QA,
        code=ClaimFailureCode.QA_BLOCKED,
        issues=["Сумма 900 000 тенге выдумана и отсутствует в материалах"],
    ).user_message()
    assert "выдумана" in message


def test_quality_error_carries_machine_readable_reason() -> None:
    error = CourtDocumentQualityError(
        ClaimFailure(
            stage=ClaimStage.QA,
            code=ClaimFailureCode.QA_BLOCKED,
            issues=["перепутаны роли сторон"],
        )
    )
    assert error.failure.code is ClaimFailureCode.QA_BLOCKED
    assert error.failure.issues == ["перепутаны роли сторон"]


def test_legacy_string_raise_still_produces_a_reason() -> None:
    error = CourtDocumentQualityError("первый дефект; второй дефект")
    assert error.failure.stage is ClaimStage.QA
    assert error.failure.issues == ["первый дефект", "второй дефект"]


def test_malformed_draft_payload_is_reported_as_technical() -> None:
    failure = failure_from_exception(
        TypeError("unexpected keyword argument 'court_name'"), stage=ClaimStage.DRAFT
    )
    assert failure.code is ClaimFailureCode.DRAFT_MALFORMED
    assert "TypeError" in failure.detail


def test_pipeline_error_reason_survives_the_bot_handler_mapping() -> None:
    original = ClaimPipelineError(
        ClaimFailure(
            stage=ClaimStage.QA,
            code=ClaimFailureCode.QA_BLOCKED,
            issues=["дефект"],
        )
    )
    assert failure_from_exception(original, stage=ClaimStage.RENDER) is original.failure
