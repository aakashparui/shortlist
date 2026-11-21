# Assumptions and decisions

Where the brief was silent, a decision was taken and recorded here. Each entry states what was
assumed, why, and what would change if the assumption turned out to be wrong.

---

## Domain assumptions

### Scheme limits and timings are plausible, not authoritative

**Assumed:** CHF 20,000 for the domestic instant rail, EUR 100,000 for SEPA Instant, 25s / 20s /
60s / 30s response thresholds.

**Why:** Real rulebooks are owned by their operators, are revised, and in several cases are not
public in full. Hard-coding a specific published figure would make the simulator look authoritative
about something it cannot keep current.

**Mitigation:** Every scheme carries a `simulationNotes` string that says so, shown in the UI
wherever the rail is described. All values are configuration in one module.

### The reference data is entirely fictional

**Assumed:** Invented institutions, BICs, IBANs, account numbers, customers and screening lists.

**Why:** Using a real BIC or a real bank name would imply a relationship that does not exist, and
would make a screenshot of this tool misleading.

**Mitigation:** The BICs follow the ISO 9362 *structure* but are not registered codes. The IBANs are
computed so their check digits genuinely validate — otherwise the IBAN rule could never pass. The
bank directory says in its own payload that every institution listed is fictional, and the status
bar carries a persistent "SIMULATED ENVIRONMENT · FICTIONAL DATA" marker.

### Embargo country codes are invented

**Assumed:** `ZZ`, `XA`, `QX` as embargoed jurisdictions.

**Why:** Naming a real country as embargoed would be a political statement, would date immediately,
and is not necessary to demonstrate the mechanism.

### Compliance screening is exact-match on a tiny list

**Assumed:** Exact name, country and BIC matching; a short keyword list for remittance.

**Why:** Real screening needs licensed data and fuzzy matching. A simplified engine still
demonstrates the thing that matters: a payment stops before any message is sent, and an alert is
raised with the matched value and the list reference.

**Would change if:** The tool were used to evaluate screening behaviour rather than payment
behaviour. It is explicitly labelled as a simplification in the UI and in the code.

### Cancellation is resolved on whether value has moved

**Assumed:** A camt.056 is answered `RJCR` if a settlement exists in `SETTLED` or
`PARTIALLY_SETTLED`, and `CNCL` otherwise.

**Why:** The first implementation keyed off the payment's own status, which produced the wrong
answer for a beneficiary claim: the payment had been moved to `INVESTIGATION_REQUIRED`, so a recall
on money that had already left was accepted. Keying off whether value actually moved is both more
correct and more instructive — it is the question a beneficiary bank actually asks.

### A reconciliation match does not close a broken ledger

**Assumed:** If the accounting journal does not balance, the payment goes to investigation even when
all four reconciliation legs agree.

**Why:** Reconciliation compares the bank against the outside world. It does not check the bank's
internal consistency. A payment whose journal is wrong must not be closed on the strength of an
external match.

### Account balances follow the account holder's view, not ledger signage

**Assumed:** The `balance` column is what the account holder would recognise as "how much is in
this account", so the direction a posting moves it depends on the account type:

| Account type | Debit | Credit |
| ------------ | ----- | ------ |
| Customer, vostro (liability — we owe it) | decreases | increases |
| Nostro, settlement, suspense (asset — we hold it) | increases | decreases |

**Why:** The first implementation applied liability signage to every account, which made an outgoing
cross-border payment appear to *increase* our nostro — the opposite of what happens. A nostro is
money we hold at a correspondent; spending it reduces it, even though the ledger entry on that leg
is a credit. The double entry itself is unchanged and still balances; only the displayed balance
direction is type-aware.

**Would change if:** The tool needed to present strict signed ledger figures as well. Both views are
derivable, and the entry side is stored, so adding one would be additive.

### Statement entries are stored separately from accounting entries

**Assumed:** Two tables, deliberately.

**Why:** If reconciliation compared a record with itself it could never find a difference. Keeping
the external view separate is what makes a missing camt.054, a changed amount or a duplicated
statement line into real breaks.

### A pending debit produces no statement notification

**Assumed:** The statement feed publishes nothing when the customer debit was not actually booked.

**Why:** An account servicer notifies movements it has booked. This also makes the delayed-posting
failure mode behave correctly end to end: the ledger is out *and* the statement is silent, which is
what the desk would see.

---

## Technical assumptions

### Modular monolith over microservices

**Assumed:** One backend process with internal module boundaries.

**Why:** The brief asks for a modular monolith unless a split provides clear benefit, and none does
here. The feature that matters most — tracing one payment across every subsystem — is harder, not
easier, across a network.

**Would change if:** Clearing simulation needed to be driven independently, or multiple teams needed
to deploy separately. The boundaries are already in place for that.

### SQLite by default, PostgreSQL for deployment

**Assumed:** `sqlite+pysqlite` is the default `DATABASE_URL`; Docker Compose uses PostgreSQL 16.

**Why:** A fresh clone should run with one command and no database to install. PostgreSQL is the
production target and is exercised by the Docker path.

**Mitigation:** A portable `Money` column type keeps amounts exact on both. Alembic migrations run
with `render_as_batch` on SQLite so ALTER-heavy migrations remain possible.

### Synchronous SQLAlchemy

**Assumed:** Sync sessions and sync route handlers.

**Why:** The workload is one operator's console. Async would complicate the engines and the
transaction boundaries for throughput nobody needs here. FastAPI runs sync handlers in a thread
pool, so the event loop is not blocked.

### Asynchronous behaviour is a durable job table, not in-memory timers

