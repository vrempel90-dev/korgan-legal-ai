from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from pinecone import Pinecone

from korgan.config import get_settings

ARTICLE_RE = re.compile(r"(?im)^(?:Статья|Бап)\s+([0-9]+(?:-[0-9]+)?)\b[^\n]*")
MAX_CHARS = 6000


def _validate_adilet_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "adilet.zan.kz":
        raise ValueError("Only https://adilet.zan.kz sources are allowed")


def _extract(url: str) -> tuple[str, str]:
    response = requests.get(url, headers={"User-Agent": "KORGAN-Legal-AI/1.0"}, timeout=30)
    response.raise_for_status()
    text = trafilatura.extract(response.text, include_links=False, include_images=False, include_tables=True, favor_precision=True)
    if not text:
        raise RuntimeError("Could not extract legal text from Adilet page")
    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "Adilet"
    return title, text


def _split_articles(text: str) -> list[tuple[str, str]]:
    matches = list(ARTICLE_RE.finditer(text))
    if not matches:
        return [("", text[i : i + MAX_CHARS]) for i in range(0, len(text), MAX_CHARS)]
    chunks: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        article = match.group(1)
        article_text = text[start:end].strip()
        for offset in range(0, len(article_text), MAX_CHARS):
            chunks.append((article, article_text[offset : offset + MAX_CHARS]))
    return chunks


async def ingest_url(url: str) -> int:
    _validate_adilet_url(url)
    settings = get_settings()
    title, text = await asyncio.to_thread(_extract, url)
    chunks = _split_articles(text)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    index = Pinecone(api_key=settings.pinecone_api_key).Index(settings.pinecone_index_name)

    total = 0
    for start in range(0, len(chunks), 50):
        batch = chunks[start : start + 50]
        embedding_response = await client.embeddings.create(model=settings.openai_embedding_model, input=[chunk_text for _, chunk_text in batch])
        vectors = []
        for pos, ((article, chunk_text), embedding) in enumerate(zip(batch, embedding_response.data, strict=True), start=start):
            vector_id = hashlib.sha256(f"{url}|{article}|{pos}".encode("utf-8")).hexdigest()
            vectors.append({
                "id": vector_id,
                "values": embedding.embedding,
                "metadata": {
                    "title": title,
                    "article": f"Статья {article}" if article else "",
                    "url": url,
                    "text": chunk_text,
                    "source_host": "adilet.zan.kz",
                },
            })
        await asyncio.to_thread(index.upsert, vectors=vectors)
        total += len(vectors)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Index an official Adilet legal act")
    parser.add_argument("url", help="https://adilet.zan.kz/... URL")
    args = parser.parse_args()
    count = asyncio.run(ingest_url(args.url))
    print(f"Indexed {count} chunks")


if __name__ == "__main__":
    main()
