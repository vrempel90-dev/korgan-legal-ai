"""Local corpus of Kazakhstan provisions, backed by SQLite + FTS5.

The corpus is intentionally article/point based.  KORGAN never treats a vector
or text-search hit as authority by itself: retrieved provisions are candidates
for the existing source-bound verification and final citation audit.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from korgan.legal.rk_catalog import ACT_SHORT_TITLES, KNOWN_ACTS

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "corpus.sqlite3"

# Backward-compatible IDs imported throughout the production quality layer.
ACT_GK_GENERAL = "GK_RK_OBSHAYA"
ACT_GK_SPECIAL = "GK_RK_OSOBENNAYA"
ACT_GPK = "GPK_RK"
ACT_TAX_DUTY = "NK_RK_GOSPOSHLINA"
ACT_CONSUMER = "ZPP_RK"
ACT_LABOR = "TK_RK"

SCHEMA = """
CREATE TABLE IF NOT EXISTS acts (
    act_id       TEXT PRIMARY KEY,
    adilet_id    TEXT NOT NULL,
    title_ru     TEXT NOT NULL,
    url          TEXT NOT NULL,
    edition_date TEXT NOT NULL,
    loaded_at    TEXT NOT NULL,
    lang         TEXT NOT NULL CHECK (lang = 'ru')
);

