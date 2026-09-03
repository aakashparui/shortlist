import { readFile } from "fs/promises";
import path from "path";
import { PROJECT_ROOT, loadEnvLocal } from "../lib/env.js";
import { fetchAllJobs } from "../lib/sources/index.js";
import { getLastQuota, JSearchApiError, JSearchConfigError } from "../lib/sources/jsearch.js";
import { saveJobs } from "../lib/storage.js";

// Anchor everything to the project root before touching data files: Task
// Scheduler launches with an arbitrary working directory, and the data
// helpers resolve their paths relative to cwd. Safe to do here because both
// the env lookup and the data paths are read lazily, inside functions.
process.chdir(PROJECT_ROOT);
loadEnvLocal();

/**
 * Each page is one API request, so a run costs N searches ×
 * SCHEDULED_MAX_PAGES. Sized for RapidAPI's 200-requests/month free tier:
 * 2 searches × 2 pages daily is ~120/month, leaving headroom for interactive
 * fetches from the UI. Raise this on a paid plan.
 */
const SCHEDULED_MAX_PAGES = 2;

/**
 * Stop before the monthly allowance is gone, so a scheduled run can never
 * consume the last requests you might want for an interactive search.
 */
const QUOTA_RESERVE = 15;

interface SavedSearch {
  query: string;
  location: string;
}

function timestamp(): string {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function log(message: string): void {
  console.log(`[${timestamp()}] ${message}`);
}

async function loadSearches(): Promise<SavedSearch[]> {
  const searchesPath = path.join(PROJECT_ROOT, "data", "searches.json");

  let raw: string;
  try {
    raw = await readFile(searchesPath, "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(
        `No saved searches found at data/searches.json. Create it with entries like: ` +
          `[{ "query": "payments analyst", "location": "India" }]`
      );
    }
    throw err;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("data/searches.json is not valid JSON.");
  }

  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("data/searches.json must be a non-empty array of { query, location }.");
  }

  return parsed.map((entry, i) => {
    const { query, location } = (entry ?? {}) as Partial<SavedSearch>;
    if (typeof query !== "string" || !query.trim()) {
      throw new Error(`data/searches.json entry ${i} is missing a "query".`);
    }
    if (typeof location !== "string" || !location.trim()) {
      throw new Error(`data/searches.json entry ${i} is missing a "location".`);
    }
    return { query: query.trim(), location: location.trim() };
  });
}

async function main() {
  const searches = await loadSearches();
  log(`Running ${searches.length} saved search(es).`);

  const allNew: { title: string; company: string; location: string }[] = [];
  let failures = 0;

  for (const { query, location } of searches) {
    // Checked between searches: the quota is only known after a real response,
    // so this protects every search after the first.
    const quota = getLastQuota();
    if (quota && quota.remaining <= QUOTA_RESERVE) {
      log(
        `Stopping early: only ${quota.remaining} of ${quota.limit} API requests left this period. ` +
          `Remaining searches skipped to preserve quota for interactive use.`
      );
      failures++;
      break;
    }

    try {
      const jobs = await fetchAllJobs(query, location, { maxPages: SCHEDULED_MAX_PAGES });
      const { newlyAdded, totalSaved, added } = await saveJobs(jobs);

      log(
        `"${query}" in "${location}": ${jobs.length} fetched, ${newlyAdded} new (${totalSaved} total saved).`
      );
      allNew.push(...added.map((j) => ({ title: j.title, company: j.company, location: j.location })));
    } catch (err) {
      failures++;
      // One bad search shouldn't abort the rest of the run.
      if (err instanceof JSearchConfigError) {
        // A bad key or missing subscription will fail every search, so stop early.
        log(`Configuration error: ${err.message}`);
        throw err;
      }
      if (err instanceof JSearchApiError) {
        log(`"${query}" in "${location}" failed: ${err.message}`);
      } else {
        log(
          `"${query}" in "${location}" failed unexpectedly: ${
            err instanceof Error ? err.message : String(err)
          }`
        );
      }
    }
  }

  if (allNew.length === 0) {
    log("No new jobs this run.");
  } else {
    log(`${allNew.length} new job(s):`);
    for (const job of allNew) {
      console.log(`  • ${job.title} — ${job.company} (${job.location})`);
    }
    log("They're marked New in the UI: run `npm run dev` and open http://localhost:3000");
  }

  const quota = getLastQuota();
  if (quota) {
    const days =
      quota.resetSeconds !== null ? Math.round(quota.resetSeconds / 86400) : null;
    log(
      `API quota: ${quota.remaining}/${quota.limit} requests left` +
        (days !== null ? ` (resets in ~${days} day${days === 1 ? "" : "s"})` : "")
    );
    if (quota.remaining <= QUOTA_RESERVE * 2) {
      log("Quota is running low — consider reducing searches or pausing the schedule.");
    }
  }

  if (failures > 0) process.exitCode = 1;
}

main().catch((err) => {
  log(`Run aborted: ${err instanceof Error ? err.message : String(err)}`);
  process.exitCode = 1;
});
