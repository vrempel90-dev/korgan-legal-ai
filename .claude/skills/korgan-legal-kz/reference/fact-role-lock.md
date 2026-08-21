# FACT LOCK & ROLE LOCK

## Purpose

Prevent the most dangerous drafting failure: changing the user's facts or reversing the parties.

## FACT LOCK

Before analysis, extract only facts actually provided by:
- the user;
- uploaded documents;
- verified external records supplied by the host.

Do not add assumptions as facts.

Create an internal fact table conceptually equivalent to:

| Fact ID | Fact | Source | Confidence |
|---|---|---|---|
| F1 | Services were performed | User + signed act | High |
| F2 | Customer did not pay | User + bank evidence | Medium/High |

If two facts conflict, stop and clarify if the conflict is material.

## ROLE LOCK

Translate facts into roles.

Examples:

### Services debt
- Provider / Исполнитель = performed services
- Customer / Заказчик = must pay
- Creditor = Provider
- Debtor = Customer
- Plaintiff = Creditor, if it sues for payment
- Defendant = Debtor

### Employment
- Employee = performs labor
- Employer = owes salary/obligations
- Claimant/Applicant depends on the procedure

### Sale
- Seller / Buyer roles must be derived from the contract and the breached obligation.

## Mandatory role chain

For every dispute, answer internally:

1. Who performed / transferred / paid / acted?
2. Who owed the corresponding obligation?
3. Who allegedly breached?
4. Who suffered the legal consequence?
5. Who seeks relief?
6. Against whom?
7. What exactly must the other side do/pay/stop/recognize?

## Role freeze

Once roles are established, freeze them.

No later module may silently reverse:
- creditor/debtor;
- provider/customer;
- claimant/defendant;
- employer/employee;
- applicant/respondent.

If later evidence requires a role change, explicitly reopen ROLE LOCK and recalculate all downstream sections.

## Final cross-check

Before release, ensure:
- factual narrative uses the same roles;
- legal analysis uses the same roles;
- prayer for relief uses the same roles;
- attachments refer to the correct parties;
- money flows in the correct direction.

Any mismatch = QA FAIL.