CREATE TABLE IF NOT EXISTS provisions (
    rowid        INTEGER PRIMARY KEY,
    article_id   TEXT NOT NULL UNIQUE,
    act_id       TEXT NOT NULL REFERENCES acts(act_id) ON DELETE CASCADE,
    article_no   TEXT NOT NULL,
    item_no      TEXT,
    heading      TEXT NOT NULL,
    body         TEXT NOT NULL,
    edition_date TEXT NOT NULL,
    url          TEXT NOT NULL,
    sort_key     INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS provisions_act_idx ON provisions(act_id, sort_key);

CREATE VIRTUAL TABLE IF NOT EXISTS provisions_fts USING fts5(
    heading,
    body,
    content='provisions',
    content_rowid='rowid',
    prefix='2 3 4',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS provisions_ai AFTER INSERT ON provisions BEGIN
    INSERT INTO provisions_fts(rowid, heading, body) VALUES (new.rowid, new.heading, new.body);
END;

CREATE TRIGGER IF NOT EXISTS provisions_ad AFTER DELETE ON provisions BEGIN
    INSERT INTO provisions_fts(provisions_fts, rowid, heading, body)
    VALUES ('delete', old.rowid, old.heading, old.body);
END;

CREATE TRIGGER IF NOT EXISTS provisions_au AFTER UPDATE ON provisions BEGIN
    INSERT INTO provisions_fts(provisions_fts, rowid, heading, body)
    VALUES ('delete', old.rowid, old.heading, old.body);
    INSERT INTO provisions_fts(rowid, heading, body) VALUES (new.rowid, new.heading, new.body);
END;
"""

_WORD = re.compile(r"[0-9a-zа-яёA-ZА-ЯЁ]+")


@dataclass(frozen=True, slots=True)
class Provision:
    article_id: str
    act_id: str
    act_title: str
    article_no: str
    item_no: str | None
    heading: str
    body: str
    edition_date: str
    url: str

    def label(self) -> str:
        base = f"ст. {self.article_no} {ACT_SHORT_TITLES.get(self.act_id, self.act_title)}"
        return f"{base}, п. {self.item_no}" if self.item_no else base


def make_article_id(act_id: str, article_no: str, item_no: str | None = None) -> str:
    suffix = f":{item_no}" if item_no else ""
    return f"{act_id}:{article_no}{suffix}"


def compile_query(text: str) -> str:
    """Build a conservative Russian/Kazakh-friendly FTS prefix query."""
    terms: list[str] = []
    for word in _WORD.findall(text.lower()):
        if len(word) >= 7:
            stem = word[:-2]
        elif len(word) >= 5:
            stem = word[:-1]
        else:
            stem = word
        term = f"{stem}*"
        if term not in terms:
            terms.append(term)
    return " OR ".join(terms)


class LegalCorpus:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            if str(self.path) != ":memory:":
                self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
        return self._connection

    def create_schema(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "LegalCorpus":
        self.create_schema()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert_act(self, act_id: str, adilet_id: str, title_ru: str, url: str, edition_date: str, loaded_at: str) -> None:
        self.connection.execute(
            """
            INSERT INTO acts (act_id, adilet_id, title_ru, url, edition_date, loaded_at, lang)
            VALUES (?, ?, ?, ?, ?, ?, 'ru')
            ON CONFLICT(act_id) DO UPDATE SET
                adilet_id = excluded.adilet_id,
                title_ru = excluded.title_ru,
                url = excluded.url,
                edition_date = excluded.edition_date,
                loaded_at = excluded.loaded_at
            """,
            (act_id, adilet_id, title_ru, url, edition_date, loaded_at),
        )
        self.connection.commit()

    def upsert_provision(self, *, act_id: str, article_no: str, item_no: str | None, heading: str, body: str, edition_date: str, url: str, sort_key: int) -> str:
        article_id = make_article_id(act_id, article_no, item_no)
        self.connection.execute(
            """
            INSERT INTO provisions
                (article_id, act_id, article_no, item_no, heading, body, edition_date, url, sort_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                heading = excluded.heading,
                body = excluded.body,
                edition_date = excluded.edition_date,
                url = excluded.url,
                sort_key = excluded.sort_key
            """,
            (article_id, act_id, article_no, item_no, heading, body, edition_date, url, sort_key),
        )
        self.connection.commit()
        return article_id

    def clear_act(self, act_id: str) -> None:
        self.connection.execute("DELETE FROM provisions WHERE act_id = ?", (act_id,))
        self.connection.commit()

    def _row_to_provision(self, row: sqlite3.Row) -> Provision:
        return Provision(
            article_id=row["article_id"],
            act_id=row["act_id"],
            act_title=row["act_title"],
            article_no=row["article_no"],
            item_no=row["item_no"],
            heading=row["heading"],
            body=row["body"],
            edition_date=row["edition_date"],
            url=row["url"],
        )

    def search(self, query: str, act_id: str | None = None, limit: int = 20) -> list[Provision]:
        return self.search_many(query, [act_id] if act_id else None, limit=limit)

    def search_many(self, query: str, act_ids: Iterable[str] | None = None, *, limit: int = 20) -> list[Provision]:
        """Search globally or inside a routed set of Kazakhstan acts.

        Filtering before BM25 ranking keeps an employment query from being
        crowded out by semantically similar wording in unrelated codes.
        """
        compiled = compile_query(query)
        if not compiled:
            return []

        selected = [item for item in dict.fromkeys(act_ids or ()) if item in KNOWN_ACTS]
        sql = """
            SELECT p.article_id, p.act_id, a.title_ru AS act_title, p.article_no, p.item_no,
                   p.heading, p.body, p.edition_date, p.url
            FROM provisions_fts
            JOIN provisions p ON p.rowid = provisions_fts.rowid
            JOIN acts a ON a.act_id = p.act_id
            WHERE provisions_fts MATCH ?
        """
        params: list[object] = [compiled]
        if selected:
            placeholders = ",".join("?" for _ in selected)
            sql += f" AND p.act_id IN ({placeholders})"
            params.extend(selected)
        sql += " ORDER BY bm25(provisions_fts, 2.0, 1.0) LIMIT ?"
        params.append(limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [self._row_to_provision(row) for row in rows]

    def get(self, article_id: str) -> Provision | None:
        row = self.connection.execute(
            """
            SELECT p.article_id, p.act_id, a.title_ru AS act_title, p.article_no, p.item_no,
                   p.heading, p.body, p.edition_date, p.url
            FROM provisions p
            JOIN acts a ON a.act_id = p.act_id
            WHERE p.article_id = ?
            """,
            (article_id,),
        ).fetchone()
        return self._row_to_provision(row) if row else None

    def get_article(self, act_id: str, article_no: str) -> list[Provision]:
        rows = self.connection.execute(
            """
            SELECT p.article_id, p.act_id, a.title_ru AS act_title, p.article_no, p.item_no,
                   p.heading, p.body, p.edition_date, p.url
            FROM provisions p
            JOIN acts a ON a.act_id = p.act_id
            WHERE p.act_id = ? AND p.article_no = ?
            ORDER BY p.sort_key
            """,
            (act_id, str(article_no)),
        ).fetchall()
        return [self._row_to_provision(row) for row in rows]

    def exists(self, article_id: str) -> bool:
        row = self.connection.execute("SELECT 1 FROM provisions WHERE article_id = ?", (article_id,)).fetchone()
        return row is not None

    def count(self, act_id: str | None = None) -> int:
        if act_id:
            row = self.connection.execute("SELECT COUNT(*) AS n FROM provisions WHERE act_id = ?", (act_id,)).fetchone()
        else:
            row = self.connection.execute("SELECT COUNT(*) AS n FROM provisions").fetchone()
        return int(row["n"])
