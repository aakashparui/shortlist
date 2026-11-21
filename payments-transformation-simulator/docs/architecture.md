# Architecture

> This document describes how the Payments Transformation Simulator is built and why. For what the
> payment concepts mean, see [`payments-domain.md`](payments-domain.md). For the engineering
> decisions taken where the brief was silent, see [`assumptions.md`](assumptions.md).

---

## Contents

1. [System architecture](#system-architecture)
2. [Component diagram](#component-diagram)
3. [Payment lifecycle](#payment-lifecycle)
4. [State machine](#state-machine)
5. [Database model](#database-model)
6. [API architecture](#api-architecture)
7. [Event flow](#event-flow)
8. [Asynchronous processing](#asynchronous-processing)
9. [Failure handling](#failure-handling)
10. [Reconciliation architecture](#reconciliation-architecture)
11. [Scheme plug-in architecture](#scheme-plug-in-architecture)
12. [Observability](#observability)
13. [Security considerations](#security-considerations)
14. [Design decisions](#design-decisions)

---

## System architecture

A **modular monolith** backend plus a separate single-page frontend.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Browser                                                                     │
│  React 18 + TypeScript · Vite · react-router · no global state library       │
│  ┌────────────┬─────────────┬────────────┬───────────┬─────────────────────┐ │
│  │ Control    │ Payment     │ Operations │ Messages  │ QA Lab ·  BA        │ │
│  │ room       │ journey     │ workbench  │ explorer  │ workbench · System  │ │
│  └────────────┴─────────────┴────────────┴───────────┴─────────────────────┘ │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    │ REST, JSON, /api/v1
┌───────────────────────────────────▼──────────────────────────────────────────┐
│  FastAPI application                                                         │
│                                                                              │
│  middleware  RequestContext (request id, correlation id, timing)             │
│              RateLimit (fixed window, per client)                            │
│              CORS                                                            │
│  errors      one envelope, structured detail, no internals leaked            │
│                                                                              │
│  routers     payments · operations · qa · ba · system                        │
│  schemas     Pydantic v2 request models (first line of input validation)     │
│  serializers ORM → camelCase response shaping                                │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────┐
│  Service layer                                                               │
│  PaymentService · ScenarioService · TestCaseService · BaService · Search     │
│  (input mapping, identifier assignment, querying, aggregate views)           │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────┐
│  PaymentOrchestrator — the only component that changes payment status        │
└──┬───────┬────────┬────────┬────────┬────────┬────────┬────────┬─────────────┘
   │       │        │        │        │        │        │        │
┌──▼──┐ ┌──▼───┐ ┌──▼───┐ ┌──▼───┐ ┌──▼───┐ ┌──▼───┐ ┌──▼───┐ ┌──▼──────────┐
│Rule │ │Comp- │ │Msg   │ │Clear-│ │Settle│ │Acct  │ │Recon │ │Investigation│
│eng. │ │liance│ │eng.  │ │ing   │ │ment  │ │      │ │      │ │desk         │
└─────┘ └──────┘ └──────┘ └──┬───┘ └──────┘ └──────┘ └──────┘ └─────────────┘
                             │
                   ┌─────────▼──────────┐
                   │ SimulatedClearing  │  deterministic decisions,
                   │ System             │  driven by scheme profile + injections
                   └────────────────────┘

   cross-cutting   StateMachine · EventRecorder · AuditTrail · FailureInjection
┌──────────────────────────────────────────────────────────────────────────────┐
│  Persistence — SQLAlchemy 2 · Alembic · 21 tables                            │
│  SQLite (local, zero setup) · PostgreSQL (docker, production target)         │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼──────────────────────────────────────────┐
│  Scheduler — background thread polling the `scheduled_job` table             │
│  delayed clearing responses · timeout detection                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Why a modular monolith

A microservice split would buy independent deployment and scaling. Neither matters here: the whole
system is one operator's console over one database, and the interesting behaviour is the
*interaction* between validation, clearing, settlement, accounting and reconciliation. Splitting
them across processes would add network failure modes that are not the ones this tool exists to
teach, and would make the single most valuable feature — tracing one payment across every
subsystem — harder rather than easier.

The boundaries are still real. Each engine owns its tables, exposes a narrow interface and is
constructed with a session. Lifting one into its own service would be a refactor, not a rewrite.

## Component diagram

| Component | Module | Responsibility | Talks to |
| --------- | ------ | -------------- | -------- |
| **Orchestrator** | `engines/orchestrator.py` | Drives the lifecycle; the only writer of `payment.status` | every engine |
| **Validation engine** | `engines/validation/` | Executes the rule book for a stage, persists one result per rule | rule book, DB |
| **Rule book** | `engines/validation/rules.py` | Declarative rule definitions + evaluator functions | — |
| **Compliance engine** | `engines/compliance.py` | Screens parties, agents and remittance against fictional lists | DB |
| **Message engine** | `engines/messaging/` | Builds, validates and persists ISO 20022 messages | validation engine |
| **Clearing adapter** | `engines/clearing.py` | Dispatches to, and interprets responses from, the simulated clearing system | simulated clearing system |
| **Settlement engine** | `engines/settlement.py` | Effects settlement across the settlement or nostro account | DB |
| **Accounting engine** | `engines/accounting.py` | Posts and reverses double-entry journals, maintains balances | DB |
| **Statement feed** | `engines/reconciliation.py` | Turns a posted journal into externally visible statement entries | DB |
| **Reconciliation engine** | `engines/reconciliation.py` | Compares the four views, classifies differences | DB |
| **Investigation desk** | `engines/investigation.py` | Opens, annotates and resolves cases | DB |
| **Failure injection** | `engines/failure_injection.py` | Mutates input or configures downstream behaviour | payment, engines |
| **State machine** | `engines/state_machine.py` | Permitted transitions; raises on an illegal one | — |
| **Event recorder** | `engines/events.py` | `PaymentEvent` per action, `AuditEvent` per operator change | DB |
| **Scheduler** | `engines/scheduler.py` | Executes due `scheduled_job` rows in a background thread | orchestrator |
| **Scheme registry** | `schemes/` | Rail configuration and lookup | — |

### Dependency direction

```
api  →  services  →  orchestrator  →  engines  →  db
                           ↓
                     scheme registry (pure configuration, no dependencies)
```

Nothing below a layer imports from above it. The engines know about the database and about each
other's result objects; they know nothing about FastAPI, HTTP or the frontend.

## Payment lifecycle

Thirteen stages, each persisted as a `payment_stage` row with its own state, timing and detail.

| # | Stage | Owner system | Produces |
| - | ----- | ------------ | -------- |
| 1 | `INITIATION` | Channel | Payment record, references assigned |
| 2 | `CHANNEL_INTAKE` | Channel | Correlation id; any data injections applied here |
| 3 | `PRE_VALIDATION` | Validation engine | Technical and structural rule results |
| 4 | `BUSINESS_VALIDATION` | Validation engine | Business, scheme, account and duplicate results |
| 5 | `COMPLIANCE` | Compliance engine | Screening results; a blocking hit stops here |
| 6 | `ORCHESTRATION` | Orchestrator | Routing decision, timeout threshold |
| 7 | `MESSAGE_GENERATION` | Message engine | pacs.008 (+ MT103 on the cross-border rail) |
| 8 | `CLEARING` | Clearing adapter | `clearing_transaction` with a clearing reference |
| 9 | `CLEARING_RESPONSE` | Clearing system | pacs.002, or a timeout and a pacs.028 |
| 10 | `SETTLEMENT` | Settlement engine | `settlement_transaction` with a reference |
| 11 | `ACCOUNTING` | Accounting engine | Journal + camt.054 notification + statement entries |
| 12 | `RECONCILIATION` | Reconciliation engine | `reconciliation_record` with a classification |
| 13 | `COMPLETION` | Orchestrator | Terminal status |

A stage that is never reached is marked `SKIPPED` with a reason, not left `PENDING`. The difference
matters to an investigator: `PENDING` means "still coming", `SKIPPED` means "will never happen,
because the payment stopped earlier".

### Sequence — the happy path

```
Operator        API            Orchestrator      Engines                Clearing
   │             │                   │              │                      │
   │ POST /payments                  │              │                      │
   │────────────▶│ create ──────────▶│              │                      │
   │             │                   │ ensure stages│                      │
   │◀────────────│ 201 (INITIATED)   │              │                      │
   │ POST /{id}/execute              │              │                      │
   │────────────▶│──────────────────▶│              │                      │
   │             │                   │ apply injections                    │
   │             │                   │─────────────▶│ (mutate instruction) │
   │             │                   │ pre-validation                      │
   │             │                   │─────────────▶│ 12 rules             │
   │             │                   │ business validation                 │
   │             │                   │─────────────▶│ 9 rules              │
   │             │                   │ compliance   │                      │
   │             │                   │─────────────▶│ screening            │
   │             │                   │ generate pacs.008                   │
   │             │                   │─────────────▶│ + message validation │
   │             │                   │ dispatch ─────────────────────────▶ │
   │             │                   │              │      decision: ACCEPT│
   │             │                   │◀────────────────────── pacs.002 ACSC│
   │             │                   │ settle ─────▶│                      │
   │             │                   │ post journal▶│                      │
   │             │                   │ publish statement entry + camt.054  │
   │             │                   │ reconcile ──▶│ MATCHED              │
   │◀────────────│ 200 (COMPLETED)   │              │                      │
```

In `SIMULATED` mode the dispatch step schedules the response and the timeout check instead of
running them inline; the API returns immediately and the UI polls the timeline.

## State machine

`engines/state_machine.py` holds one table: for each status, the set of statuses it may move to.
`assert_transition` raises `IllegalTransitionError`, which the API turns into `409 Conflict` with
the permitted targets in the body.

```
                      ┌─────────┐
                      │  DRAFT  │
                      └────┬────┘
                           ▼
                     ┌───────────┐
                     │ INITIATED │
                     └─────┬─────┘
                           ▼
                    ┌─────────────┐        ┌──────────┐
                    │ VALIDATING  ├───────▶│ REJECTED │◀──────┐
                    └──────┬──────┘        └────┬─────┘       │
                           ▼                    │             │
                    ┌─────────────┐             ▼             │
                    │  VALIDATED  │       ┌──────────────┐    │
                    └──────┬──────┘       │ REPROCESSING │────┘
                           ▼              └──────▲───────┘
                  ┌──────────────────┐           │
                  │ COMPLIANCE_CHECK ├──▶ BLOCKED┤
                  └────────┬─────────┘           │
                           ▼                     │
                 ┌───────────────────┐           │
                 │ MESSAGE_GENERATED │           │
                 └─────────┬─────────┘           │
                           ▼                     │
                 ┌───────────────────┐           │
                 │ SENT_TO_CLEARING  │           │
                 └──┬─────────┬──────┴───────┐   │
                    ▼         ▼              ▼   │
       ┌────────────────┐ ┌───────────┐ ┌─────────────────────────┐
       │CLEARING_REJECTED│ │ TIMED_OUT ├▶│ INVESTIGATION_REQUIRED  │
       └────────┬────────┘ └───────────┘ └───────────┬─────────────┘
                ▼                                    │
          ┌──────────┐                               │ (resolution)
          │ REVERSED │                               │
          └──────────┘                               ▼
                 ┌──────────────────┐        ┌───────────────┐
                 │ CLEARING_ACCEPTED├───────▶│ SETTLEMENT_   │
                 └──────────────────┘        │ PENDING       │
                                             └───────┬───────┘
                        ┌────────────────────────────┤
                        ▼                            ▼
              ┌───────────────────┐           ┌───────────┐
              │ SETTLEMENT_FAILED │           │  SETTLED  │
              └───────────────────┘           └─────┬─────┘
                                     ┌──────────────┤
                                     ▼              ▼
                        ┌──────────────────┐  ┌───────────┐
                        │ ACCOUNTING_BREAK │  │ ACCOUNTED │
                        └──────────────────┘  └─────┬─────┘
                                     ┌──────────────┤
                                     ▼              ▼
                     ┌──────────────────────┐ ┌────────────┐
                     │ RECONCILIATION_BREAK │ │ RECONCILED │
                     └──────────────────────┘ └──────┬─────┘
                                                     ▼
                                              ┌───────────┐
                                              │ COMPLETED ├──▶ RETURNED / REVERSED
                                              └───────────┘
```

Three properties this buys:

- **Retry cannot launder a failure.** `REJECTED → REPROCESSING → VALIDATING` re-runs the real rules.
  If the data is still wrong the payment is rejected again.
- **An investigation cannot be skipped.** `INVESTIGATION_REQUIRED` only leads onward through states
  that correspond to an actual resolution.
- **Terminal means terminal.** `CANCELLED` has no outgoing transitions at all.

A small number of transitions are applied with `force=True` where the orchestrator has already
established the facts (for example moving into `INVESTIGATION_REQUIRED` from a break state). These
are deliberate and localised; everything an operator triggers goes through the check.

## Database model

21 tables. `payment` is the aggregate root.

```
┌──────────────┐        ┌──────────────────┐
│     bank     │◀───────┤     account      │──────┐
│  bic (uq)    │  bank  │  account_number  │      │
│  country     │  corr. │  iban · type     │      │
└──────────────┘        │  currency        │      │
                        │  balance         │      │
                        └────────┬─────────┘      │
                                 │                │
   ┌─────────────────────────────┼────────────────┼─────────────────────┐
   │                             │                │                     │
┌──▼──────────────┐    ┌─────────▼────────┐  ┌────▼──────────────┐      │
│accounting_entry │    │ statement_entry  │  │settlement_        │      │
│ entry_id        │    │ statement_ref    │  │transaction        │      │
│ side · amount   │    │ side · amount    │  │ settlement_ref    │      │
│ balance_after   │    │ end_to_end_id    │  │ status · amounts  │      │
└──────┬──────────┘    │ is_orphan        │  └────┬──────────────┘      │
       │               └─────────┬────────┘       │                     │
       │                         │                │                     │
┌──────▼─────────────────────────▼────────────────▼─────────────────────▼──┐
│                                payment                                   │
│  reference (uq) · correlation_id · scheme · status · previous_status     │
│  amount · currency · instruction_id · end_to_end_id · transaction_id     │
│  uetr · purpose_code · service_level · charge_bearer · clearing_channel  │
│  debtor_account_id · retry_count · failure_summary · scenario_code       │
└──┬────────┬──────────┬───────────┬────────────┬──────────┬──────────────┘
   │        │          │           │            │          │
┌──▼────┐┌──▼──────┐┌──▼────────┐┌─▼─────────┐┌─▼────────┐┌▼──────────────┐
│payment││payment  ││payment    ││payment    ││validation││clearing_      │
│_party ││_stage   ││_message   ││_event     ││_result   ││transaction    │
│ role  ││ stage   ││ msg type  ││ seq       ││ rule_id  ││ clearing_ref  │
│ name  ││ state   ││ message_id││ type      ││ status   ││ status        │
│ iban  ││ detail  ││ xml       ││ source    ││ severity ││ decision      │
│ bic   ││ summary ││ mappings  ││ severity  ││ actual   ││ timeout_at    │
└───────┘└─────────┘└───────────┘└───────────┘│ expected ││ latency_ms    │
                                              └──────────┘└───────────────┘
   │                                   │
┌──▼──────────────────┐   ┌────────────▼────────┐   ┌──────────────────┐
│reconciliation_record│──▶│   investigation     │   │failure_injection │
│ reference · status  │   │ reference · reason  │   │ code · category  │
│ 4 leg amounts       │   │ expected · actual   │   │ parameters       │
│ difference_amount   │   │ probable_cause      │   │ active · consumed│
│ probable_cause      │   │ recommended_action  │   │ effect_summary   │
│ recommended_action  │   │ actions[]           │   └──────────────────┘
│ legs[]              │   └─────────────────────┘
└─────────────────────┘

┌──────────────┐   ┌───────────────────┐   ┌───────────┐   ┌──────────────┐
│business_rule │   │scenario           │──▶│scenario_  │   │ scheduled_job│
│ rule_id (uq) │   │ code (uq)         │   │execution  │   │ job_type     │
│ category     │   │ input_data        │   │ assertions│   │ due_at       │
│ severity     │   │ failure_codes     │   │ outcome   │   │ status       │
│ enabled      │   │ expected_*        │   └───────────┘   │ payload      │
└──────────────┘   └───────────────────┘                   └──────────────┘

┌──────────────┐   ┌──────────────────────────────────────────────────────┐
│  test_case   │   │ audit_event  actor · action · entity · before · after │
└──────────────┘   └──────────────────────────────────────────────────────┘
```

### Portable exact money

`db/types.py` defines a `Money` column type that stores `NUMERIC(20,4)` on PostgreSQL and a scaled
`BIGINT` on SQLite. Amounts are therefore exact on both, and remain sortable and range-queryable in
SQL — which a `TEXT` column would not be. No float ever touches a monetary value.

`UTCDateTime` does the same job for timestamps, always returning timezone-aware UTC even on SQLite.

### Indexing

Composite indexes follow the actual query patterns: `(status, created_at)` and `(scheme, status)` on
`payment`, `(payment_id, sequence)` on `payment_event`, `(status, due_at)` on `scheduled_job`,
`(status, created_at)` on `reconciliation_record`. Every business reference an investigator can
search by — `reference`, `end_to_end_id`, `instruction_id`, `transaction_id`, `uetr`,
`correlation_id`, `clearing_reference`, `settlement_reference` — is indexed.

### Enum storage

Statuses and categories are stored as short strings, not database enums. Adding a status or a rail
then needs no type migration, and the application remains the single authority on the vocabulary.

## API architecture

66 endpoints under `/api/v1`, documented at `/docs` (Swagger) and `/redoc`.

**Request path**

```
HTTP → RateLimit → RequestContext → CORS → router
                                             ↓
                                      Pydantic model (reject malformed early)
                                             ↓
                                      dependency: Session per request
                                             ↓
                                      Service → Orchestrator → Engines
                                             ↓
                                      serializer → camelCase JSON
```

Sessions are per-request and committed on success, rolled back on any exception. A failed request
therefore leaves no half-written payment behind.

**Error envelope** — one shape for every failure, with a request id the operator can quote and no
internal detail:

```json
{ "error": { "code": "…", "message": "…", "requestId": "…", "correlationId": "…", "detail": … } }
```

`422` carries field-level validation detail; `409` on an illegal transition carries the permitted
targets, so the UI can show what *is* possible.

**Versioning** — the prefix is configuration (`API_V1_PREFIX`). A v2 would mount a second router
alongside rather than breaking v1.

## Event flow

Every meaningful action produces a `PaymentEvent`:

```
PAYMENT_CREATED · STAGE_STARTED · STAGE_COMPLETED · STAGE_FAILED · STATUS_CHANGED
VALIDATION_EXECUTED · VALIDATION_FAILED · COMPLIANCE_SCREENED
MESSAGE_GENERATED · MESSAGE_SENT · MESSAGE_RECEIVED
CLEARING_DISPATCHED · CLEARING_RESPONSE · CLEARING_TIMEOUT
SETTLEMENT_POSTED · SETTLEMENT_FAILED · ACCOUNTING_POSTED · ACCOUNTING_BREAK
RECONCILIATION_RUN · RECONCILIATION_BREAK
INVESTIGATION_OPENED/UPDATED/RESOLVED · FAILURE_INJECTED · RETRY_REQUESTED
CANCELLATION_REQUESTED · PAYMENT_RETURNED · SCENARIO_EXECUTED
```

Each carries a monotonic per-payment `sequence`, the source system, a severity, the stage, a
summary and a structured detail object. The sequence is what makes the event log a reliable
narrative rather than a timestamp-ordered guess.

Operator changes additionally produce an `AuditEvent` with **who / what / when / before / after /
why**. Rule toggles, retries, cancellations, returns and investigation actions are all audited.

A typical completed payment produces around 30 events:

```
10:42:01.120  CHANNEL              Payment TXN-10001 created for 4850.00 CHF
10:42:01.131  VALIDATION_ENGINE    12 rules executed, 0 failed
10:42:01.140  VALIDATION_ENGINE    9 rules executed, 0 failed
10:42:01.148  COMPLIANCE_ENGINE    Screening complete: 0 hit(s)
10:42:01.155  MESSAGE_ENGINE       pacs.008 PACS008-… generated
10:42:01.161  CLEARING_ADAPTER     pacs.008 sent, reference SIC-26001-…
10:42:03.166  CLEARING_SYSTEM      pacs.002 received: ACSC
10:42:03.180  SETTLEMENT_ENGINE    Settlement STL-… SETTLED for 4850.00 CHF
10:42:03.191  ACCOUNTING_ENGINE    Journal ACC-… posted with 2 entries
10:42:03.199  ACCOUNTING_ENGINE    camt.054 … notifies entry STMT-8801
10:42:03.210  RECONCILIATION_ENGINE Reconciliation RECON-…: MATCHED
10:42:03.215  ORCHESTRATOR         Status RECONCILED -> COMPLETED
```

## Asynchronous processing

Two processing modes:

| Mode | Used by | Behaviour |
| ---- | ------- | --------- |
| `IMMEDIATE` | tests, QA Lab, scenario runs, seeding | Whole lifecycle inline, no artificial delay |
| `SIMULATED` | the UI | Clearing response and timeout handed to the scheduler |

In `SIMULATED` mode the clearing adapter writes two `scheduled_job` rows — one to deliver the
response, one to check for a timeout — and the API returns. A background thread polls for due jobs,
claims them in their own transaction (`PENDING → RUNNING`), and runs them through the orchestrator.

**Why a durable job table rather than in-memory timers**

- Pending work is visible: the payment view lists the next scheduled job and its due time.
- A restart does not lose a payment mid-flight.
- Tests can drive the same code path synchronously with `scheduler.drain()`, so the asynchronous
  path is covered by the same assertions as the synchronous one.
- A job that raises is marked `FAILED` with the error recorded, and never takes the worker down.

The clearing timeout threshold comes from the **scheme profile**, not a global constant. In demo
mode it is divided by `SIMULATION_SPEED_FACTOR`, and both the accelerated and the realistic value
are shown wherever a timeout is reported.

## Failure handling

### Principle

An injection changes an **input** or the **behaviour of a downstream system**. It never writes a
failure result directly. The consequence is that every failure in this system is produced by the
same code path that would produce it in anger, and can be explained in terms of the rule or the
message that caused it.

```
registered injection
        │
        ├── data injection ──────▶ mutates the instruction at CHANNEL_INTAKE
        │                         (records before → after on the audit trail)
        │                                │
        │                                ▼
        │                         the real rule fires → real ValidationResult
        │
        ├── clearing injection ──▶ configures SimulatedClearingSystem's decision
        │                                │
        │                                ▼
        │                         a real pacs.002 RJCT / no response at all
        │
        └── downstream injection ─▶ consumed by settlement / accounting /
                                    statement feed when that engine runs
```

### What a failure reports

Every failed stage records six things, and the UI renders them together:

1. **What happened** — the stage summary
2. **Where** — the stage key
3. **Why** — the failure reason
4. **Expected vs actual** — the concrete values
5. **What message was generated** — if any
6. **What state the payment entered, and the next possible action**

### Defensive behaviour

- A rule whose evaluator raises is caught, recorded as a failure naming the exception, and does not
  kill the payment.
- A scheduled job that raises is marked `FAILED` with the error; the worker continues.
- Structured logging cannot crash its caller: a `SafeLogger` renames `extra` keys that would collide
  with `LogRecord` attributes instead of raising.
- Seeding is idempotent, and re-syncing the rule book never silently re-enables a rule an operator
  disabled.

## Reconciliation architecture

```
   internal payment record ─┐
   accounting journal ──────┤
   clearing transaction ────┼──▶ ReconciliationEngine ──▶ classification
   statement entry ─────────┘            │                 + difference
   (camt.054 / camt.053)                 │                 + probable cause
                                         │                 + recommended action
                                         ▼
                                 reconciliation_record
                                         │
                            (if a break) ▼
                                   investigation
```

Classification order matters, and reflects how an analyst actually reasons:

1. **Ledger integrity first.** A journal that does not balance is a break regardless of what the
   statement says — a missing credit leg, a duplicate posting, a currency or amount mismatch between
   legs.
2. **Then the statement.** No entry → `MISSING_ENTRY`. More than one → `DUPLICATE`. Different
   currency → `CURRENCY_MISMATCH`. Different amount → `AMOUNT_MISMATCH` with the difference.
   Different reference → `REFERENCE_MISMATCH`. Different booking period → `TIMING_DIFFERENCE`.
3. **Otherwise** `MATCHED`.

A reconciliation match never closes a payment whose journal is broken: if the ledger disagrees with
itself, the payment goes to investigation even though the external records agree.

Statement entries with no internal payment at all are kept as orphans and surfaced in their own
queue — the external-side half of the same problem.

## Scheme plug-in architecture

```
PaymentScheme
   ├── SchemeRules        currencies · amount limits · country scope · remittance
   │                      limit · duplicate window · cut-off · future dating ·
   │                      service levels · charge bearers · UETR · cancellation
   ├── MessageRules       which ISO messages, which namespaces, settlement method,
   │                      clearing system proprietary code, legacy equivalent
   ├── ClearingProfile    clearing system name · response time · timeout ·
   │                      investigation threshold · finality · operating hours ·
   │                      rejection reason codes
   ├── SettlementProfile  settlement method · account type · value date offset
   └── validation_rule_ids  the ordered rule set that applies
```

Adding a rail: write one module, add it to `ALL_SCHEMES`. The orchestrator, the engines, the API and
the UI pick it up with no further change — the scheme dropdown, the rulebook panel, the BA package
and the test-case generator are all driven from the registry.

Rules restricted to a rail declare it (`schemes=("SIC_INSTANT",)`); `rules_for_scheme` resolves the
intersection, so a shared rule id can carry rail-specific parameters.

## Observability

**Structured logging** — every line carries `request_id`, and where known `correlation_id` and
`payment_id`, propagated through `contextvars` so the context follows the work without being passed
as an argument. JSON by default, human-readable text for local work.

```json
{"timestamp":"2026-01-01T10:42:03.166Z","level":"INFO","service":"payments-simulator",
 "logger":"app.engines.clearing","operation":"dispatch","message":"dispatched to clearing",
 "request_id":"7f3c…","correlation_id":"CORR-…","payment_id":"TXN-10001",
 "clearing_reference":"SIC-26001-…","decision":"ACCEPT","timeout_seconds":5.0}
```

**Request logging** — method, path, status and duration for every request, with the request id
echoed in the `x-request-id` response header.

**Health** — `/health` reports application and database state and is suitable as a readiness probe.

**In-application observability** — the event log and audit trail are first-class features, not just
diagnostics: filtering, a live tail, and per-payment correlation are part of the product.

## Security considerations

This is a local simulator with no authentication, and should not be exposed to an untrusted network.
Within that boundary the practices that matter are applied, and nothing is security theatre:

- **No secrets in source.** Every setting comes from the environment. `alembic.ini` deliberately
  carries no URL. `.env` is ignored; `.env.example` documents the shape.
- **Input validation in depth.** Pydantic models reject malformed requests (`extra="forbid"`, length
  and range bounds) before any engine runs, and the rule book validates the business content.
- **Error sanitisation.** Responses carry a code, a message and a request id. Stack traces and
  database errors go to the log, never to the client.
- **CORS** is an explicit allow-list from configuration, not `*`.
- **Rate limiting** is a fixed window per client, enabled by default. It protects a local demo from a
  runaway client; real rate limiting belongs at a gateway, and the code says so.
- **Page-size caps** prevent an unbounded result set from being requested.
- **SQL injection** is structurally prevented: every query is built with SQLAlchemy constructs and
  bound parameters.
- **Audit trail** records who changed what, when, from what, to what, and why.
- **No real data.** All reference data is fictional, and the UI says so persistently in the status
  bar rather than once in a corner.

## Design decisions

| Decision | Alternative | Why |
| -------- | ----------- | --- |
| Modular monolith | Microservices | The valuable feature is cross-subsystem tracing; a split adds failure modes that are not the point |
| Durable job table | In-memory timers / Celery | Visible, restart-safe, testable synchronously, no broker to run |
| Synchronous SQLAlchemy | Async SQLAlchemy | The workload is one operator's console; sync keeps the engines readable and the transaction boundaries obvious |
| Rules as code + metadata table | Rules as data in the DB | Evaluators stay type-checked and testable; the table carries only the inspectable metadata and the enable flag |
| Injections mutate input | Injections write results | A faked result teaches nothing; a mutated input produces a real, explainable failure |
| Explicit state machine | Status as a free string | Makes "retry cannot launder a failure" a property of the system, not a convention |
| `Money` column type | `Float` / `Numeric` / `TEXT` | Exact on both backends, sortable in SQL, no float anywhere near money |
| Hand-written CSS | Tailwind / component library | The brief is a dense operations console; a utility framework or a generic component library would have pulled the design toward a SaaS dashboard |
| No frontend state library | Redux / React Query | The console is read-mostly over a live engine; a cache would show remembered state where the operator needs current state |
| Per-request session | Shared session | A failed request rolls back cleanly and leaves no half-written payment |
| `SKIPPED` stages | Leave stages `PENDING` | An investigator must be able to tell "still coming" from "will never happen" |
| Scheme timeouts per rail | One global timeout | A global constant would make every rail behave the same, which is the opposite of the point |
