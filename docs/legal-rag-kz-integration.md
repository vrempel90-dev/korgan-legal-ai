# KORGAN Kazakhstan Legal RAG

KORGAN uses two separate local legal corpora.

## 1. Official current corpus

`korgan/data/corpus.sqlite3` is built from the official Kazakhstan sources already supported by KORGAN (Adilet, with ZAN.GOV.KZ fallback). This corpus participates in freshness and filing-safety checks.

## 2. Broad retrieval-only corpus

`korgan/data/legal_rag_kz.sqlite3` is seeded from:

- upstream repository: `bobur554396/legal-rag-kz-uz`
- pinned commit: `499e86c2f2463b8dee7a5fc909097d3e40ba2d8c`
- source file: `data/corpus.jsonl`
- upstream license: MIT

Only Kazakhstan Russian-language rows are imported. Uzbekistan rows and non-Russian rows are discarded.

This second database is **candidate-only**. Its article ids are intentionally rewritten to the isolated `RAGKZ_*` namespace, so they cannot be mistaken for KORGAN's official-current act ids. A row from this database can help the research prompt discover a relevant statute, but it cannot by itself make a legal proposition `VERIFIED` or filing-ready. Final legal conclusions still require KORGAN's source-bound verification against the current official source.

The upstream project reports fine-tuned BGE-M3 retrieval results, but it does not ship its fine-tuned weights or dense index in Git. KORGAN therefore does not make the production Railway runtime depend on unavailable model artifacts or GPU inference. The published article corpus is loaded into SQLite/FTS5 and fused with KORGAN's official corpus. Dense retrieval can be added later as an optional accelerator without changing the verification boundary.

## Runtime

The active Mini App recovery ASGI app installs `korgan.legal.rag_runtime` as a lifespan layer. It starts two non-blocking jobs:

1. official Adilet/ZAN corpus refresh;
2. pinned broad KZ corpus bootstrap.

Legal generation does not fail if either background sync is temporarily unavailable: source-bound research remains the fail-safe fallback.

Recommended Railway variables:

```text
KORGAN_LOCAL_CORPUS=1
KORGAN_CORPUS_AUTOLOAD=1
KORGAN_CORPUS_REFRESH_HOURS=24
KORGAN_UPSTREAM_RAG_AUTOLOAD=1
```

If a persistent Railway volume is mounted at `/data`, also set:

```text
KORGAN_CORPUS_DB=/data/corpus.sqlite3
KORGAN_UPSTREAM_RAG_DB=/data/legal_rag_kz.sqlite3
```

Without a volume, both databases are rebuilt after a container replacement. The application remains functional during rebuilding because official web research is still available.

## Manual sync

```bash
python scripts/sync_legal_rag_kz.py --force
```

The importer is atomic: a new database is built in a temporary path and replaces the live retrieval database only after the pinned corpus passes minimum-size and JSONL validation.
