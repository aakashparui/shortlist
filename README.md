# Shortlist

Track job postings worth pursuing. Fetches listings from the JSearch API, deduplicates them across runs, and gives you a UI to triage what's worth applying to — plus resume analysis that works out which roles to search for in the first place.

## Features

- **Fetch** roles by title and location, with cursor pagination for deeper coverage
- **Deduplicate** across runs by a normalized `company + title + location` key, so re-fetching never creates duplicates
- **Track** each posting as Interested / Applied / Dismissed, persisted between sessions
- **Resume analysis** — upload a PDF or paste text, and get ranked role suggestions with the evidence behind each one
- **Scheduled runs** that fetch your saved searches unattended and report what's new
- **Quota-aware** — reads RapidAPI's rate-limit headers and stops before exhausting a monthly allowance

## Setup

```bash
npm install
cp .env.local.example .env.local   # then add your key
cp data/searches.example.json data/searches.json
```

`.env.local` needs a [JSearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) key from RapidAPI — subscribe to the API first, or requests return `403 You are not subscribed to this API`:

```
RAPIDAPI_KEY=your_key_here
```

Optionally add an Anthropic key to upgrade resume analysis from keyword matching to Claude:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
npm run dev              # web UI at http://localhost:3000
npm run scheduled-fetch  # run every saved search in data/searches.json
npm test                 # 83 tests
```

One-off search from the CLI:

```bash
npm run fetch-jobs "payments analyst" "India"
```

### Scheduling

On Windows, from an Administrator PowerShell:

```
schtasks /create /tn "Shortlist Daily Fetch" /tr "cmd /c cd /d \"C:\path\to\Shortlist\" && npm run scheduled-fetch >> data\fetch.log 2>&1" /sc daily /st 09:00
```

## Architecture

```
lib/
  sources/     job board adapters (jsearch) + dedupe registry
  resume/      PDF extraction, keyword heuristic, Claude analyzer
  storage.ts   accumulating JSON + CSV store
  statuses.ts  per-job status tracking, serialized writes
app/           Next.js UI and API routes
scripts/       CLI entry points
tests/         node:test suite
```

Adding a second job board means writing one adapter that returns `Job[]` and appending it to the `sources` array in `lib/sources/index.ts` — dedupe and storage handle the rest.

### API notes

The JSearch endpoint is `/search-v2`, which paginates by opaque `cursor` rather than page number. Location is folded into the free-text `query` ("payments analyst in India") since there's no separate location parameter; without one the API defaults to US listings. Results are filtered client-side to the last 14 days — `date_posted=month` is the narrowest server-side window that fully covers that.

### Cost

Each page is one API request. RapidAPI's free tier is 200/month. The defaults — 2 pages from the UI, 2 from the scheduler — put a daily run at roughly 120/month, leaving headroom for interactive searches.

## Data

`data/` is gitignored. `jobs.json` is the source of truth, `jobs.csv` a spreadsheet-friendly mirror, `statuses.json` your triage state.
