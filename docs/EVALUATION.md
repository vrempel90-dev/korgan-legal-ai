# Evaluation suite and quality gates

## What it is

`korgan_legal_ai.evals` holds synthetic matters with independently derived expectations. Every case
is invented — no party, amount or document comes from the private reference corpus — so a failing
assertion can print the whole case, and the generated report can be shared.

The suite runs with **no database, no network and no model**. The citation gateway is the
fail-closed one, which means no legal reference is available to the drafter at all. That is
deliberate: it is the configuration in which inventing law would be easiest, and therefore the one
worth measuring.

## Running it

```bash
pytest tests/test_eval_suite.py          # gate: every criterion must pass
python scripts/generate_quality_report.py  # writes QUALITY_REPORT.md
```

The report is generated, never written by hand, so every number in it comes from the same code
paths the tests exercise.

## Structure

Eight regression cases × six criteria = 48 criteria.

| Criterion | Question it answers |
|---|---|
| `calc.matches_manual_derivation` | Does the calculator agree with a formula worked out by hand? |
| `calc.no_double_counting` | Does the contract sum stay an input to the balance, not a second claim? |
| `doc.amounts_match_calculation` | Does every figure in the text come from the calculator? |
| `law.no_unverified_citations` | Is any article named without a confirmed source? |
| `verification.discipline` | Is NEEDS_VERIFICATION on the open questions — and only on those? |
| `style.house_layout` | Does the layout follow the applicable house-style rules? |

The expectation in `calc.matches_manual_derivation` is written independently of the code that
produces the number. Comparing the calculator against itself would prove nothing.

Four regression cases are tagged `trap` because they are the shapes where money goes wrong:

- partial payment (debt = contract − paid, never contract + remainder);
- several partial payments, with the penalty following the declining balance;
- a debt repaid mid-delay, where the penalty for the unpaid period survives;
- a catch-all "иные суммы" field echoing an amount already counted.

## Acceptance cases

`ACCEPTANCE_CASES` sits deliberately outside the regression suite, so "the suite passes" and "new
matters work" stay separate statements. It covers a monetary claim with a penalty ceiling, a
document with no monetary calculation at all, a matter with several partial payments and a set-off,
and a case with facts deliberately left undetermined.

## House-style rules that cannot pass without a corpus

Three of the eleven derived rules require quoting a specific norm: the verbatim opening formula, the
profile norm after the contract, and representative costs. With no canonical corpus connected they
report as unsatisfied, with the reason stated.

That is the correct outcome. The alternative — reciting law from memory to satisfy a layout rule —
is the failure this system exists to prevent, so the suite must not reward it. The
`style.house_layout` criterion therefore expects only the rules the drafter fully controls.

A case may name a rule in `style_exempt` with a reason, used only where the missing layout is the
right result: a document whose signatory was deliberately left unknown cannot produce a signature
block, and pretending otherwise would hide the gap.

## What the suite does not establish

It measures internal consistency: arithmetic, provenance, verification discipline and layout. It
does not and cannot establish that a document is legally correct — that the position is sound, the
norms apply, the rates are current or the facts are true. Those remain a human's judgement, and the
strongest machine status stays `READY FOR FINAL HUMAN REVIEW`.
