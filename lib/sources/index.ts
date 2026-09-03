import type { FetchOptions, Job } from "../types.js";
import { fetchJobs as fetchJSearchJobs } from "./jsearch.js";

type SourceFn = (
  query: string,
  location: string,
  options?: FetchOptions
) => Promise<Job[]>;

const sources: SourceFn[] = [fetchJSearchJobs];

function normalize(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

export function dedupeKey(job: Job): string {
  return `${normalize(job.company)}|${normalize(job.title)}|${normalize(job.location)}`;
}

export async function fetchAllJobs(
  query: string,
  location: string,
  options: FetchOptions = {}
): Promise<Job[]> {
  const results = await Promise.all(
    sources.map((source) => source(query, location, options))
  );
  const seen = new Set<string>();
  const deduped: Job[] = [];

  for (const job of results.flat()) {
    const key = dedupeKey(job);
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(job);
  }

  return deduped;
}
