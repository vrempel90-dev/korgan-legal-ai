from korgan.citation_audit import CitationVerdict, audit_citations


def test_runtime_verified_paraphrase_marked_for_verification_does_not_block_release() -> None:
    verified = [
        "Специализированные межрайонные экономические суды рассматривают гражданские дела по спорам, сторонами которых являются юридические лица и индивидуальные предприниматели. "
        "[основание: статья 27 ГПК РК; текст нормы: «Специализированные межрайонные экономические суды рассматривают и разрешают гражданские дела по имущественным и неимущественным спорам, сторонами в которых являются индивидуальные предприниматели и юридические лица»; источник: https://adilet.zan.kz/rus/docs/K1500000377]"
    ]
    text = (
        "[ТРЕБУЕТ ПРОВЕРКИ: правовое основание требования включает нормы статьи 27 ГПК РК. "
        "Действующая редакция и содержание статьи 27 ГПК РК подлежат сверке по официальному источнику до подачи документа; "
        "в настоящем документе содержание нормы не утверждается.]"
    )

    audit = audit_citations(text, verified_claims=verified)

    assert audit.findings
    assert not audit.blocking
    assert all(
        item.verdict in {CitationVerdict.UNVERIFIED_SOURCE, CitationVerdict.PARAPHRASE_OK}
        for item in audit.findings
    )
