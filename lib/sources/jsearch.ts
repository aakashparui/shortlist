import type { FetchOptions, Job } from "../types.js";

const ENDPOINT = "https://jsearch.p.rapidapi.com/search-v2";
const HOST = "jsearch.p.rapidapi.com";
const MAX_AGE_DAYS = 14;

/**
 * How many cursor pages to walk per search. The API returns ~10 postings per
 * page, so this caps a single search at roughly 30 results — enough depth to
 * be useful without burning request quota on every run.
 */
const DEFAULT_MAX_PAGES = 3;

interface JSearchJob {
  job_id: string;
  job_title: string | null;
  employer_name: string | null;
  job_location: string | null;
  job_posted_at_datetime_utc: string | null;
  job_description: string | null;
  job_apply_link: string | null;
}

interface JSearchResponse {
  status: string;
  data: {
    jobs: JSearchJob[];
    /** Opaque token for the next page; absent once results are exhausted. */
    cursor?: string | null;
  };
}

export interface QuotaSnapshot {
  limit: number;
  remaining: number;
  /** Seconds until the monthly allowance resets. */
  resetSeconds: number | null;
}

let lastQuota: QuotaSnapshot | null = null;

/**
 * The quota reported by the most recent API response, or null if no request
 * has been made yet. RapidAPI returns these on every call, which is the only
 * reliable way to know how much of a monthly allowance is left.
 */
export function getLastQuota(): QuotaSnapshot | null {
  return lastQuota;
}

function readQuota(headers: Headers): void {
  const limit = Number(headers.get("x-ratelimit-requests-limit"));
  const remaining = Number(headers.get("x-ratelimit-requests-remaining"));
  if (!Number.isFinite(limit) || !Number.isFinite(remaining)) return;

  const reset = Number(headers.get("x-ratelimit-requests-reset"));
  lastQuota = {
    limit,
    remaining,
    resetSeconds: Number.isFinite(reset) ? reset : null,
  };
}

export class JSearchConfigError extends Error {}
export class JSearchApiError extends Error {}

function isWithinLastNDays(isoDate: string | null, days: number): boolean {
  if (!isoDate) return false;
  const posted = Date.parse(isoDate);
  if (Number.isNaN(posted)) return false;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return posted >= cutoff;
}

async function requestPage(
  searchQuery: string,
  apiKey: string,
  cursor?: string
): Promise<JSearchResponse> {
  const url = new URL(ENDPOINT);
  url.searchParams.set("query", searchQuery);
  url.searchParams.set("date_posted", "month");
  if (cursor) url.searchParams.set("cursor", cursor);

  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "X-RapidAPI-Key": apiKey,
        "X-RapidAPI-Host": HOST,
      },
    });
  } catch (err) {
    throw new JSearchApiError(
      `Could not reach JSearch API: ${err instanceof Error ? err.message : String(err)}`
    );
  }

  readQuota(response.headers);

  if (response.status === 401 || response.status === 403) {
    const detail = await response
      .json()
      .then((body: { message?: string }) => body.message)
      .catch(() => undefined);
    throw new JSearchConfigError(
      `RapidAPI rejected the request (${response.status})${detail ? `: ${detail}` : ""}. ` +
        "Check that RAPIDAPI_KEY is correct and that you are subscribed to the JSearch API on RapidAPI."
    );
  }

  if (!response.ok) {
    throw new JSearchApiError(
      `JSearch API request failed with status ${response.status} ${response.statusText}`
    );
  }

  const body = (await response.json()) as JSearchResponse;

  if (body.status !== "OK" || !Array.isArray(body.data?.jobs)) {
    throw new JSearchApiError("JSearch API returned an unexpected response shape.");
  }

  return body;
}

export async function fetchJobs(
  query: string,
  location: string,
  options: FetchOptions = {}
): Promise<Job[]> {
  const apiKey = process.env.RAPIDAPI_KEY;
  if (!apiKey) {
    throw new JSearchConfigError(
      "Missing RAPIDAPI_KEY environment variable. Set it to your RapidAPI key for JSearch before running this script."
    );
  }

  const maxPages = Math.max(1, options.maxPages ?? DEFAULT_MAX_PAGES);
  const searchQuery = location ? `${query} in ${location}` : query;

  const collected: JSearchJob[] = [];
  const seenIds = new Set<string>();
  let cursor: string | undefined;

  for (let page = 0; page < maxPages; page++) {
    const body = await requestPage(searchQuery, apiKey, cursor);
    const pageJobs = body.data.jobs;
    if (pageJobs.length === 0) break;

    let freshOnThisPage = 0;
    for (const job of pageJobs) {
      if (job.job_id && seenIds.has(job.job_id)) continue;
      if (job.job_id) seenIds.add(job.job_id);
      collected.push(job);
      freshOnThisPage++;
    }

    // A cursor that returns nothing new means we're looping; stop rather than
    // spend the remaining requests re-reading the same page.
    if (freshOnThisPage === 0) break;

    const nextCursor = body.data.cursor;
    if (!nextCursor) break;
    cursor = nextCursor;
  }

  return collected
    .filter((job) => isWithinLastNDays(job.job_posted_at_datetime_utc, MAX_AGE_DAYS))
    .map((job) => ({
      id: job.job_id,
      title: job.job_title ?? "",
      company: job.employer_name ?? "",
      location: job.job_location ?? "",
      postedDate: job.job_posted_at_datetime_utc ?? "",
      description: job.job_description ?? "",
      applyUrl: job.job_apply_link ?? "",
      source: "jsearch",
    }));
}
