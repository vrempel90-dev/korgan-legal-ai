from korgan_legal_ai.audit.hash_chain import HashChainAuditLog


def test_hash_chain_verifies():
    log = HashChainAuditLog()
    log.append("one", {"a": 1})
    log.append("two", {"b": 2})
    assert log.verify() is True
    assert log.head != "GENESIS"
