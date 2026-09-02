"""Strict Kazakhstan-only retrieval corpus for KORGAN.

The upstream repository is cross-jurisdictional, but KORGAN persists only rows
that are explicitly KZ, Russian-language, and sourced from the official
Kazakhstan Adilet `/rus/docs/` section. Everything else is discarded before any
database write. This corpus is retrieval-only and never upgrades a provision to
VERIFIED by itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from korgan.legal.corpus import LegalCorpus

LOGGER = logging.getLogger(__name__)

UPSTREAM_REPOSITORY = "bobur554396/legal-rag-kz-uz"
UPSTREAM_COMMIT = "499e86c2f2463b8dee7a5fc909097d3e40ba2d8c"
UPSTREAM_SNAPSHOT_DATE = "2026-08-19"
UPSTREAM_CORPUS_URL = (
    "https://raw.githubusercontent.com/bobur554396/legal-rag-kz-uz/"
    f"{UPSTREAM_COMMIT}/data/corpus.jsonl"
)
TARGET_JURISDICTION = "KZ"
TARGET_LANGUAGE = "ru"
TARGET_SOURCE_DOMAIN = "adilet.zan.kz"
AUTOLOAD_ENV = "KORGAN_UPSTREAM_RAG_AUTOLOAD"
DB_ENV = "KORGAN_UPSTREAM_RAG_DB"
MIN_KZ_ROWS = 500
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_FALSEY = {"0", "false", "no", "off"}

DEFAULT_UPSTREAM_DB_PATH = Path(
    os.getenv(DB_ENV)
    or (Path(__file__).resolve().parent.parent / "data" / "legal_rag_kz.sqlite3")
)

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS upstream_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_CODE_TITLES_RU = {
    "Civil Code": "Гражданский кодекс Республики Казахстан",
    "Civil Procedure Code": "Гражданский процессуальный кодекс Республики Казахстан",
    "Labor Code": "Трудовой кодекс Республики Казахстан",
    "Tax Code": "Налоговый кодекс Республики Казахстан",
    "Criminal Code": "Уголовный кодекс Республики Казахстан",
    "Administrative Offences Code": "Кодекс Республики Казахстан об административных правонарушениях",
    "Administrative Procedure Code": "Административный процедурно-процессуальный кодекс Республики Казахстан",
    "Entrepreneurial Code": "Предпринимательский кодекс Республики Казахстан",
    "Health Code": "Кодекс Республики Казахстан о здоровье народа и системе здравоохранения",
}

_ARTICLE_SORT = re.compile(r"^(\d+)(?:[-.]([0-9]+))?")
_ACTIVE_TASK: asyncio.Task[None] | None = None


@dataclass(frozen=True, slots=True)
class UpstreamRagStatus:
    ready: bool
    loading: bool
    rows: int
    path: str
    commit: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "loading": self.loading,
            "rows": self.rows,
            "path": self.path,
            "commit": self.commit,
            "jurisdiction": TARGET_JURISDICTION,
            "language": TARGET_LANGUAGE,
            "mode": "retrieval-candidates-only",
        }


def autoload_enabled() -> bool:
    return os.getenv(AUTOLOAD_ENV, "1").strip().lower() not in _FALSEY


def _database_path(path: Path | str | None = None) -> Path:
    return Path(path or os.getenv(DB_ENV) or DEFAULT_UPSTREAM_DB_PATH)


def _metadata(corpus: LegalCorpus) -> dict[str, str]:
    try:
        rows = corpus.connection.execute("SELECT key, value FROM upstream_meta").fetchall()
    except Exception:
        return {}
    return {str(row["key"]): str(row["value"]) for row in rows}


def _database_is_kz_only(corpus: LegalCorpus) -> bool:
    meta = _metadata(corpus)
    if meta.get("jurisdiction") != TARGET_JURISDICTION:
        return False
    if meta.get("language") != TARGET_LANGUAGE:
        return False
    if meta.get("source_domain") != TARGET_SOURCE_DOMAIN:
        return False
    invalid = corpus.connection.execute(
        """
        SELECT COUNT(*) AS n
        FROM provisions
        WHERE url NOT LIKE 'https://adilet.zan.kz/rus/docs/%'
          AND url NOT LIKE 'https://www.adilet.zan.kz/rus/docs/%'
        """
    ).fetchone()
    return int(invalid["n"] if invalid is not None else 1) == 0


def upstream_rag_status(path: Path | str | None = None) -> UpstreamRagStatus:
    db_path = _database_path(path)
    rows = 0
    ready = False
    if db_path.exists():
        corpus = LegalCorpus(db_path)
        try:
            rows = corpus.count()
            meta = _metadata(corpus)
            ready = rows >= MIN_KZ_ROWS and meta.get("commit") == UPSTREAM_COMMIT and _database_is_kz_only(corpus)
        except Exception:
            LOGGER.exception("KZ-only RAG status check failed")
        finally:
            corpus.close()
    task = _ACTIVE_TASK
    return UpstreamRagStatus(
        ready=ready,
        loading=bool(task is not None and not task.done()),
        rows=rows,
        path=str(db_path),
        commit=UPSTREAM_COMMIT,
    )


def open_upstream_corpus(path: Path | str | None = None) -> LegalCorpus | None:
    status = upstream_rag_status(path)
    if not status.ready:
        return None
    corpus = LegalCorpus(_database_path(path))
    try:
        if corpus.count() < MIN_KZ_ROWS or not _database_is_kz_only(corpus):
            corpus.close()
            return None
    except Exception:
        corpus.close()
        return None
    return corpus


def _allowed_upstream_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "raw.githubusercontent.com"
        and parsed.path == f"/bobur554396/legal-rag-kz-uz/{UPSTREAM_COMMIT}/data/corpus.jsonl"
        and not parsed.query
        and not parsed.fragment
    )


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not _allowed_upstream_url(newurl):
            raise RuntimeError(f"upstream RAG redirect rejected: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_upstream(timeout: int = 90):
    if not _allowed_upstream_url(UPSTREAM_CORPUS_URL):
        raise RuntimeError("pinned upstream corpus URL failed allowlist validation")
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _PinnedRedirectHandler(),
    )
    request = urllib.request.Request(
        UPSTREAM_CORPUS_URL,
        headers={
            "User-Agent": "KORGAN-legal-rag-kz/1.1",
            "Accept": "application/x-ndjson,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    response = opener.open(request, timeout=timeout)  # noqa: S310 - exact pinned host/path
    if not _allowed_upstream_url(response.geturl()):
        response.close()
        raise RuntimeError("unexpected upstream final URL")
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            if int(declared) > MAX_DOWNLOAD_BYTES:
                response.close()
                raise RuntimeError("upstream corpus exceeds size limit")
        except ValueError:
            response.close()
            raise RuntimeError("invalid upstream Content-Length") from None
    return response


def _official_kz_url(value: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.hostname not in {TARGET_SOURCE_DOMAIN, f"www.{TARGET_SOURCE_DOMAIN}"}:
        return ""
    if not parsed.path.startswith("/rus/docs/"):
        return ""
    return text


def _act_id(code_id: str) -> str:
    return "RAGKZ_" + hashlib.sha256(code_id.encode("utf-8", errors="replace")).hexdigest()[:16]


def _sort_key(article_no: str) -> int:
    match = _ARTICLE_SORT.match(article_no)
    if not match:
        return 2_000_000_000
    return int(match.group(1)) * 10_000 + int(match.group(2) or 0)


def _write_row(connection, row: dict[str, object], *, loaded_at: str) -> bool:
    if str(row.get("jurisdiction") or "").strip().upper() != TARGET_JURISDICTION:
        return False
    if str(row.get("lang") or "").strip().lower() not in {"ru", "rus", "russian"}:
        return False
    url = _official_kz_url(str(row.get("url") or ""))
    if not url:
        return False
    article_no = str(row.get("article_no") or "").strip()
    body = " ".join(str(row.get("text") or "").split()).strip()
    if not article_no or not body:
        return False

    code_id = str(row.get("code_id") or "").strip() or "unknown-kz-act"
    code_name = str(row.get("code_name") or "").strip()
    act_id = _act_id(code_id)
    title = _CODE_TITLES_RU.get(code_name) or code_name or code_id
    article_id = f"{act_id}:{article_no}"
    heading = " ".join(str(row.get("article_title") or "").split()).strip()

    connection.execute(
        """
        INSERT INTO acts(act_id, adilet_id, title_ru, url, edition_date, loaded_at, lang)
        VALUES(?,?,?,?,?,?,'ru')
        ON CONFLICT(act_id) DO UPDATE SET
            adilet_id=excluded.adilet_id,
            title_ru=excluded.title_ru,
            url=excluded.url,
            edition_date=excluded.edition_date,
            loaded_at=excluded.loaded_at
        """,
        (act_id, code_id, title, url, UPSTREAM_SNAPSHOT_DATE, loaded_at),
    )
    connection.execute(
        """
        INSERT INTO provisions(article_id, act_id, article_no, item_no, heading, body, edition_date, url, sort_key)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(article_id) DO UPDATE SET
            heading=excluded.heading,
            body=excluded.body,
            edition_date=excluded.edition_date,
            url=excluded.url,
            sort_key=excluded.sort_key
        """,
        (article_id, act_id, article_no, None, heading, body, UPSTREAM_SNAPSHOT_DATE, url, _sort_key(article_no)),
    )
    return True


def sync_upstream_rag(*, path: Path | str | None = None, force: bool = False) -> UpstreamRagStatus:
    target = _database_path(path)
    current = upstream_rag_status(target)
    if current.ready and not force:
        return current

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    loaded_at = date.today().isoformat()
    total_bytes = 0
    written = 0

    try:
        with LegalCorpus(temporary) as corpus:
            connection = corpus.connection
            connection.executescript(_META_SCHEMA)
            connection.execute("BEGIN")
            with _open_upstream() as response:
                stream = io.TextIOWrapper(response, encoding="utf-8", errors="strict", newline="")
                for line_no, line in enumerate(stream, start=1):
                    total_bytes += len(line.encode("utf-8"))
                    if total_bytes > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("upstream corpus exceeded streaming size limit")
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"invalid JSONL at line {line_no}: {exc}") from exc
                    if isinstance(row, dict) and _write_row(connection, row, loaded_at=loaded_at):
                        written += 1

            if written < MIN_KZ_ROWS:
                raise RuntimeError(f"KZ-only corpus too small: {written}")
            connection.executemany(
                "INSERT OR REPLACE INTO upstream_meta(key,value) VALUES(?,?)",
                (
                    ("repository", UPSTREAM_REPOSITORY),
                    ("commit", UPSTREAM_COMMIT),
                    ("snapshot_date", UPSTREAM_SNAPSHOT_DATE),
                    ("loaded_at", loaded_at),
                    ("rows", str(written)),
                    ("jurisdiction", TARGET_JURISDICTION),
                    ("language", TARGET_LANGUAGE),
                    ("source_domain", TARGET_SOURCE_DOMAIN),
                    ("filter_mode", "strict-kz-only"),
                ),
            )
            connection.commit()
            if not _database_is_kz_only(corpus):
                raise RuntimeError("KZ-only invariant failed")

        os.replace(temporary, target)
        LOGGER.info("UPSTREAM_KZ_ONLY_RAG_SYNC_SUCCESS rows=%d bytes=%d path=%s", written, total_bytes, target)
        return upstream_rag_status(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        LOGGER.exception("UPSTREAM_KZ_ONLY_RAG_SYNC_FAILED existing corpus remains active")
        raise


async def _sync_once() -> None:
    try:
        await asyncio.to_thread(sync_upstream_rag)
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("KZ-only RAG bootstrap failed safely; source-bound research remains active")


def start_upstream_rag_task() -> asyncio.Task[None] | None:
    global _ACTIVE_TASK
    if not autoload_enabled():
        LOGGER.info("KZ-only RAG autoload disabled")
        return None
    if _ACTIVE_TASK is not None and not _ACTIVE_TASK.done():
        return _ACTIVE_TASK
    _ACTIVE_TASK = asyncio.create_task(_sync_once(), name="korgan-upstream-kz-rag")
    return _ACTIVE_TASK
