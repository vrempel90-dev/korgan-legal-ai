from __future__ import annotations

import logging
from urllib.parse import urlparse

from openai import AsyncOpenAI
from pinecone import Pinecone

from korgan.config import Settings
from korgan.legal_types import LegalAnswer, LegalSource, VerificationStatus

LOGGER = logging.getLogger(__name__)
TRUSTED_HOSTS = {"adilet.zan.kz"}


def is_trusted_source(url: str) -> bool:
    try:
        return urlparse(url).hostname in TRUSTED_HOSTS
    except ValueError:
        return False


class LegalRAG:
    """Strict RAG: legal facts are generated only from trusted retrieved sources."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.index = Pinecone(api_key=settings.pinecone_api_key).Index(
            settings.pinecone_index_name
        )

    async def _embed(self, text: str) -> list[float]:
        response = await self.openai.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def retrieve(self, query: str) -> tuple[LegalSource, ...]:
        vector = await self._embed(query)
        result = self.index.query(
            vector=vector,
            top_k=self.settings.rag_top_k,
            include_metadata=True,
        )

        sources: list[LegalSource] = []
        for match in getattr(result, "matches", []) or []:
            metadata = getattr(match, "metadata", {}) or {}
            score = float(getattr(match, "score", 0.0) or 0.0)
            url = str(metadata.get("url", ""))
            text = str(metadata.get("text", ""))
            if score < self.settings.rag_min_score:
                continue
            if not text or not is_trusted_source(url):
                continue
            sources.append(
                LegalSource(
                    title=str(metadata.get("title", "НПА Республики Казахстан")),
                    article=str(metadata.get("article", "")),
                    url=url,
                    text=text,
                    score=score,
                )
            )
        return tuple(sources)

    async def answer(self, query: str, language: str = "ru") -> LegalAnswer:
        sources = await self.retrieve(query)
        if not sources:
            return LegalAnswer(
                status=VerificationStatus.NEEDS_VERIFICATION,
                text=(
                    "Не удалось подтвердить правовое основание по проверенному источнику Adilet. "
                    "Я не буду придумывать статью, срок, госпошлину или подсудность. Требуется дополнительная проверка."
                    if language == "ru"
                    else "Құқықтық негіз Adilet-тегі тексерілген дереккөзбен расталмады. Мен бапты, мерзімді, мемлекеттік бажды немесе соттылықты ойдан шығармаймын. Қосымша тексеру қажет."
                ),
            )

        context_parts: list[str] = []
        for idx, source in enumerate(sources, 1):
            context_parts.append(
                f"SOURCE {idx}\nTitle: {source.title}\nArticle: {source.article or 'not specified'}\nURL: {source.url}\nText: {source.text}"
            )
        context = "\n\n".join(context_parts)

        lang_instruction = (
            "Answer in formal Russian legal language."
            if language == "ru"
            else "Answer in formal Kazakh legal language."
        )
        instructions = (
            "You are KORGAN Legal AI, a legal assistant for the Republic of Kazakhstan. "
            "Use ONLY the legal context supplied by the application. Do not use memory or general world knowledge to assert an article number, deadline, state duty, jurisdiction, legal status, or other concrete legal fact. "
            "If the supplied context is insufficient for any concrete legal statement, explicitly write NEEDS_VERIFICATION for that statement. Never fabricate citations. Separate facts from recommendations. Cite sources by title/article and URL. "
            + lang_instruction
        )
        prompt = f"User question:\n{query}\n\nVERIFIED CONTEXT:\n{context}"

        try:
            response = await self.openai.responses.create(
                model=self.settings.openai_model,
                instructions=instructions,
                input=prompt,
            )
            text = (response.output_text or "").strip()
        except Exception:
            LOGGER.exception("OpenAI response generation failed")
            return LegalAnswer(
                status=VerificationStatus.NEEDS_VERIFICATION,
                text="AI-сервис временно недоступен. Правовой ответ не сформирован.",
                sources=sources,
            )

        if not text:
            return LegalAnswer(
                status=VerificationStatus.NEEDS_VERIFICATION,
                text="Не удалось сформировать проверенный правовой ответ.",
                sources=sources,
            )

        status = VerificationStatus.NEEDS_VERIFICATION if "NEEDS_VERIFICATION" in text else VerificationStatus.VERIFIED
        return LegalAnswer(status=status, text=text, sources=sources)
