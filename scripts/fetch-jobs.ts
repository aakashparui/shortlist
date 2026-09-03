import { PROJECT_ROOT, loadEnvLocal } from "../lib/env.js";
import { fetchAllJobs } from "../lib/sources/index.js";
import { JSearchConfigError, JSearchApiError } from "../lib/sources/jsearch.js";
import { saveJobs } from "../lib/storage.js";

process.chdir(PROJECT_ROOT);
loadEnvLocal();

async function main() {
  const [query, location] = process.argv.slice(2);

  if (!query || !location) {
    console.error('Usage: npx tsx scripts/fetch-jobs.ts "<query>" "<location>"');
    process.exitCode = 1;
    return;
  }

  const jobs = await fetchAllJobs(query, location);

  console.log(JSON.stringify(jobs, null, 2));
  console.log(`\n${jobs.length} job(s) found.`);

  const { newlyAdded, totalSaved } = await saveJobs(jobs);
  console.log(`${newlyAdded} new job(s) saved. ${totalSaved} total in data/jobs.json and data/jobs.csv.`);
}

main().catch((err) => {
  if (err instanceof JSearchConfigError || err instanceof JSearchApiError) {
    console.error(`Error: ${err.message}`);
  } else {
    console.error(`Unexpected error: ${err instanceof Error ? err.message : String(err)}`);
  }
  process.exitCode = 1;
});
