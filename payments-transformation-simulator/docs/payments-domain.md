# Payments domain

How the concepts in this simulator map onto the real world — and, just as importantly, where the
simulator simplifies.

Throughout, two labels are used:

> **REAL-WORLD STANDARD** — something that exists outside this application: an ISO standard, a
> message definition, a code set, an industry practice.
>
> **SIMULATED IMPLEMENTATION** — how this application models it, including the simplifications.

Nothing here should be read as an authoritative statement of any scheme rulebook. Scheme rulebooks
are owned by their operators, change over time, and contain far more detail than is modelled.

---

## Contents

1. [The payment lifecycle](#the-payment-lifecycle)
2. [Validation](#validation)
3. [Compliance screening](#compliance-screening)
4. [Clearing](#clearing)
5. [Settlement](#settlement)
6. [Nostro and vostro](#nostro-and-vostro)
7. [Accounting](#accounting)
8. [ISO 20022](#iso-20022)
9. [pacs.008](#pacs008--fitoficustomercredittransfer)
10. [pacs.002](#pacs002--fitofipaymentstatusreport)
11. [pacs.004](#pacs004--paymentreturn)
12. [pacs.028](#pacs028--fitofipaymentstatusrequest)
13. [camt.056 and camt.029](#camt056-and-camt029--cancellation-and-resolution)
14. [camt.053 and camt.054](#camt053-and-camt054--statement-and-notification)
15. [MT and the move to MX](#mt-and-the-move-to-mx)
16. [Reconciliation](#reconciliation)
17. [Investigation](#investigation)
18. [Timeout handling](#timeout-handling)
19. [Identifiers](#identifiers)
20. [Why payments fail](#why-payments-fail)
21. [Glossary](#glossary)

---

## The payment lifecycle

**REAL-WORLD STANDARD.** A credit transfer passes through recognisable phases, whatever the rail:
the customer instructs their bank; the bank validates and screens the instruction; it constructs a
scheme message and sends it to a clearing system; the clearing system responds; value settles
between the banks; both banks update their books; and the records are reconciled against what the
accounts actually show.

**SIMULATED IMPLEMENTATION.** Thirteen explicit stages, each with a persisted state. The names are
the simulator's own, chosen so that a business user and a developer can both point at the same
place:

| Stage | What a bank is really doing |
| ----- | --------------------------- |
| Initiation | Receiving the instruction from the customer or channel |
| Channel intake | Accepting it, stamping it with references, queuing it |
| Pre-validation | Structural and technical checks: is this even a well-formed instruction? |
| Business validation | Scheme and bank rules: may we send this, on this rail, today? |
| Compliance | Sanctions and embargo screening before anything leaves the bank |
| Orchestration | Deciding the route and the timing expectations |
| Message generation | Building the scheme message |
| Clearing | Handing the message to the clearing system |
| Clearing response | Receiving (or failing to receive) the status report |
| Settlement | Moving value between the banks |
| Accounting | Posting to the general ledger |
| Reconciliation | Checking that the books agree with the statement |
| Completion | Closing the payment |

**Simplifications.** A real bank interleaves these: liquidity checks, fraud scoring, duplicate
detection at several points, warehousing of future-dated payments, batch cut-offs. The simulator
runs them strictly in order, one payment at a time.

## Validation

**REAL-WORLD STANDARD.** Validation is layered. Technical validation asks whether the message is
structurally valid. Business validation asks whether the bank is willing to make this payment.
Scheme validation asks whether this rail will accept it. Rejections carry an ISO 20022
*ExternalStatusReason* code — `AC01` for an invalid creditor account, `AM04` for insufficient funds,
`AM05` for a duplicate, `RR04` for a regulatory reason, `FF01` for a format problem.

The IBAN check-digit algorithm (ISO 13616, mod-97-10) and the BIC structure (ISO 9362) are real
standards, implemented here exactly.

**SIMULATED IMPLEMENTATION.** A rule book of around 30 rules, each declaring its category, severity,
stage, the rails it applies to, the field it concerns, the ISO reason code it raises and what
happens when it fails. Every rule produces a result with the actual value, the expected value and a
remediation note — not just a pass or a fail.

Rules can be disabled from the Business Rule Explorer. A disabled rule is recorded as `SKIPPED`
rather than omitted, so it is always visible which checks did and did not run.

**Simplifications.** A real bank's rule set runs to hundreds of rules, is versioned, has effective
dates, and differs per product and per customer agreement. Account validation here is a lookup
against a small fictional book rather than a core-banking enquiry.

## Compliance screening

**REAL-WORLD STANDARD.** Before a payment is released, parties, agents, countries and free-text
fields are screened against sanctions and embargo lists. A hit stops the payment and raises an alert
for a human to disposition. Screening is a regulatory obligation, and what may be said to the
customer about a held payment is itself constrained.

**SIMULATED IMPLEMENTATION.** Deterministic exact-match screening against a handful of entirely
fictional entries — fictional embargo country codes (`ZZ`, `XA`, `QX`), fictional designated
entities, fictional designated institutions, a short list of high-risk remittance keywords, and a
fictional PEP list. Blocking hits move the payment to `BLOCKED` and open an investigation; a PEP hit
is recorded but does not block.

Screening results are written to the same table as rule-book results, so the investigation view
shows one unified list of checks.

**Simplifications.** This is a toy. Real screening uses licensed watch-list data, fuzzy and
phonetic matching, alias and date-of-birth matching, list versioning, whitelisting, alert queues
with four-eyes disposition, and audited decision records. None of that is modelled.

## Clearing

**REAL-WORLD STANDARD.** A clearing system receives payment messages from participants, applies its
own validation, and reports a status back. "Clearing" is the exchange and processing of the payment
instruction; it is not the same thing as settlement, and the two can happen at different times. An
instant scheme compresses them to seconds; a correspondent chain can take days.

**SIMULATED IMPLEMENTATION.** A `ClearingAdapter` the orchestrator talks to, and behind it a
`SimulatedClearingSystem` that decides deterministically. Its default decision is to accept. The QA
Lab can configure it to reject (business or technical), to delay its answer, never to answer, to be
unavailable, to answer twice, or to answer with a message missing its original references.

Each dispatch creates a `clearing_transaction` carrying the clearing reference, the send time, when
a response is due, when the timeout expires, the response latency, and the reason code if rejected.

**Simplifications.** The clearing system runs in-process. There is no network protocol, no mutual
authentication, no message signing, no store-and-forward, no participant reachability directory, no
queuing or throttling, and no settlement cycle or netting.

## Settlement

**REAL-WORLD STANDARD.** Settlement is the actual transfer of value between the banks. It may be
gross (each payment individually, as in an RTGS or instant scheme) or net (positions settled
periodically). The *settlement method* in ISO 20022 says how: `CLRG` through a clearing system,
`INDA`/`INGA` across an account held with the instructed or instructing agent, `COVE` with a
separate cover payment. Finality — the point at which the transfer becomes irrevocable — is defined
by the scheme.

**SIMULATED IMPLEMENTATION.** A settlement engine that posts across the account type the rail
specifies: a central-bank style settlement account for the domestic instant rail, a pre-funded CSM
position for SEPA Instant, a nostro account for cross-border. It records the payment amount and the
settlement amount separately (so a difference is visible), the settlement method, the value date and
a settlement reference.

Statuses: `PENDING`, `SUBMITTED`, `SETTLED`, `FAILED`, `PARTIALLY_SETTLED`, `REVERSED`.

**Simplifications.** No liquidity management, no settlement windows or cycles, no netting, no queue
management, no reservation of funds. Cross-currency settlement uses fixed invented indicative rates
rather than an FX execution.

## Nostro and vostro

**REAL-WORLD STANDARD.** Two names for the same account, seen from opposite sides.

- **Nostro** — Italian *ours*. **Our** money on **their** books: an account our bank holds with a
  correspondent, usually in the correspondent's currency. Our USD nostro with a New York bank is how
  we hold and move USD.
- **Vostro** — Italian *yours*. **Their** money on **our** books: an account another bank holds with
  us, in our currency.

```
   Our bank                                   Correspondent bank
   ┌────────────────────┐                     ┌────────────────────┐
   │ NOSTRO USD         │ ───── the same ──── │ VOSTRO (for us)    │
   │ "our USD at them"  │      account        │ "their CHF at us"  │
   └────────────────────┘                     └────────────────────┘
```

An outgoing cross-border USD payment debits the customer and reduces our USD nostro position: we are
spending money we hold abroad. Reconciling the nostro — our record of that account against the
statement the correspondent sends — is one of the classic operational controls in correspondent
banking, and one of the classic sources of breaks.

**SIMULATED IMPLEMENTATION.** Nostro accounts in USD, EUR, GBP, INR, JPY, SGD and CHF with fictional
correspondents; vostro accounts in CHF for two of those correspondents. The cross-border rail settles
across the matching nostro; the accounts page explains the relationship and shows the movements.

**Simplifications.** No nostro reconciliation cycle of its own, no correspondent charges deducted in
transit (except where injected to create a reconciliation break), no account-servicing fees, no
intraday position or liquidity management.

## Accounting

**REAL-WORLD STANDARD.** Every payment produces balanced double-entry postings. For an outgoing
customer payment, the customer account is debited and a settlement or nostro account is credited.
Debits must equal credits; if they do not, the ledger is wrong and the control account will be out.

**SIMULATED IMPLEMENTATION.** One journal per payment:

```
DEBIT   customer account              4,850.00 CHF
CREDIT  settlement / nostro account   4,850.00 CHF
```

Each entry records its id, journal reference, side, account, amount, currency, posting date, value
date, status, narrative and the account balance after posting. Balances on the accounts are updated
for real, so the accounts page shows genuine movement. A return or a clearing rejection posts a
reversing journal and marks the originals `REVERSED`.

The displayed balance follows the account holder's view rather than raw ledger signage, because the
two differ by account type:

| Account type | Debit | Credit |
| ------------ | ----- | ------ |
| Customer, vostro — a liability, we owe it | decreases | increases |
| Nostro, settlement, suspense — an asset, we hold it | increases | decreases |

That is why the journal above credits the nostro and the nostro position still **falls**: we are
spending money we hold at the correspondent. The double entry balances either way; only the
direction of the displayed balance is type-aware.

**Simplifications.** No charge or FX legs, no accrual accounting, no end-of-day cut-off, no
multi-currency position keeping, no suspense-account workflow beyond the account existing, no
sub-ledger/general-ledger split.

## ISO 20022

**REAL-WORLD STANDARD.** ISO 20022 is a methodology and a repository for financial messaging, not a
single format. It defines business processes, a data dictionary and message definitions identified
like `pacs.008.001.08`: business area (`pacs` — payments clearing and settlement, `camt` — cash
management, `pain` — payments initiation), message number, variant, version.

It replaced the fixed-field MT standard for cross-border interbank payments, and is the basis for
SEPA, for most instant schemes, and for domestic schemes worldwide.

**SIMULATED IMPLEMENTATION.** Nine message types generated as structurally realistic XML.

**Simplifications.** Messages are **not validated against the official XSDs**, do not use market
practice (CBPR+ or scheme) usage guidelines, and are never transmitted anywhere. One payment per
message — no batching, no `pain.001` initiation layer, no group-level status.

## pacs.008 — FIToFICustomerCreditTransfer

**REAL-WORLD STANDARD.** The core interbank credit transfer: the debtor agent instructs the creditor
agent to pay the creditor. Key elements:

| Element | Meaning |
| ------- | ------- |
| `GrpHdr/MsgId` | Identifies this message. Not the payment reference |
| `GrpHdr/NbOfTxs` | How many transactions it carries |
| `GrpHdr/SttlmInf/SttlmMtd` | How settlement is effected (`CLRG`, `INDA`, …) |
| `PmtId/InstrId` | The instructing party's reference, point-to-point |
| `PmtId/EndToEndId` | The customer's reference, carried unchanged along the whole chain |
| `PmtId/TxId` | Uniquely identifies the transaction within the chain |
| `PmtId/UETR` | The end-to-end tracking reference (UUIDv4) |
| `IntrBkSttlmAmt` | The amount actually settled between the banks |
| `InstdAmt` | The amount the customer instructed, before charges or FX |
| `ChrgBr` | Who bears the charges: `DEBT`, `CRED`, `SHAR`, `SLEV` |
| `Dbtr` / `DbtrAcct` / `DbtrAgt` | The paying customer, their account, their bank |
| `Cdtr` / `CdtrAcct` / `CdtrAgt` | The beneficiary, their account, their bank |
| `RmtInf` | What the payment is for: `Ustrd` free text or `Strd` structured |

`EndToEndId` matters disproportionately: it is the reference the customer quotes, the one that must
survive the whole chain, and the one reconciliation matches on.

**SIMULATED IMPLEMENTATION.** Generated from the payment record, with the group header, settlement
information, payment identification, amounts, charge bearer, all four parties, purpose, service
level and remittance information populated. Optional elements are omitted when empty, as the
standard intends. A UETR is included only on the rail that carries one. The message viewer shows the
field-by-field mapping from the payment record to each ISO element.

## pacs.002 — FIToFIPaymentStatusReport

**REAL-WORLD STANDARD.** Reports the status of a previously sent instruction. Statuses include:

| Code | Meaning |
| ---- | ------- |
| `ACTC` | Accepted technical validation |
| `ACCP` | Accepted customer profile |
| `ACSP` | Accepted, settlement in process |
| `ACSC` | Accepted, settlement completed |
| `RJCT` | Rejected — not executed, and will not be |
| `PDNG` | Pending |

A rejection carries a reason code from the ExternalStatusReason code set, and may carry additional
narrative. `ACSC` is the one that means the money has moved.

**SIMULATED IMPLEMENTATION.** Produced by the simulated clearing system, carrying the original
message id, the original end-to-end id, the transaction status, the reason code and text on
rejection, and the clearing system reference. The business view explains what the status code
actually means in plain language.

A **malformed** variant omits the original end-to-end id, which is how a real integration problem
presents: a response exists, but it cannot be matched to the instruction automatically.

## pacs.004 — PaymentReturn

**REAL-WORLD STANDARD.** Returns funds for a payment that cannot be applied — a closed account, a
blocked account, a name mismatch. It references the original payment, states the returned amount
(which may be net of charges deducted by an agent in the chain) and carries a return reason code.

A return is a **new payment in the opposite direction**, not an undo. It has its own settlement.

**SIMULATED IMPLEMENTATION.** Receiving a pacs.004 reverses the accounting journal, marks the
settlement `REVERSED` and moves the payment to `RETURNED`. The message records the original and
returned amounts separately and can carry deducted charges, so the difference is visible.

## pacs.028 — FIToFIPaymentStatusRequest

**REAL-WORLD STANDARD.** Asks for the status of a payment for which no status report was received.
It is the polite first step when a payment has gone quiet: *what happened to this instruction?*

**SIMULATED IMPLEMENTATION.** Sent automatically when the clearing response times out, before any
investigation action is taken and before any thought of re-sending. The business view states how
long was waited and against what threshold.

**Simplification.** Real schemes differ on whether a status request, a cancellation request or an
operational enquiry is the correct first step, and some have their own proprietary enquiry channel.

## camt.056 and camt.029 — cancellation and resolution

**REAL-WORLD STANDARD.** `camt.056` is a *request* to cancel a payment already sent. Reasons include
`DUPL` (duplicate), `TECH` (technical error), `FRAD` (fraud), `CUST` (customer request), `CUTA`
(pending investigation), `UPAY` (unjustified).

Crucially, it is a request, not an instruction. The receiving side decides. `camt.029` carries the
answer: `CNCL` cancelled, `RJCR` rejected, `PDCR` pending, `ACVC` accepted with a value-date
correction. Once the beneficiary has been credited, a recall normally requires their consent.

**SIMULATED IMPLEMENTATION.** A cancellation can be requested from the payment view or from an
investigation. The simulator resolves it based on whether value has actually moved: if a settlement
exists in `SETTLED` or `PARTIALLY_SETTLED`, the recall is refused with `RJCR`; otherwise it is
accepted with `CNCL`, the payment is cancelled and any debit is reversed.

That rule is deliberate. Basing the answer on whether value moved, rather than on our own status
label, is what makes the refusal realistic.

## camt.053 and camt.054 — statement and notification

**REAL-WORLD STANDARD.**

- **camt.054** — a *notification* of a debit or credit, typically intraday, usually per movement.
- **camt.053** — an end-of-day *statement*: opening balance, booked entries, closing balance.

For reconciliation, the statement is the external source of truth. Each entry carries booking and
value dates, a bank transaction code, and references including the end-to-end id.

**SIMULATED IMPLEMENTATION.** When a journal is posted, a statement entry is created and a camt.054
generated for it. A camt.053 can be generated for any account on demand, assembled from the stored
statement entries with opening and closing balances.

The important design point: **statement entries are stored separately from accounting entries.** If
they were the same records, reconciliation would be comparing a thing with itself and could never
find anything. Keeping the two apart is what makes a missing notification, a changed amount or a
duplicate statement line into real, discoverable breaks.

A statement entry is only published when the customer debit was actually booked — a pending debit
produces no notification, which is exactly the situation a real desk would see.

## MT and the move to MX

**REAL-WORLD STANDARD.** MT is the legacy fixed-field FIN format: `MT103` is a single customer credit
transfer, with fields such as `:20` sender's reference, `:32A` value date / currency / amount, `:50`
ordering customer, `:59` beneficiary, `:71A` charges, `:72` sender-to-receiver information. MX is the
ISO 20022 XML equivalent. Cross-border interbank payments have moved from MT to MX.

**There is no universal one-to-one mapping.** The authoritative rules are the CBPR+ usage guidelines
and the published translation rules. The problems are structural:

- **Concatenated fields.** `:32A` is value date, currency and amount in one field; MX splits it into
  `IntrBkSttlmDt` and `IntrBkSttlmAmt` with a `Ccy` attribute.
- **Option letters.** `:50A` carries a BIC, `:50F` structured party data, `:50K` unstructured name
  and address. Only `F` maps cleanly to the structured MX `Dbtr`; `K` requires parsing free text.
- **Free text.** `:72` codewords are the classic truncation problem. Some map to structured MX
  elements; many do not.
- **MX is richer.** Batch metadata, an explicit settlement method and ultimate parties have no MT
  equivalent without workarounds.
- **Length and character set.** `:70` allows four lines of 35 characters; MX allows `Max140Text`, so
  line structure is lost.

**SIMULATED IMPLEMENTATION.** An MT103 is generated alongside the pacs.008 on the cross-border rail,
and the mapping table classifies every row as `DIRECT`, `TRANSFORMED`, `DERIVED` or
`NO_DIRECT_EQUIVALENT`. The simulator is explicit that this is an educational comparison, not an
implementation specification.

## Reconciliation

**REAL-WORLD STANDARD.** Reconciliation proves that the bank's records agree with reality. Internal
payment records, the general ledger, the clearing system's records and the account statement should
all tell the same story. Where they do not, the difference is a **break**, and a break is worked
until it is explained.

Common break types, and what they usually mean:

| Break | Usual cause |
| ----- | ----------- |
| Missing entry | Notification never arrived, was dropped, or the booking fell after the cut-off |
| Amount mismatch | Charges deducted in transit, FX applied at a different time, partial settlement |
| Currency mismatch | Wrong nostro credited; an accounting configuration error |
| Duplicate | Settled twice, or notified twice — establish which before acting |
| Timing difference | Booked in a different period; a cut-off difference, not a value difference |
| Reference mismatch | The reference was not carried through the chain; auto-matching failed |
| Unmatched statement entry | A movement on the account with no internal record at all |

**SIMULATED IMPLEMENTATION.** All four views are compared for every payment, with the statement as
the external source of truth. Each break records the difference amount, a probable cause and a
recommended action. Ledger integrity is checked first: a journal that does not balance is a break
regardless of what the statement says.

**Simplifications.** One payment at a time. No many-to-many matching across batches, no tolerance
rules, no ageing, no auto-matching heuristics, no reconciliation periods.

## Investigation

**REAL-WORLD STANDARD.** When a payment cannot be completed or explained, an investigation case is
raised. It is worked by an operations analyst who gathers evidence, contacts the counterparty, and
records every step. A good case states what was expected, what actually happened, and what is
believed to have caused it — so that anyone can pick it up.

**SIMULATED IMPLEMENTATION.** Investigations are opened automatically for clearing timeouts,
compliance blocks, settlement failures, accounting breaks, reconciliation breaks and beneficiary
claims. Each records expected behaviour, actual behaviour, probable cause, recommended action,
priority and an action log, and can be annotated and resolved from the investigation workbench.

The recommended action is specific to the situation. For a timeout it says to await the status
response and reprocess — and explicitly not to re-send the pacs.008, because that risks a duplicate
credit. For a missing statement entry it says to request a re-send rather than to repair the
payment.

## Timeout handling

**REAL-WORLD STANDARD.** Instant schemes define a maximum time within which the outcome must be
known — single-digit seconds for the customer-facing promise, with a longer window before the
payment is treated as failed. If no status report arrives, the payment is in the worst possible
state: **unknown**. It may have been processed and the response lost, or never have arrived at all.

The one thing a bank must not do is re-send the instruction. That risks crediting the beneficiary
twice.

**SIMULATED IMPLEMENTATION.** Each rail declares its own response threshold (25s domestic instant,
20s SEPA Instant, 60s cross-border, 30s generic). On expiry:

```
pacs.008 sent
      │
      ▼  no pacs.002 within the scheme threshold
  TIMED_OUT
      │
      ├──▶ pacs.028 status request sent
      │
      ▼
INVESTIGATION_REQUIRED      ── the lifecycle stops here
      │
      ▼  the clearing system eventually answers
  accepted ──▶ CLEARING_ACCEPTED ──▶ settlement, accounting, reconciliation
  rejected ──▶ CLEARING_REJECTED ──▶ any customer debit reversed
```

The threshold is **per scheme**, never a global constant. In demo mode it is divided by the
simulation speed factor so a timeout can be demonstrated in seconds, and both the accelerated and
the realistic value are shown wherever a timeout is reported.

## Identifiers

**REAL-WORLD STANDARD.**

| Identifier | Scope | Who assigns it |
| ---------- | ----- | -------------- |
| `InstrId` | Point-to-point between two agents | The instructing agent |
| `EndToEndId` | The whole chain, unchanged | The debtor or their bank |
| `TxId` | The transaction within the chain | The first agent |
| `UETR` | End-to-end tracking, UUIDv4 | The originator |
| Clearing system reference | Within the clearing system | The clearing system |
| Statement entry reference | Within the account statement | The account servicer |

**SIMULATED IMPLEMENTATION.** All of these, plus a `correlation_id` stamped on the payment and
copied onto every event and message. A payment can be found from any of them. That is the point of
the search: an investigator who has only a statement line, or only a clearing reference, must be
able to get back to the payment.

UETRs are generated locally in the UUIDv4 shape and tracked only inside this simulator. They are not
registered anywhere and the tracking view is not connected to any real tracking service.

## Why payments fail

A short field guide, by stage.

**Validation** — the cheapest failures. The payment never leaves the bank, nothing has moved, and
the fix is to correct the data. Invalid IBAN check digits, an unsupported currency for the rail, an
amount over the scheme ceiling, a missing mandatory field, a duplicate end-to-end id.

**Compliance** — the payment is stopped before any message is sent. What can be said to the customer
is constrained; the alert must be dispositioned by someone qualified to do it.

**Clearing rejection** — our instruction was valid but the receiving side will not apply it. Any
customer debit must be reversed, and the customer told. The reason code says why.

**Timeout** — the hardest case, because the outcome is *unknown*. Do not re-send. Ask, wait, then
act on the answer.

**Settlement failure** — the clearing system accepted but value did not move. The beneficiary bank
may already be relying on the acceptance. Exposure sits with the bank until it is resolved.

**Accounting break** — no customer impact, but the ledger is wrong until corrected. A missing leg, a
duplicate posting, a debit and credit that disagree.

**Reconciliation break** — usually a control failure rather than a customer problem, but it must be
cleared, and occasionally it is the first sign of something worse.

**Return** — the payment completed and came back. The customer must be re-credited and told why.

**Beneficiary not credited** — everything on our side succeeded and the customer still has not been
paid. The problem is beyond our leg of the chain; the enquiry goes to the beneficiary bank, and the
customer debit is *not* reversed unilaterally.

## Glossary

| Term | Meaning |
| ---- | ------- |
| **ACSC** | AcceptedSettlementCompleted — the money has moved |
| **BIC** | Business Identifier Code, ISO 9362; 8 or 11 characters identifying an institution |
| **Charge bearer** | Who pays the charges: `DEBT` debtor, `CRED` creditor, `SHAR` shared, `SLEV` per service level |
| **Clearing** | Exchange and processing of the payment instruction |
| **Correspondent** | A bank that holds an account for another bank, enabling it to operate in a currency |
| **EndToEndId** | The customer's reference, carried unchanged along the whole chain |
| **Finality** | The point at which a transfer becomes irrevocable |
| **IBAN** | International Bank Account Number, ISO 13616, with mod-97 check digits |
| **Instant payment** | A scheme where the outcome is known, and funds available, within seconds |
| **MT / MX** | Legacy fixed-field FIN format / ISO 20022 XML |
| **Nostro** | Our account with another bank, in their currency |
| **RJCT** | Rejected — not executed and will not be |
| **Settlement** | The actual transfer of value between banks |
| **UETR** | Unique End-to-end Transaction Reference, a UUIDv4 used for tracking |
| **Vostro** | Another bank's account with us, in our currency |
