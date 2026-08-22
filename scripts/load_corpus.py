#!/usr/bin/env python3
"""Load Kazakhstan acts from official Ministry of Justice sources.

Adilet remains the normal source. The runtime refresh may also pass text
extracted from the official ZAN.GOV.KZ electronic reference bank when Adilet is
unreachable. Both source families are strict HTTPS allowlists and only Russian
editions are accepted.

Network access is required only for the CLI's direct Adilet fetch. Parsing and
validation are pure functions covered by tests against saved fixtures.

    python scripts/load_corpus.py --all
    python scripts/load_corpus.py --act GK_RK_OBSHAYA
    python scripts/load_corpus.py --act GPK_RK --from-file dump.html --edition-date 2026-01-01
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.corpus import (  # noqa: E402
    DEFAULT_DB_PATH,
    KNOWN_ACTS,
    LegalCorpus,
)
from korgan.legal.official_sources import (  # noqa: E402
    ADILET_HOSTS,
    ZAN_HOSTS,
    is_allowed_adilet_url,
    is_allowed_zan_pdf_url,
    official_source_kind,
)

ADILET_HOST = "adilet.zan.kz"
RUSSIAN_PATH = "/rus/"
MIN_CYRILLIC_SHARE = 0.5

_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_ARTICLE_HEAD = re.compile(r"Статья\s+(\d+(?:-\d+)?)\.\s*([^\n]*)")
_ITEM_HEAD = re.compile(r"^\s*(\d+(?:-\d+)?)\.\s+(?=\S)", re.MULTILINE)
_WHITESPACE = re.compile(r"[ \t\xa0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class SourceRejected(RuntimeError):
    """The document is not an acceptable official source for the corpus."""


@dataclass(frozen=True, slots=True)
class ParsedProvision:
    article_no: str
    item_no: str | None
    heading: str
    body: str
    sort_key: int


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text pass; Adilet pages are plain enough not to need more."""

    _SKIP = {"script", "style", "head", "noscript"}
    _BREAK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAK:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.chunks)
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES.sub("\n\n", text).strip()


def cyrillic_share(text: str) -> float:
    letters = _LETTER.findall(text)
    if not letters:
        return 0.0
    return len(_CYRILLIC.findall(text)) / len(letters)


