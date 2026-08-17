#!/usr/bin/env python3
"""Load Kazakhstan acts from adilet.zan.kz into the local article corpus.

Only the official Russian Adilet edition is accepted.  The parser keeps the
article as the legal retrieval unit and strips amendment-history footnotes so
RAG candidates contain operative text rather than publication noise.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from korgan.legal.corpus import DEFAULT_DB_PATH, KNOWN_ACTS, LegalCorpus  # noqa: E402
from korgan.legal.rk_catalog import CORE_ACT_IDS  # noqa: E402

ADILET_HOST = "adilet.zan.kz"
RUSSIAN_PATH = "/rus/"
MIN_CYRILLIC_SHARE = 0.5

_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_ARTICLE_HEAD = re.compile(r"Статья\s+(\d+(?:-\d+)?)\.\s*([^\n]*)")
_ITEM_HEAD = re.compile(r"^\s*(\d+(?:-\d+)?)\.\s+(?=\S)", re.MULTILINE)
_WHITESPACE = re.compile(r"[ \t\xa0]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_FOOTNOTE = re.compile(r"^\s*Сноска\.\s*", re.IGNORECASE)
_REPEALED_HEADER_LINE = re.compile(
    r"(?im)^\s*(?:Утративший\s+силу|[^\n]{0,220}\b(?:Закон|Кодекс|Конституция|акт)\b[^\n]{0,120}\bутратил(?:а|о)?\s+силу\b)"
)


class SourceRejected(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedProvision:
    article_no: str
    item_no: str | None
    heading: str
    body: str
    sort_key: int


class _TextExtractor(HTMLParser):
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
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        # Adilet places amendment history in paragraphs beginning with «Сноска.».
        # It is useful provenance for a human reader but noise for retrieval.
        if _FOOTNOTE.match(line):
            continue
        lines.append(line)
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def cyrillic_share(text: str) -> float:
    letters = _LETTER.findall(text)
    if not letters:
        return 0.0
    return len(_CYRILLIC.findall(text)) / len(letters)


def check_source(url: str, text: str) -> None:
    if ADILET_HOST not in url:
        raise SourceRejected(f"источник не adilet.zan.kz: {url}")
    if RUSSIAN_PATH not in url:
        raise SourceRejected(f"не русская редакция по URL (ожидается {RUSSIAN_PATH}): {url}")
    share = cyrillic_share(text)
    if share < MIN_CYRILLIC_SHARE:
        raise SourceRejected(
            f"текст не похож на русскую редакцию: доля кириллицы {share:.0%} < {MIN_CYRILLIC_SHARE:.0%}"
        )

    article_match = _ARTICLE_HEAD.search(text)
    if article_match is None:
        raise SourceRejected("в тексте не найдено ни одной «Статья N.» — страница не является актом")

    # Status/title live before the first normative article.  Looking only at
    # that header avoids false positives from historical footnotes inside a
    # current act while still rejecting an Adilet page explicitly marked as
    # repealed.  Transitional remnants are intentionally not cached locally;
    # the source-bound web layer may still verify a specific surviving rule.
    header = text[: article_match.start()]
    if _REPEALED_HEADER_LINE.search(header):
        raise SourceRejected("Adilet помечает акт как утративший силу — локальный RAG его не принимает")


def _split_items(body: str) -> list[tuple[str | None, str]]:
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
    request = urllib.request.Request(url, headers={"User-Agent": "KORGAN-corpus-loader/1.3"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - allowlisted Adilet only
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def load_act(
    corpus: LegalCorpus,
    act_id: str,
    html: str,
    *,
    url: str | None = None,
    edition_date: str | None = None,
    articles: set[str] | None = None,
) -> int:
    if act_id not in KNOWN_ACTS:
        raise SourceRejected(f"акт {act_id} не входит в список загружаемых")
    adilet_id, title = KNOWN_ACTS[act_id]
    source_url = url or act_url(act_id)
    text = strip_html(html)
    check_source(source_url, text)
    provisions = parse_provisions(text, articles)
    if not provisions:
        raise SourceRejected(f"в документе {act_id} не найдено статей для загрузки")

    today = date.today().isoformat()
    corpus.upsert_act(
        act_id=act_id,
        adilet_id=adilet_id,
        title_ru=title,
        url=source_url,
        edition_date=edition_date or today,
        loaded_at=today,
    )
    corpus.clear_act(act_id)
    for provision in provisions:
        corpus.upsert_provision(
            act_id=act_id,
            article_no=provision.article_no,
            item_no=provision.item_no,
            heading=provision.heading,
            body=provision.body,
            edition_date=edition_date or today,
            url=f"{source_url}#z{provision.article_no}",
            sort_key=provision.sort_key,
        )
    return len(provisions)


# The 2025 Tax Code is large; court-duty provisions are the deterministic scope
# required by claim generation.  Other tax questions still use source-bound web.
TAX_DUTY_ARTICLES = {"665", "666", "667", "668", "669"}
ACT_ARTICLE_FILTER: dict[str, set[str]] = {"NK_RK_GOSPOSHLINA": TAX_DUTY_ARTICLES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Загрузка норм РК с adilet.zan.kz в локальный корпус")
    parser.add_argument("--act", action="append", choices=sorted(KNOWN_ACTS), help="какой акт загрузить")
    parser.add_argument("--all", action="store_true", help="загрузить весь поддерживаемый каталог")
    parser.add_argument("--core", action="store_true", help="загрузить только обязательное production-ядро")
    parser.add_argument("--from-file", type=Path, help="читать HTML из файла вместо сети (для одного акта)")
    parser.add_argument("--edition-date", help="редакция на дату, ISO; по умолчанию сегодняшняя")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="путь к файлу базы")
    args = parser.parse_args(argv)

    if args.all:
        act_ids = sorted(KNOWN_ACTS)
    elif args.core:
        act_ids = sorted(CORE_ACT_IDS)
    else:
        act_ids = args.act or []
    if not act_ids:
        parser.error("укажите --act, --core или --all")
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
