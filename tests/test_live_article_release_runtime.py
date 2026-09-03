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


def test_live_article_guard_accepts_exact_current_official_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.live_article_release_runtime as runtime

    async def scenario() -> None:
        provision = (
            "Обязательство должно исполняться надлежащим образом в соответствии "
            "с условиями обязательства и требованиями законодательства."
        )
        general = runtime.LiveAct(
            act_id=runtime.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="01.01.2026",
            articles={"272": {"": provision}},
        )
        special = runtime.LiveAct(
            act_id=runtime.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="01.01.2026",
            articles={},
        )

        async def live_act(act_id: str):
            return general if act_id == runtime.ACT_GK_GENERAL else special

        monkeypatch.setattr(runtime, "_live_act", live_act)
        payload = _docx_bytes(
            "Согласно статье 272 ГК РК: «" + provision + "»"
        )

        await runtime.verify_document_articles(payload)

    asyncio.run(scenario())


def test_live_article_guard_blocks_article_missing_from_current_adilet(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.live_article_release_runtime as runtime

    async def scenario() -> None:
        empty_general = runtime.LiveAct(
            act_id=runtime.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="01.01.2026",
            articles={},
        )
        empty_special = runtime.LiveAct(
            act_id=runtime.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="01.01.2026",
            articles={},
        )

        async def live_act(act_id: str):
            return empty_general if act_id == runtime.ACT_GK_GENERAL else empty_special

        monkeypatch.setattr(runtime, "_live_act", live_act)
        payload = _docx_bytes("На основании статьи 9999 ГК РК заявитель просит удовлетворить требования.")

        with pytest.raises(runtime.LiveArticleVerificationError, match="не найдена"):
            await runtime.verify_document_articles(payload)

    asyncio.run(scenario())


def test_live_article_guard_blocks_quote_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.live_article_release_runtime as runtime

    async def scenario() -> None:
        general = runtime.LiveAct(
            act_id=runtime.ACT_GK_GENERAL,
            source_url="https://adilet.zan.kz/rus/docs/K940001000_",
            edition_date="01.01.2026",
            articles={
                "272": {
                    "": "Обязательство должно исполняться надлежащим образом в соответствии с условиями обязательства."
                }
            },
        )
        special = runtime.LiveAct(
            act_id=runtime.ACT_GK_SPECIAL,
            source_url="https://adilet.zan.kz/rus/docs/K990000409_",
            edition_date="01.01.2026",
            articles={},
        )

        async def live_act(act_id: str):
            return general if act_id == runtime.ACT_GK_GENERAL else special

        monkeypatch.setattr(runtime, "_live_act", live_act)
        payload = _docx_bytes(
            "Согласно статье 272 ГК РК: «Должник обязан уплатить штраф в размере пятидесяти процентов.»"
        )

        with pytest.raises(runtime.LiveArticleVerificationError, match="не совпадает"):
            await runtime.verify_document_articles(payload)

    asyncio.run(scenario())


def test_live_article_guard_blocks_unowned_statute_instead_of_guessing(monkeypatch: pytest.MonkeyPatch) -> None:
    import korgan.live_article_release_runtime as runtime

    async def scenario() -> None:
        # KAS is intentionally outside the civil-document deterministic live map
        # for this release. A source-bound AI answer is not enough to fabricate a
        # filing citation: unsupported acts fail closed until a verifier is added.
        payload = _docx_bytes("Согласно статье 5 КАС РК административный орган обязан совершить действие.")
        with pytest.raises(runtime.LiveArticleVerificationError, match="нет детерминированного live-verifier"):
            await runtime.verify_document_articles(payload)

    asyncio.run(scenario())
