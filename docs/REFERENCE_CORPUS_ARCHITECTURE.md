# Reference corpus: storage and privacy architecture

KORGAN's house style is derived from real claims the firm filed in Kazakhstan courts. Those
documents contain client personal data — ИИН, БИН, names, addresses, phone numbers — belonging to
parties in actual cases, not to the operator of this system.

The code repository and the client corpus therefore have **different lifecycles and different
access rights**, and they are never stored together.

## What lives where

| Artefact | Location | Contains PII |
|---|---|---|
| Raw filed claims (`.docx`, converted `.md`) | private corpus store, outside this repository | yes |
| `DOCUMENT_MAP.private.yaml` (`document_id` → file) | private corpus store | yes (file names identify parties) |
| Full `STYLE_GUIDE.md` with verbatim excerpts | private corpus store | yes |
| `house_style/rules.vN.json` | this repository | no |
| `house_style/provenance.vN.json` | this repository | no |
| Synthetic fixtures (`tests/fixtures/`) | this repository | no — invented parties |

The repository being private is **not** what makes this safe. Visibility can change; a repository
that once held personal data holds it in history forever. The boundary is what gets written, not
who can currently read it.

## Identity and versioning

Every corpus document carries:

- `document_id` — an opaque handle (`kzc-07`) that says nothing about the parties;
- `sha256` — content hash, so a document can be verified or detected as changed;
- `corpus_version` — the corpus revision the document belonged to.

Only `document_id`, `dispute_type`, `sha256` and `corpus_version` cross into this repository. The
mapping back to a real filed claim exists solely in the private store.

## Provenance

`provenance.vN.json` records, for each style rule, the `document_id`s it was derived from. Any rule
can be traced to its evidence without exposing the evidence itself, and
`load_rules()` / `load_provenance()` are pinned by version so a generated document remains
reproducible against the rule set that produced it.

## Withdrawing a document

A client may require their filed claim to be removed. `CorpusProvenance.without_document()` models
the rebuild:

1. delete the raw document from the private store;
2. remove its entry from `DOCUMENT_MAP.private.yaml`;
3. rebuild `provenance.vN+1.json` and `rules.vN+1.json`;
4. rules whose only source was the withdrawn document **disappear** rather than surviving as
   unattributable rules;
5. publish the new version and pin the application to it.

`orphaned_rules()` reports exactly which rules were lost, so the change is reviewable.

## PII must not leak sideways

- **Logs**: never log corpus content or a resolved file name. Application logs record exception
  types, not payloads (see `docs/TELEGRAM_RUNTIME.md` for the same rule on client case text).
- **CI artifacts**: test output, junit XML and uploaded diagnostics are built only from synthetic
  fixtures, so a failing assertion cannot print client data.
- **Fixtures**: invented parties only. Never seed a test from a real claim, even redacted —
  redaction is not a guarantee and drifts over time.
- **Model context**: raw documents are not sent to a model at request time. Rule extraction is an
  offline process against the private store; production reads `rules.vN.json` only.

## Production default

The application runs on PII-free derived rules. There is no runtime code path that reads the raw
corpus, and none should be added: if a new rule is needed, it is extracted offline and shipped as a
new rule-set version.

## House style is not a source of law

The layer separation this architecture protects:

| Layer | Owns |
|---|---|
| Fact Lock | facts and party roles |
| Legal RAG / verified corpus | which norms apply and in which effective wording |
| Deterministic calculation layer | amounts, state duty, deadlines |
| House style | presentation only |

`HouseStyleRule.is_legal_authority` is a constant `False`. A pattern observed in every corpus
document is a drafting habit, never evidence that a norm applies to a new case, and style can never
promote `NEEDS_VERIFICATION` to `VERIFIED`.
