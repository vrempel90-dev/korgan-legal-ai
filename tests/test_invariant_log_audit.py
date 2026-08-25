from korgan.invariant_log_audit import audit_log


def test_clean_v2_log_is_accepted() -> None:
    log = """
    UNIVERSAL_WORD_QUALITY kind=claim issues_after=1 delivered=1 internal_markers=1
    CLAIM_MONEY_AUTHORITY price='3 900 000 тенге' input_amounts=1 ledger_total=3900000 principal=3250000 penalty=650000 unresolved=0
    CLAIM_MATERIAL_LAW_RESCUE added=['статья 439'] removed=['устаревший пересказ'] rewritten=[]
    FAST_PROFESSIONAL_PREFLIGHT stage=repaired score=8.4 deterministic=[] blockers=[]
    FINALIZED_PROFESSIONAL_CLAIM score=8.4 deterministic=[] blockers=[]
    RESEARCH_NORM_SET run=1 input_hash=aaaaaaaa norm_hash=bbbbbbbb norms=['ГК РК:439'] verified=2 unverified=1
    RESEARCH_NORM_SET run=2 input_hash=aaaaaaaa norm_hash=bbbbbbbb norms=['ГК РК:439'] verified=2 unverified=1
    RESEARCH_HIGH_CONTEXT_COMPARE retry=0 first_verified=2 first_unverified=1 chosen=first
    FINALIZATION_ONCE run=1 kind=claim accepted=1
    """
    result = audit_log(log)
    assert result.accepted is True
    assert result.passed_count == 10
    assert result.penalties == 0


def test_legacy_failure_patterns_are_detected_without_model_judgment() -> None:
    log = """
    UNIVERSAL_WORD_QUALITY kind=pretrial issues_after=1 delivered=1 internal_markers=0
    PRETRIAL_PRELIMINARY issues=['Для самостоятельного требования неустойки нет source-bound VERIFIED нормы']
    UNIVERSAL_WORD_QUALITY kind=claim issues_after=1 blocker_class=NEEDS_USER_DATA
    CLAIM_FINAL_RELEASE_REPAIR_BLOCKED citations=['статья 469 ГК РК: пересказ обобщает узкое условие нормы']
    CLAIM_MONEY_AUTHORITY price=None ledger_total=0 unresolved=0
    CLAIM_MATERIAL_LAW_RESCUE stale_act=GK_RK_OBSHAYA added=['GK_RK_OSOBENNAYA:439:2'] removed=[] rewritten=[]
    REPAIR iteration=1 score=8.4 blockers=['статья 469']
    REPAIR iteration=2 score=8.4 blockers=['статья 469']
    FAST_PROFESSIONAL_PREFLIGHT stage=repaired score=8.4 deterministic=[] blockers=['x']
    FINALIZED_PROFESSIONAL_CLAIM score=7.8 deterministic=[] blockers=['x']
    RESEARCH_NORM_SET run=1 input_hash=aaaaaaaa norm_hash=bbbbbbbb norms=['ГК РК:439'] verified=1 unverified=0
    RESEARCH_NORM_SET run=2 input_hash=aaaaaaaa norm_hash=cccccccc norms=['ГК РК:469'] verified=1 unverified=0
    FINALIZATION_ONCE run=1 kind=claim accepted=0
    """
    result = audit_log(log)
    assert result.accepted is False
    for invariant in ("I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10"):
        assert result.findings[invariant].passed is False
    assert result.penalties < 0


def test_research_balance_failure_is_not_accepted() -> None:
    result = audit_log(
        "RESEARCH_HIGH_CONTEXT_COMPARE retry=1 first_verified=1 first_unverified=3 "
        "second_verified=2 second_unverified=3 chosen=second invariant_ok=0"
    )
    assert result.findings["I9"].passed is False
    assert result.accepted is False


def test_user_block_with_structured_reason_and_action_passes_i4() -> None:
    log = """
    UNIVERSAL_WORD_QUALITY kind=pretrial issues_after=1 blocker_class=NEEDS_USER_DATA
    USER_BLOCK_REASON run=42 kind=досудебная blocker_class=NEEDS_USER_DATA reasons=['не указан отправитель'] actions=['укажите отправителя']
    """
    result = audit_log(log)
    assert result.findings["I4"].passed is True
