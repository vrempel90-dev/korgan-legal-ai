from __future__ import annotations

import asyncio
import io

import pytest
from docx import Document


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_article_9_penalty_basis_is_not_poisoned_by_next_factual_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for production case KOR-2728CDCDBA32.

    The cited sentence is a proposition from Article 9 GK RK.  A following
    sentence applies a contractual penalty to the facts.  The final verifier
    must compare the cited proposition to Article 9, not require Article 9 to
    contain every factual/application term from the neighbouring sentence.
    """
    import korgan.live_article_release_runtime as runtime
    import korgan.live_article_release_stable_runtime as stable  # noqa: F401

    async def scenario() -> None:
        general = runtime.LiveAct(
            act_id=runtime.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="04.09.2026",
            articles={
                "9": {
                    "1": (
                        "Защита гражданских прав осуществляется путем признания прав; "
                        "восстановления положения, существовавшего до нарушения права; "
                        "взыскания убытков, неустойки, а также иными способами, "
                        "предусмотренными законодательными актами."
                    )
                }
            },
        )
        special = runtime.LiveAct(
            act_id=runtime.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="04.09.2026",
            articles={},
        )

        async def live_act(act_id: str):
            return general if act_id == runtime.ACT_GK_GENERAL else special

        monkeypatch.setattr(runtime, "_live_act", live_act)
        payload = _docx_bytes(
            "Согласно статье 9 ГК РК защита гражданских прав осуществляется путем взыскания неустойки. "
            "По договору неустойка начислена за просрочку срока оплаты и составляет 120 000 тенге."
        )

        await runtime.verify_document_articles(payload)

    asyncio.run(scenario())


def test_sentence_scope_still_blocks_penalty_wrongly_attributed_to_article_272(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sentence scoping must not weaken the legal-attribution gate."""
    import korgan.live_article_release_runtime as runtime
    import korgan.live_article_release_stable_runtime as stable  # noqa: F401

    async def scenario() -> None:
        general = runtime.LiveAct(
            act_id=runtime.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="04.09.2026",
            articles={
                "272": {
                    "": (
                        "Обязательство должно исполняться надлежащим образом в соответствии "
                        "с условиями обязательства и требованиями законодательства."
                    )
                }
            },
        )
        special = runtime.LiveAct(
            act_id=runtime.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="04.09.2026",
            articles={},
        )

        async def live_act(act_id: str):
            return general if act_id == runtime.ACT_GK_GENERAL else special

        monkeypatch.setattr(runtime, "_live_act", live_act)
        payload = _docx_bytes(
            "Согласно статье 272 ГК РК кредитор вправе взыскать неустойку. "
            "По договору сумма требований составляет 120 000 тенге."
        )

        with pytest.raises(runtime.LiveArticleVerificationError, match="неустойка"):
            await runtime.verify_document_articles(payload)

    asyncio.run(scenario())


def test_exact_quote_keeps_original_paragraph_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact-quote verification remains strict after sentence scoping."""
    import korgan.live_article_release_runtime as runtime
    import korgan.live_article_release_stable_runtime as stable  # noqa: F401

    provision = (
        "Обязательство должно исполняться надлежащим образом в соответствии "
        "с условиями обязательства и требованиями законодательства."
    )

    async def scenario() -> None:
        general = runtime.LiveAct(
            act_id=runtime.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="04.09.2026",
            articles={"272": {"": provision}},
        )
        special = runtime.LiveAct(
            act_id=runtime.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="04.09.2026",
            articles={},
        )

        async def live_act(act_id: str):
            return general if act_id == runtime.ACT_GK_GENERAL else special

        monkeypatch.setattr(runtime, "_live_act", live_act)
        payload = _docx_bytes(
            "Согласно статье 272 ГК РК: «" + provision + "» Далее приведены обстоятельства дела."
        )
        await runtime.verify_document_articles(payload)

    asyncio.run(scenario())
