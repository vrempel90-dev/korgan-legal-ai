# Architecture

## Two ways in, one pipeline

A request reaches the legal pipeline by one of two routes:

1. **Free text** — the user describes the case in prose. Fact Lock extracts the facts, grounding
   validation rejects anything not present in the source text, and the Task Router picks the
   document type.
2. **Guided dialogue** — the user picks a document type and answers one validated question at a
   time. Answers are parsed by deterministic code and assembled into the locked case directly, so
   no model participates in producing the facts, and completeness is checked before drafting starts.

From that point the stages are identical:

1. **Evidence Map** — links material facts to the documents the user actually has.
2. **Calculation Layer** — deterministic arithmetic for money and periods.
3. **Legal Research & Citation Gateway** — the only path by which an exact legal reference may
   become `VERIFIED`.
4. **Procedural Check** — jurisdiction, pre-trial procedure, limitation, state duty, authority and
   attachments, restricted to the checks that apply to the document being produced.
5. **Judicial practice** — optional supporting decisions from the reviewed practice corpus.
6. **Drafting Engine** — renders the document section by section from its blueprint.
7. **House-style review** — presentation-only feedback against the derived KORGAN rules.
8. **Final Legal QA** — fail-closed policy gate before output.
9. **Output Contract** — document, verification queue, readiness status and summary.

## Document blueprints

A `DocumentBlueprint` describes one document type as data: its sections and their order, how the
two sides are labelled, whether it claims money, which procedural checks apply, the closing demands
and the interview questions that collect its facts.

The drafter, Final Legal QA, the Word exporter and the Telegram dialogue all read the same
blueprint. Supporting a new category of case is a registry entry, not a change to the engine, and a
new document type cannot accidentally skip a verification stage.

Registered types: claim, pretrial demand, response, motion, complaint, appeal, contract and
consultation.

### Party labels are presentation; roles are not

A blueprint says a claim prints "Истец"/"Ответчик" and a response prints them in the other order.
What it cannot change is which locked party sits under which label: that binding runs through the
role sets, and Final Legal QA checks it. Presentation can never swap who is claiming against whom.

## Corpora

Four corpora were always intended; two exist today.

| Corpus | Status | Role |
|---|---|---|
| Legislation | implemented | The only source of a `VERIFIED` legal reference |
| Judicial practice | implemented | Persuasive support; can never raise a verification status |
| Approved templates | not implemented | — |
| Lawyer corrections | not implemented | — |

Both live corpora use article/paragraph-level chunks, effective-date metadata and hybrid semantic +
keyword retrieval. An explicit article locator is deterministic and outranks merely similar
provisions, so an exact article number cannot be lost to semantic ranking.

Retrieval only ever sees rows a human marked canonical. Live web search stays restricted to
official Kazakhstan sources, acts as a fallback, and never becomes canonical automatically.

### Judicial practice is not authority

Practice is offered beside a verified norm, never in place of one. A decision's own wording may
name articles the current case never verified; reproducing it would smuggle an unverified statutory
reference into the document as a quotation. The summary is therefore carried over only when every
article it names is already verified for this case — otherwise the act is cited by its identifying
details and the reader is pointed at the source.

An empty, unconfigured or unreachable practice corpus produces no practice section, and that
absence is not a verification gap: a document is complete without supporting practice.

## Money and time are code

No model computes an amount or a deadline. The calculation layer derives the debt from the contract
sum minus every payment credited against it, so the contract sum can never also appear as a
claimable position. Penalties accrue per period on the balance that was actually outstanding, which
is what lets a debt repaid mid-delay still owe the penalty for the time it was unpaid. Each accrual
period is printed so a reader can re-derive the figure instead of trusting it.

Where a contractual term is genuinely ambiguous — "не более N% от суммы задолженности" read against
the defaulted debt or against the remaining balance — the calculation reports the question rather
than deciding it silently.

## NEEDS_VERIFICATION discipline

An unresolved point stays visibly unresolved, in the document text and in a separate queue.

The converse matters as much: a marker on a fact the user actually supplied is treated as a defect,
not as harmless caution. Norms quoted purely for house style resolve through the same fail-closed
gateway but are never reported as verification gaps, so presentation cannot raise a false alarm on
determined data.

## LLM boundary

All OpenAI calls are isolated behind `LLMProvider`. Structured extraction uses Pydantic schemas.
Tests inject fake providers and therefore need no network access or API key — including the whole
evaluation suite, which runs against the fail-closed gateway because that is the configuration in
which inventing law would be easiest.

When a model is configured, it rewrites the deterministic draft for readability and is given that
draft as its reference. It cannot introduce an article, amount, date or attachment the reference
does not already contain, and its output passes the same Final Legal QA. A blocked draft falls back
to the deterministic one rather than withholding the document.