**Assumed:** `scheduled_job` rows polled by a background thread.

**Why:** Pending work is then inspectable in the UI, survives a restart, and can be driven
synchronously by the test suite — so the async path is covered by the same assertions as the sync
path. An in-memory timer would fail all three.

**Would change if:** The application needed multiple replicas. The claim step is already a single
`PENDING → RUNNING` update, so moving to `SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL would be a
small change.

### Rules are code plus a metadata table, not data

**Assumed:** Evaluator functions in Python; the inspectable metadata and the enable flag in the
database.

**Why:** A rule needs to execute arbitrary logic — a mod-97 check, a duplicate query, a cut-off
comparison. Expressing that as data would mean building an expression language and losing type
checking and unit tests. The metadata table gives the Business Rule Explorer something real to show
and toggle.

**Mitigation:** The sync is one-way for metadata and never overwrites an operator's enable/disable
choice, which is covered by a test.

### A disabled rule is SKIPPED, not omitted

**Assumed:** Disabling a rule still writes a result row with status `SKIPPED`.

**Why:** A QA engineer must always be able to see which checks ran. Silently dropping a rule would
make a passing payment ambiguous.

### Money is Decimal end to end

**Assumed:** No float touches a monetary value, anywhere.

**Why:** It is the one bug in a payments system that is never acceptable.

**Mitigation:** The `Money` column type stores `NUMERIC(20,4)` on PostgreSQL and a scaled `BIGINT`
on SQLite, so values are exact on both and still sort and range-query in SQL. Amounts are quantised
to the currency's minor units on creation.

### Payment creation quantises the amount

**Assumed:** `10.004 CHF` becomes `10.00 CHF` at creation rather than being rejected.

**Why:** Defence in depth at the boundary. `VAL-AMOUNT-002` still exists and still fires for amounts
that reach the engine another way (an import, an injection), and the test suite covers both paths.

### No frontend state library

**Assumed:** Two small hooks (`useAsync`, `useAction`) and no global cache.

**Why:** The console is read-mostly over a live engine. A cache would show remembered state where
the operator needs current state — and "the UI said it was fine" is precisely the failure mode this
tool exists to teach people to distrust.

**Mitigation:** Views poll while a payment is processing asynchronously, and every mutation reloads.

### Hand-written CSS, no component library

**Assumed:** A design-token file plus a component stylesheet.

**Why:** The brief explicitly rules out a generic SaaS dashboard. A utility framework or an
off-the-shelf component library would have pulled the result toward exactly that.

**Mitigation:** The tokens file is small and documented, with a light theme defined alongside the
dark one.

### The frontend trusts the backend for business decisions

**Assumed:** No validation logic is duplicated in the UI beyond input shape and an inline hint for
the scheme ceiling.

**Why:** Two implementations of a rule is two rules. The hint is presentational; the rule engine
decides.

### Logging cannot crash the caller

**Assumed:** A `SafeLogger` renames `extra` keys that collide with `LogRecord` attributes.

**Why:** Found the hard way: a seed summary containing a `created` key took down application
startup. Structured logging must never be able to do that.

---

## Scope decisions

| Not built | Why |
| --------- | --- |
| Authentication and multi-user | Single-operator local tool. The audit model already carries an actor, so adding roles later is additive. |
| pain.001 initiation layer | The brief starts at the bank. Adding it is listed as a future enhancement. |
| Batch and bulk processing | One payment per message keeps the journey view legible, which is the product's core. |
| XSD validation of messages | Would need the official schemas, which are licensed. Message *structure* is tested instead. |
| Real AI integration | The brief requires the engine to work without AI. Nothing in this build calls an LLM; the configuration hooks exist and are documented. |
| WebSockets for live updates | Polling while a payment is in flight is sufficient for a single operator and far simpler to reason about. |
| A charting library | The brief rules out fake analytics. The two bar indicators that exist are plain CSS and show real proportions. |

---

## Known rough edges

- **Scenario SC-03 (duplicate payment) creates its own precondition.** It runs a baseline payment
  first so that a prior end-to-end id genuinely exists. Without that, running the scenario on an
  empty database would silently pass for the wrong reason. The baseline is recorded in the execution
  notes.
- **In `IMMEDIATE` mode no wall-clock time passes,** so a timeout cannot quote an elapsed duration.
  The wording changes to say the clearing system was configured not to respond, rather than
  reporting a meaningless `0.0s`.
- **The demo book is built by running the scenario library,** so the payment references and the
  exact counts depend on the seed order. Counts are asserted as minimums, not exact values.
- **The scheduler is single-process.** It is durable and restart-safe but does not coordinate across
  replicas.
- **The Docker path has not been run end to end.** No Docker daemon was available on the development
  machine. What *is* verified: `docker compose config` validates; the backend image's
  `pip install .` resolves and the app imports and builds from the resulting wheel in a clean
  environment; the frontend's `npm run build` succeeds; and a `.dockerignore` keeps host-built
  `node_modules` and `.venv` out of the build context, which would otherwise have put
  Windows-built binaries into a Linux image. What is **not** verified: the image builds themselves,
  the containers starting, Nginx proxying to the API, and the PostgreSQL path. Everything was run
  and tested against SQLite.
- **PostgreSQL is unexercised.** The `Money` column type has a `NUMERIC(20,4)` branch that has never
  executed, and the migration has only ever been applied to SQLite. The migration does render the
  portable `app.db.types.Money` / `UTCDateTime` types rather than SQLite-specific ones, so it should
  apply, but nothing has proved it.
