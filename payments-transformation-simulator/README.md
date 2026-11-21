# Payments Transformation Simulator

**Observe. Execute. Break. Investigate. Reconcile.**

A payments operations console that simulates the full lifecycle of a modern payment — from
initiation through validation, sanctions screening, ISO 20022 messaging, clearing, settlement,
double-entry accounting and reconciliation — and, just as importantly, what happens when any of
those stages goes wrong.

> **This is a simulator.** It is standards-inspired and contains only fictional data. It is not an
> implementation of any bank, SWIFT, SIC, SEPA or clearing system. Every bank, BIC, IBAN, account,
> reference and screening-list entry is invented. Where behaviour is simplified it is labelled as
> *simulation behaviour* or a *simplified model*, both in the UI and in the code.

---

## Contents

1. [Product overview](#product-overview)
2. [What it answers](#what-it-answers)
3. [Architecture](#architecture)
4. [Payment lifecycle](#payment-lifecycle)
5. [Supported schemes](#supported-schemes)
6. [ISO 20022 messages](#iso-20022-messages)
7. [Failure injection](#failure-injection)
8. [Reconciliation](#reconciliation)
9. [Features by area](#features-by-area)
10. [Local setup](#local-setup)
11. [Docker setup](#docker-setup)
12. [Testing](#testing)
13. [API documentation](#api-documentation)
14. [Database architecture](#database-architecture)
15. [Demo scenarios](#demo-scenarios)
16. [Screens](#screens)
17. [Known limitations](#known-limitations)
18. [Future enhancements](#future-enhancements)

---

## Product overview

Most payment training material stops at the happy path. Operations teams spend their time on
everything else: the status report that never arrived, the statement line that does not match, the
customer who was debited for a payment the clearing system refused.

This application is built around those cases. You create a payment, watch it travel through a
realistic processing architecture, deliberately break it at any stage, and then investigate the
failure with the same artefacts a real operations analyst would have: the validation results, the
ISO 20022 messages, the clearing response (or its absence), the accounting journal, the statement
entries and the reconciliation record.

It is designed for payments business analysts, SMEs, QA leads, product owners, operations teams and
transformation consultants, with a **business / technical mode switch** so the same screen can speak
either language.

## What it answers

- What actually happens to a payment after a customer presses Send?
- What happens when something goes wrong — and how would you know?
- Where exactly did this payment fail, and why?
- Which rule rejected it, with what ISO 20022 reason code, and what was the expected value?
- What message was produced at each step, and what does each field map from?
- The clearing system accepted it and we settled — so why does the statement disagree?
- Can this payment safely be retried, or would that risk a duplicate credit?

## Architecture

A **modular monolith**: one backend process with clear internal boundaries, and a separate frontend.
There is no microservice split, because nothing here would benefit from one.

```
                        ┌──────────────────────────────────────────┐
   Browser ────────────▶│  React + TypeScript operations console   │
                        │  (Vite, react-router, no state library)  │
                        └────────────────────┬─────────────────────┘
                                             │  REST /api/v1 (JSON)
                        ┌────────────────────▼─────────────────────┐
                        │  FastAPI application                     │
                        │  middleware: request id, correlation id, │
                        │  rate limit, structured logging          │
                        └────────────────────┬─────────────────────┘
                                             │
                        ┌────────────────────▼─────────────────────┐
                        │  Services  payment · scenario · testcase │
                        │            BA · search                   │
                        └────────────────────┬─────────────────────┘
                                             │
   ┌─────────────────────────────────────────▼──────────────────────────────────────┐
   │                            Payment orchestrator                               │
   │          (the only component allowed to change payment status)                 │
   └───┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┘
       │          │          │          │          │          │          │
   ┌───▼───┐ ┌────▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────────┐
   │ Rule  │ │Compli-  │ │Message │ │Clearing│ │Settle- │ │Account-│ │Reconcilia- │
   │engine │ │ance     │ │engine  │ │adapter │ │ment    │ │ing     │ │tion        │
   └───────┘ └─────────┘ └────────┘ └───┬────┘ └────────┘ └────────┘ └────────────┘
                                        │
                              ┌─────────▼──────────┐
                              │ Simulated clearing │
                              │ system (pacs.002)  │
                              └────────────────────┘

       State machine · Event recorder · Audit trail · Failure injection · Investigation desk
                                             │
                        ┌────────────────────▼─────────────────────┐
                        │  SQLAlchemy 2 · Alembic · 21 tables      │
                        │  SQLite (local) / PostgreSQL (docker)    │
                        └────────────────────┬─────────────────────┘
                                             │
                        ┌────────────────────▼─────────────────────┐
                        │  Durable scheduler (scheduled_job table) │
                        │  delayed clearing responses, timeouts    │
                        └──────────────────────────────────────────┘
```

**Stack**

| Layer            | Choice                                                            |
| ---------------- | ----------------------------------------------------------------- |
| Frontend         | React 18 + TypeScript 5, Vite 6, react-router 6, hand-built CSS   |
| Backend          | Python 3.12, FastAPI, Pydantic v2                                 |
| Persistence      | SQLAlchemy 2, Alembic migrations, SQLite or PostgreSQL            |
| Async behaviour  | Durable job table polled by a background worker thread            |
| Tests            | pytest (backend), Vitest + Testing Library (frontend)             |
| Containerisation | Docker + Docker Compose (Postgres, API, Nginx-served UI)          |

**Principles applied**

- Business logic lives in the backend engines. A UI component never decides whether a payment is
  valid.
- The backend owns payment state. Every transition is checked against an explicit state machine, and
  an illegal transition raises instead of being silently applied.
- Scheme behaviour is configuration. Adding a rail means adding one module and registering it.
- The rule book is one source of truth, read by the processing engine, the Business Rule Explorer,
  the test-case generator and the BA workbench alike.
- Asynchronous behaviour is persisted, not held in memory, so pending work survives a restart and is
  inspectable.
- Money is `Decimal` end to end, stored exactly on both PostgreSQL and SQLite. No floats.

Design decisions and their trade-offs are recorded in [`docs/architecture.md`](docs/architecture.md).

## Payment lifecycle

Thirteen stages, each with a persisted state (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `REJECTED`,
`FAILED`, `TIMED_OUT`, `INVESTIGATION_REQUIRED`, `REVERSED`, `SKIPPED`, …):

```
INITIATION ─▶ CHANNEL_INTAKE ─▶ PRE_VALIDATION ─▶ BUSINESS_VALIDATION ─▶ COMPLIANCE
     ─▶ ORCHESTRATION ─▶ MESSAGE_GENERATION ─▶ CLEARING ─▶ CLEARING_RESPONSE
     ─▶ SETTLEMENT ─▶ ACCOUNTING ─▶ RECONCILIATION ─▶ COMPLETION
```

The payment aggregate moves through its own status vocabulary, enforced by the state machine:

```
INITIATED → VALIDATING → VALIDATED → COMPLIANCE_CHECK → MESSAGE_GENERATED
          → SENT_TO_CLEARING → CLEARING_ACCEPTED → SETTLEMENT_PENDING → SETTLED
          → ACCOUNTED → RECONCILED → COMPLETED

failure paths
  VALIDATING          → REJECTED
  COMPLIANCE_CHECK    → BLOCKED               → INVESTIGATION_REQUIRED
  SENT_TO_CLEARING    → TIMED_OUT             → INVESTIGATION_REQUIRED
  CLEARING_RESPONSE   → CLEARING_REJECTED     → (customer debit reversed)
  SETTLEMENT          → SETTLEMENT_FAILED     → INVESTIGATION_REQUIRED
  ACCOUNTING          → ACCOUNTING_BREAK      → INVESTIGATION_REQUIRED
  RECONCILIATION      → RECONCILIATION_BREAK  → INVESTIGATION_REQUIRED
  COMPLETED           → RETURNED / REVERSED
```

`INVESTIGATION_REQUIRED` is a real state with real consequences: the payment cannot be closed, an
investigation case is open, and the only permitted forward moves are the ones the state machine
allows. Retrying is a controlled transition that re-runs the lifecycle for real — a payment whose
data is still wrong fails again.

## Supported schemes

Four rails, each a configuration module (`backend/app/schemes/definitions.py`):

| Rail                      | Currency      | Ceiling (simulated) | Clearing threshold | Settlement        | UETR | Legacy |
| ------------------------- | ------------- | ------------------- | ------------------ | ----------------- | ---- | ------ |
| **SIC Instant**           | CHF           | 20,000              | 25 s               | Settlement a/c, T+0 | no   | —      |
| **SEPA Instant**          | EUR           | 100,000             | 20 s               | CSM position, T+0 | no   | —      |
| **SWIFT cross-border**    | 9 currencies  | 50,000,000          | 60 s               | Nostro, T+1       | yes  | MT103  |
| **Generic ISO 20022**     | 10 currencies | 10,000,000          | 30 s               | Settlement a/c    | no   | —      |

Each rail carries its own currency scope, country scope, remittance limit, duplicate window,
service levels, charge bearers, cut-off, rejection reason codes, settlement account type and value
date rule — plus the ordered rule set that applies to it.

> Limits, cut-offs and thresholds are plausible simulator values, **not** an authoritative statement
> of any live rulebook.

## ISO 20022 messages

Generated as structurally realistic XML by `backend/app/engines/messaging`:

| Message      | ISO identifier        | Direction | Role in the simulator                                     |
| ------------ | --------------------- | --------- | --------------------------------------------------------- |
| **pacs.008** | pacs.008.001.08       | outbound  | The credit transfer instruction                            |
| **pacs.002** | pacs.002.001.10       | inbound   | Clearing status report (ACSC / RJCT + reason code)         |
| **pacs.004** | pacs.004.001.09       | inbound   | Payment return, with deducted charges                      |
| **pacs.028** | pacs.028.001.03       | outbound  | Status request, sent after a timeout                       |
| **camt.056** | camt.056.001.08       | outbound  | Cancellation request                                       |
| **camt.029** | camt.029.001.09       | inbound   | Resolution of investigation (CNCL / RJCR)                  |
| **camt.054** | camt.054.001.08       | inbound   | Debit/credit notification — the reconciliation input       |
| **camt.053** | camt.053.001.08       | inbound   | Account statement, generated per account on demand         |
| **MT103**    | legacy FIN            | outbound  | Cross-border legacy equivalent, for MT → MX comparison     |

The **message viewer** shows five views of each message: a plain-English business view, the
formatted payload, the field-by-field mapping from the payment record to the ISO element, per-field
validation, and the message timeline. Payloads can be copied or downloaded.

### MT → MX mapping

A field-level MT103 ↔ pacs.008 comparison that refuses to pretend the mapping is one-to-one. Every
row is classified:

- **DIRECT** — one MT field onto one MX element with the same meaning
- **TRANSFORMED** — split, combined, re-coded or restructured (`:32A` becomes three MX elements)
- **DERIVED** — inferred from the message type, scheme or context rather than copied
- **NO_DIRECT_EQUIVALENT** — `:72` free-text codewords, MX batch metadata, ultimate parties

## Failure injection

The design rule: **an injection never fakes a result.** It changes the input, or the behaviour of a
downstream system, and the engines then fail for real.

- **Data injections** mutate the instruction before validation runs, so the genuine rule fires and
  produces a genuine validation result with a real reason code.
- **Clearing injections** configure the simulated clearing system's response.
- **Settlement, accounting and reconciliation injections** are consumed by those engines when they
  execute.

Every injection records what it changed (before → after) on the audit trail and on the payment
journey, so an investigation shows *why* it failed, not *that a failure was requested*.

30 failure modes across eight categories:

| Category           | Examples                                                                          |
| ------------------ | --------------------------------------------------------------------------------- |
| **Validation**     | invalid IBAN · invalid BIC · unsupported currency · over the scheme ceiling · missing mandatory field · remittance too long · duplicate EndToEndId · insufficient funds · past execution date |
| **Compliance**     | embargo jurisdiction · sanctions party match · suspicious remittance wording      |
| **Clearing**       | business rejection · technical rejection · clearing unavailable · duplicate response · malformed response |
| **Timeout**        | no pacs.002 at all · delayed pacs.002                                             |
| **Settlement**     | settlement rejected · amount mismatch · partial settlement · settled but status not updated |
| **Accounting**     | missing entry · duplicate entry · debit/credit amount mismatch · currency mismatch · delayed posting |
| **Reconciliation** | missing camt.054 · amount mismatch · currency mismatch · duplicate settlement · unmatched statement entry · timing difference · reference mismatch |
| **Return**         | beneficiary bank returns the payment · clearing accepted but beneficiary not credited |

## Reconciliation

Reconciliation compares **four views of the same payment**:

1. **Internal** — the payment record held by the payment engine
2. **Accounting** — the general-ledger journal posted for it
3. **Clearing** — the clearing system's own record
4. **Statement** — the camt.054 / camt.053 entry from the account servicer

The statement is treated as the external source of truth, exactly as it is on a real desk: if the
statement and the internal record disagree, the internal record is the one under suspicion.

Classifications: `MATCHED`, `UNMATCHED`, `AMOUNT_MISMATCH`, `CURRENCY_MISMATCH`, `DUPLICATE`,
`MISSING_ENTRY`, `TIMING_DIFFERENCE`, `REFERENCE_MISMATCH`. Each break records the difference
amount, the **probable cause** and the **recommended action** — for example, an amount mismatch
points at correspondent charges deducted in transit against an SLEV instruction, and tells the
analyst to raise a claim with the deducting agent.

## Features by area

**Payments** — payment simulator with progressive disclosure and the live scheme rulebook alongside;
payment search across reference, end-to-end id, UETR, correlation id, clearing and settlement
references, party name, IBAN, BIC and amount; the payment journey as an interactive process graph.

**Operations** — investigation workbench (expected / actual / probable cause / recommended action,
action log, resolution); exception queues; reconciliation records with the four legs side by side;
unmatched statement entries.

**Messages** — ISO 20022 catalogue and every generated instance; message trace for one payment;
MT → MX mapping reference.

**Schemes** — each rail's limits, scope, timings, settlement behaviour, message set and rule set.

**QA Lab** — 20 executable scenarios with expected-versus-actual assertions; the failure injection
catalogue with its mechanism and expected outcome; a test-case generator that derives real boundary
values from a rule's own parameters and then executes the cases against the engine.

**BA Workbench** — business requirement → functional requirements → business rules → process flow →
acceptance criteria (given/when/then) → exception scenarios → test scenarios → traceability matrix,
all generated from live configuration.

**System** — global event log with filters and a live tail; audit trail (who / what / when / before /
after / why); rule engine with enable-disable; accounts with nostro/vostro explainer and camt.053
generation; effective configuration and the state machine.

**Command centre** — `Ctrl/Cmd + K` accepts references, identifiers, message types and
plain-language intents ("find failed payments", "show unmatched reconciliations", "open pacs.008").

## Local setup

**Requirements:** Python 3.11+ and Node 20+. Nothing else — the default database is SQLite.

```bash
# 1. backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

On first start the application creates the schema, seeds the fictional reference data, the rule book
and the scenario library, then runs the scenarios to build a demo book of 30+ payments.

```bash
# 2. frontend (second terminal)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The dev server proxies `/api` to the backend.

| URL                             | What                       |
| ------------------------------- | -------------------------- |
| http://localhost:5173           | Operations console         |
| http://localhost:8000/docs      | Swagger UI                 |
| http://localhost:8000/redoc     | ReDoc                      |
| http://localhost:8000/health    | Liveness and readiness     |

Or use the start script, which launches both:

```bash
./start.sh          # macOS / Linux
.\start.ps1         # Windows PowerShell
```

### Configuration

Copy `.env.example` to `.env`. Everything has a safe default; no secret is ever committed.

```ini
DATABASE_URL=sqlite+pysqlite:///./data/simulator.db
DEMO_MODE=true                 # seed the demo book, accelerate scheme timings
SIMULATION_SPEED_FACTOR=5      # divide each scheme's threshold by this in demo mode
CLEARING_TIMEOUT_SECONDS=25    # fallback only; each scheme defines its own
SCHEDULER_ENABLED=true
LOG_LEVEL=INFO
LOG_FORMAT=json                # json | text
AI_ENABLED=false               # the payment engine never depends on an LLM
```

### Migrations

```bash
cd backend
alembic upgrade head           # apply
alembic check                  # confirm the models and the migration agree
alembic revision --autogenerate -m "description"
```

## Docker setup

```bash
docker compose up --build
```

Brings up PostgreSQL 16, the API (migrated and seeded on start) and the UI behind Nginx:

| URL                   | What                     |
| --------------------- | ------------------------ |
| http://localhost:8080 | Operations console        |
| http://localhost:8000/docs | API documentation    |

## Testing

```bash
# backend — 300 tests
cd backend
python -m pytest -q
python -m pytest --cov=app --cov-report=term-missing
python -m ruff check app tests

# frontend — 54 tests
cd frontend
npm test
npm run typecheck
npm run lint
```

Backend coverage spans the validation engine (including boundary values and disabled rules), the
state machine, the full lifecycle for every failure path, ISO 20022 message structure, clearing
responses and timeout behaviour, settlement, accounting integrity, reconciliation classification,
failure injection, scenario execution, the test-case generator, the BA package, search, seeding
idempotency and the API surface end to end.

The end-to-end path — create → execute → clearing → settlement → accounting → reconciliation →
completed — is asserted, as are all 20 scenarios and eight distinct failure paths.

## API documentation

66 endpoints under `/api/v1`, documented at `/docs`. Highlights:

```
POST   /api/v1/payments                        create
GET    /api/v1/payments                        search and filter
GET    /api/v1/payments/statistics             portfolio statistics
GET    /api/v1/payments/{id}                   full view, every subsystem
POST   /api/v1/payments/{id}/execute           run the lifecycle
GET    /api/v1/payments/{id}/timeline          journey with stage states
GET    /api/v1/payments/{id}/messages          ISO 20022 messages
GET    /api/v1/payments/{id}/events            event log
GET    /api/v1/payments/{id}/validations       rule results
GET    /api/v1/payments/{id}/accounting        journal + statement entries
GET    /api/v1/payments/{id}/clearing          clearing records
GET    /api/v1/payments/{id}/settlement        settlement records
GET    /api/v1/payments/{id}/reconciliation    reconciliation records
GET    /api/v1/payments/{id}/mt-mx             MT → MX mapping for this payment
GET    /api/v1/payments/{id}/tracking          UETR tracking timeline
POST   /api/v1/payments/{id}/failures          arm a failure injection
POST   /api/v1/payments/{id}/retry             controlled reprocessing
POST   /api/v1/payments/{id}/resolve-timeout   apply the clearing system's late answer
POST   /api/v1/payments/{id}/cancel            send camt.056
POST   /api/v1/payments/{id}/return            apply an inbound pacs.004
POST   /api/v1/payments/{id}/reconcile         re-run reconciliation

GET    /api/v1/investigations                  queue
POST   /api/v1/investigations/{ref}/actions    record an action
POST   /api/v1/investigations/{ref}/resolve    resolve
GET    /api/v1/exceptions                      everything in an exception state
GET    /api/v1/reconciliation                  records and classifications
GET    /api/v1/reconciliation/unmatched        orphan statement entries

GET    /api/v1/schemes · /schemes/{code}       rail configuration
GET    /api/v1/rules · PATCH /rules/{id}       rule book, enable/disable
GET    /api/v1/state-machine                   transitions and stages
GET    /api/v1/events · /audit                 event log, audit trail
GET    /api/v1/accounts · /accounts/{number}   accounts and movements
GET    /api/v1/statement/{number}              generate a camt.053
GET    /api/v1/messages · /messages/catalogue  message explorer
GET    /api/v1/messages/mt-mx                  mapping reference
GET    /api/v1/search                          command centre

GET    /api/v1/scenarios                       library
POST   /api/v1/scenarios/{code}/run            execute with assertions
POST   /api/v1/scenarios/run-all               execute all 20
GET    /api/v1/failure-injections              catalogue
POST   /api/v1/test-cases/generate             generate from a rule
POST   /api/v1/test-cases/run                  execute against the engine
GET    /api/v1/ba/package                      full BA artefact package
```

Errors share one envelope and never leak internals:

```json
{
  "error": {
    "code": "ILLEGAL_STATE_TRANSITION",
    "message": "Transition COMPLETED -> VALIDATING is not permitted by the payment state machine.",
    "requestId": "7f3c…",
    "correlationId": "CORR-…",
    "detail": { "currentStatus": "COMPLETED", "allowedTransitions": ["RETURNED", "REVERSED"] }
  }
}
```

## Database architecture

21 tables. `payment` is the aggregate root; every artefact references it and also carries its own
business reference, so an investigator can search from any direction.

```
bank ──────┬── account ──┬── accounting_entry ──┐
           │             ├── statement_entry ───┤
           └── (correspondent)                  │
                                                │
business_rule        validation_result ─────────┤
                                                │
payment ──┬── payment_party                     │
          ├── payment_stage                     ├──▶ reconciliation_record ──▶ investigation
          ├── payment_message                   │
          ├── payment_event                     │
          ├── clearing_transaction ─────────────┤
          ├── settlement_transaction ───────────┘
          ├── failure_injection
          └── scheduled_job

scenario ──▶ scenario_execution        test_case        audit_event
```

`correlation_id` is stamped on the payment and copied onto every event and message. Enum values are
stored as short strings rather than database enums, so adding a status or a rail needs no type
migration. Monetary columns use a portable type that stores exact decimals on PostgreSQL (NUMERIC)
and as scaled integers on SQLite, keeping amounts sortable and range-queryable without ever touching
a float.

The full model, with indexes and the event flow, is in [`docs/architecture.md`](docs/architecture.md).

## Demo scenarios

The control room has one-click launchers; the QA Lab runs any scenario, or all 20 at once with
expected-versus-actual assertions.

| #  | Scenario                                             | Ends as                  |
| -- | ---------------------------------------------------- | ------------------------ |
| 01 | Successful instant payment (SIC)                     | COMPLETED                |
| 02 | Invalid IBAN                                         | REJECTED                 |
| 03 | Duplicate payment                                    | REJECTED                 |
| 04 | Embargo hit                                          | INVESTIGATION_REQUIRED   |
| 05 | Clearing rejection                                   | CLEARING_REJECTED        |
| 06 | Clearing timeout                                     | INVESTIGATION_REQUIRED   |
| 07 | pacs.002 delayed                                     | COMPLETED                |
| 08 | Customer debited but clearing rejected               | CLEARING_REJECTED        |
| 09 | Clearing accepted but beneficiary not credited       | INVESTIGATION_REQUIRED   |
| 10 | Settlement completed but internal status pending     | INVESTIGATION_REQUIRED   |
| 11 | Settlement completed but camt.054 missing            | INVESTIGATION_REQUIRED   |
| 12 | Statement contains an unmatched transaction          | COMPLETED (+ orphan)     |
| 13 | Amount mismatch                                      | INVESTIGATION_REQUIRED   |
| 14 | Currency mismatch                                    | INVESTIGATION_REQUIRED   |
| 15 | Accounting entry missing                             | INVESTIGATION_REQUIRED   |
| 16 | Duplicate settlement                                 | INVESTIGATION_REQUIRED   |
| 17 | Payment returned                                     | RETURNED                 |
| 18 | Cancellation request                                 | INVESTIGATION_REQUIRED   |
| 19 | Investigation required — malformed status report      | INVESTIGATION_REQUIRED   |
| 20 | Successful end-to-end cross-border payment           | COMPLETED                |

Each scenario declares preconditions, input data, execution steps, expected status, expected
messages, expected accounting, expected reconciliation and the conditions under which it fails —
and the runner compares all of it against what the engine actually did.

### A five-minute tour

1. **Control room** → *Run successful SIC payment*. Open the payment and walk the journey.
2. Switch to **Technical** mode in the top bar; the same screen now shows system states, owners and
   payloads.
3. Open the **Messages** tab, pick the pacs.008, and look at *Field mapping*.
4. Back on the control room → *Simulate clearing timeout*. Open the payment: the clearing-response
   stage explains what was expected, what happened, and that the instruction must not be re-sent.
5. Open the **investigation** it raised, then use *Apply clearing answer* to resolve it and watch the
   lifecycle continue from settlement.
6. **QA Lab → Scenarios → Run the whole library**: 20 scenarios, expected versus actual.
7. **QA Lab → Test cases**: generate from `SIC-AMOUNT-001` and run the suite. The boundary values
   (19,999.99 / 20,000.00 / 20,000.01) come from the rule's own parameters.
8. **BA Workbench**: pick SWIFT, open the traceability matrix.

## Screens

| Screen | What it shows |
| ------ | ------------- |
| ![Control room](docs/screenshots/control-room.png) | Operational posture, queues, demo launchers |
| ![Payment journey](docs/screenshots/payment-journey.png) | The lifecycle as a process graph with per-stage detail |
| ![Failure report](docs/screenshots/failure-report.png) | What happened / where / why / expected / actual / next action |
| ![Message viewer](docs/screenshots/message-viewer.png) | Business, payload, mapping, validation and timeline views |
| ![Reconciliation](docs/screenshots/reconciliation.png) | The four legs side by side with the probable cause |
| ![BA workbench](docs/screenshots/ba-workbench.png) | Requirements and the traceability matrix |

## Known limitations

These are deliberate boundaries, not defects:

- **Single tenant, no authentication.** Audit records carry an actor and the model is ready for
  multi-user, but there is no login. Do not expose this to a network you do not control.
- **Screening is a toy.** A handful of fictional list entries and exact-match logic. Real screening
  uses licensed watch-list data, fuzzy matching, alert queues and a human disposition workflow.
- **Messages are not XSD-validated.** They are structurally realistic and never transmitted. There
  is no schema validation against the official ISO 20022 XSDs.
- **One payment per message.** No batch pacs.008, no bulk files, no pain.001 initiation layer.
- **Reconciliation is one-to-one.** No many-to-many matching across batches, no tolerance rules, no
  ageing.
- **Accounting is a single journal per payment.** No charge or FX legs, no accrual accounting, no
  end-of-day cut-off, no multi-currency position keeping.
- **FX rates are fixed and invented.** Used only to let a cross-currency settlement be demonstrated.
- **Scheme values are plausible, not authoritative.** Real rulebooks are owned by their operators,
  change over time and contain far more detail.
- **Clearing is in-process.** A real adapter would speak a network protocol with mutual
  authentication, message signing and store-and-forward semantics.
- **The scheduler is single-process.** It is durable and restart-safe, but it does not coordinate
  across replicas.
- **No AI features are enabled.** The hooks and configuration exist; the payment engine never
  depends on an LLM, and nothing in this build calls one.

## Future enhancements

- pain.001 / pain.002 customer initiation layer, so the chain starts at the channel
- Batch and bulk file processing, with batch-level and transaction-level status
- XSD validation of generated messages against the official ISO 20022 schemas
- Request-for-payment (pain.013/014) and direct debit (pacs.003) flows
- Many-to-many reconciliation with tolerance and ageing rules
- Charge and FX legs on the accounting journal, plus intraday liquidity positions
- Multi-user with roles (operations, compliance, finance, QA) over the existing audit model
- Optional AI assist: explain this failure, summarise this investigation, suggest a root cause —
  always clearly labelled and never able to change payment state
- Scheme plug-ins loaded from configuration rather than code, so a rail can be added without a deploy

---

## Repository layout

```
payments-transformation-simulator/
├── backend/
│   ├── app/
│   │   ├── api/            REST layer: routers, schemas, serializers, errors, middleware
│   │   ├── core/           config, structured logging, identifier generation
│   │   ├── db/             models, session, portable column types, bootstrap
│   │   ├── domain/         enums, money, IBAN/BIC
│   │   ├── schemes/        rail definitions and the registry
│   │   ├── engines/        validation, compliance, messaging, clearing, settlement,
│   │   │                   accounting, reconciliation, investigation, failure injection,
│   │   │                   state machine, orchestrator, scheduler, events
│   │   ├── services/       payment, scenario, test case, BA, search
│   │   ├── seed/           fictional reference data, rule sync, scenarios, demo book
│   │   └── main.py
│   ├── alembic/            migrations
│   └── tests/              300 tests
├── frontend/
│   └── src/
│       ├── api/            client and response types
│       ├── components/     shell, journey graph, message viewer, command palette, primitives
│       ├── pages/          20 screens
│       ├── lib/            formatting and status tones
│       ├── hooks/          data loading
│       └── styles/         design tokens and the component system
├── docs/
│   ├── architecture.md
│   ├── payments-domain.md
│   └── assumptions.md
├── docker/
├── docker-compose.yml
├── .env.example
├── start.sh · start.ps1
└── README.md
```