def check_source(url: str, text: str, *, act_id: str | None = None) -> None:
    """Reject non-official sources and bind official document identity when known."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        host = ""
        parsed = None
    if parsed is not None and host in (ADILET_HOSTS | ZAN_HOSTS) and "/rus/" not in parsed.path:
        # Preserve the long-standing error contract used by callers/tests.
        raise SourceRejected(f"не русская редакция URL: {url}")

    source_kind = official_source_kind(url)
    if source_kind is None:
        raise SourceRejected(f"источник не adilet.zan.kz и не zan.gov.kz: {url}")

    if act_id is not None:
        if source_kind == "adilet" and not is_allowed_adilet_url(url, act_id=act_id):
            raise SourceRejected(f"Adilet URL не соответствует акту {act_id}: {url}")
        if source_kind == "zan" and not is_allowed_zan_pdf_url(url, act_id=act_id):
            raise SourceRejected(f"ZAN URL не соответствует акту {act_id}: {url}")

    share = cyrillic_share(text)
    if share < MIN_CYRILLIC_SHARE:
        raise SourceRejected(
            f"текст не похож на русскую редакцию: доля кириллицы {share:.0%} < {MIN_CYRILLIC_SHARE:.0%}"
        )
    if not _ARTICLE_HEAD.search(text):
        raise SourceRejected("в тексте не найдено ни одной «Статья N.» — страница не является актом")


def _split_items(body: str) -> list[tuple[str | None, str]]:
    """Split an article into пункты; a single-part article stays whole."""
    matches = list(_ITEM_HEAD.finditer(body))
    if len(matches) < 2:
        return [(None, body.strip())]

    items: list[tuple[str | None, str]] = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        items.append((None, preamble))

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[match.end() : end].strip()
        if text:
            items.append((match.group(1), text))
    return items


def parse_provisions(text: str, articles: set[str] | None = None) -> list[ParsedProvision]:
    """Split act text into articles and пункты.

    ``articles`` limits the result to the listed article numbers — the Tax Code
    is loaded only for the court-duty articles, not in full.
    """
    heads = list(_ARTICLE_HEAD.finditer(text))
    provisions: list[ParsedProvision] = []
    sort_key = 0

    for index, head in enumerate(heads):
        article_no = head.group(1)
        if articles is not None and article_no not in articles:
            continue

        heading = head.group(2).strip()
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        body = text[head.end() : end].strip()

        for item_no, item_text in _split_items(body):
            if not item_text:
                continue
            provisions.append(
                ParsedProvision(
                    article_no=article_no,
                    item_no=item_no,
                    heading=heading,
                    body=item_text,
                    sort_key=sort_key,
                )
            )
            sort_key += 1

    return provisions


def act_url(act_id: str) -> str:
    adilet_id, _ = KNOWN_ACTS[act_id]
    return f"https://{ADILET_HOST}{RUSSIAN_PATH}docs/{adilet_id}"


def fetch(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - CLI only; source checked after fetch
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def load_act_text(
    corpus: LegalCorpus,
    act_id: str,
    text: str,
    *,
    source_url: str,
    citation_url: str | None = None,
    edition_date: str | None = None,
    articles: set[str] | None = None,
) -> int:
    """Validate already-extracted official text and replace one act in the temp corpus.

    ``source_url`` records where the refresh bytes actually came from. For ZAN
    fallback refreshes, ``citation_url`` may remain the stable canonical Adilet
    act URL used in filing-facing citations; the act row still records ZAN as
    refresh provenance.
    """
    if act_id not in KNOWN_ACTS:
        raise SourceRejected(f"акт {act_id} не входит в список загружаемых")

    adilet_id, title = KNOWN_ACTS[act_id]
    check_source(source_url, text, act_id=act_id)
    if citation_url is not None and not (
        is_allowed_adilet_url(citation_url, act_id=act_id)
        or is_allowed_zan_pdf_url(citation_url, act_id=act_id)
    ):
        raise SourceRejected(f"citation URL не соответствует акту {act_id}: {citation_url}")

    provisions = parse_provisions(text, articles)
    if not provisions:
        raise SourceRejected(f"в документе {act_id} не найдено статей для загрузки")

    today = date.today().isoformat()
    verified_on = edition_date or today
    corpus.upsert_act(
        act_id=act_id,
        adilet_id=adilet_id,
        title_ru=title,
        url=source_url,
        edition_date=verified_on,
        loaded_at=today,
    )
    corpus.clear_act(act_id)

    base_citation_url = citation_url or source_url
    for provision in provisions:
        corpus.upsert_provision(
            act_id=act_id,
            article_no=provision.article_no,
            item_no=provision.item_no,
            heading=provision.heading,
            body=provision.body,
            edition_date=verified_on,
            url=f"{base_citation_url}#z{provision.article_no}",
            sort_key=provision.sort_key,
        )
    return len(provisions)


def load_act(
    corpus: LegalCorpus,
    act_id: str,
    html: str,
    *,
    url: str | None = None,
    edition_date: str | None = None,
    articles: set[str] | None = None,
) -> int:
    """Parse one official Adilet HTML act and replace its provisions in the corpus."""
    if act_id not in KNOWN_ACTS:
        raise SourceRejected(f"акт {act_id} не входит в список загружаемых")
    source_url = url or act_url(act_id)
    return load_act_text(
        corpus,
        act_id,
        strip_html(html),
        source_url=source_url,
        citation_url=source_url,
        edition_date=edition_date,
        articles=articles,
    )


# Only the court-duty part of the Tax Code is in scope.
TAX_DUTY_ARTICLES = {"665", "666", "667", "668", "669"}

ACT_ARTICLE_FILTER: dict[str, set[str]] = {"NK_RK_GOSPOSHLINA": TAX_DUTY_ARTICLES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Загрузка норм РК с adilet.zan.kz в локальный корпус")
    parser.add_argument("--act", action="append", choices=sorted(KNOWN_ACTS), help="какой акт загрузить")
    parser.add_argument("--all", action="store_true", help="загрузить все поддерживаемые акты")
    parser.add_argument("--from-file", type=Path, help="читать HTML из файла вместо сети (для одного акта)")
    parser.add_argument("--edition-date", help="редакция на дату, ISO; по умолчанию сегодняшняя")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="путь к файлу базы")
    args = parser.parse_args(argv)

    act_ids = sorted(KNOWN_ACTS) if args.all else (args.act or [])
    if not act_ids:
        parser.error("укажите --act или --all")
    if args.from_file and len(act_ids) != 1:
        parser.error("--from-file работает только с одним --act")

    total = 0
    with LegalCorpus(args.db) as corpus:
        for act_id in act_ids:
            url = act_url(act_id)
            html = args.from_file.read_text(encoding="utf-8") if args.from_file else fetch(url)
            try:
                loaded = load_act(
                    corpus,
                    act_id,
                    html,
                    url=url,
                    edition_date=args.edition_date,
                    articles=ACT_ARTICLE_FILTER.get(act_id),
                )
            except SourceRejected as exc:
                print(f"ОТКАЗ {act_id}: {exc}", file=sys.stderr)
                return 1
            print(f"{act_id}: загружено норм — {loaded}")
            total += loaded

    print(f"Всего норм в базе: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
