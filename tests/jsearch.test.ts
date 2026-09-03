import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  fetchJobs,
  JSearchApiError,
  JSearchConfigError,
} from "../lib/sources/jsearch.js";

const DAY = 24 * 60 * 60 * 1000;
const realFetch = globalThis.fetch;
const realKey = process.env.RAPIDAPI_KEY;

/** An API job whose posted date is `days` days before now. */
function apiJob(days: number | null, overrides: Record<string, unknown> = {}) {
  return {
    job_id: `id-${days}`,
    job_title: `Role ${days}`,
    employer_name: "Acme Corp",
    job_location: "Bengaluru, Karnataka, India",
    job_posted_at_datetime_utc:
      days === null ? null : new Date(Date.now() - days * DAY).toISOString(),
    job_description: "A description",
    job_apply_link: "https://example.com/apply",
    ...overrides,
  };
}

function stubFetch(body: unknown, init: { status?: number; statusText?: string } = {}) {
  const calls: URL[] = [];
  globalThis.fetch = (async (input: URL) => {
    calls.push(input);
    return new Response(JSON.stringify(body), {
      status: init.status ?? 200,
      statusText: init.statusText ?? "OK",
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return calls;
}

function okBody(jobs: unknown[]) {
  return { status: "OK", data: { jobs } };
}

beforeEach(() => {
  process.env.RAPIDAPI_KEY = "test-key";
});

afterEach(() => {
  globalThis.fetch = realFetch;
  if (realKey === undefined) delete process.env.RAPIDAPI_KEY;
  else process.env.RAPIDAPI_KEY = realKey;
});

describe("fetchJobs — 14-day filter", () => {
  test("keeps postings inside the window and drops older ones", async () => {
    stubFetch(okBody([apiJob(1), apiJob(13), apiJob(15), apiJob(40)]));

    const jobs = await fetchJobs("analyst", "India");

    assert.deepEqual(
      jobs.map((j) => j.title),
      ["Role 1", "Role 13"]
    );
  });

  test("keeps a posting just inside the 14-day boundary", async () => {
    // Slightly under 14 days, to stay clear of clock drift during the call.
    stubFetch(okBody([apiJob(13.99)]));
    const jobs = await fetchJobs("analyst", "India");
    assert.equal(jobs.length, 1);
  });

  test("drops a posting just outside the 14-day boundary", async () => {
    stubFetch(okBody([apiJob(14.01)]));
    const jobs = await fetchJobs("analyst", "India");
    assert.equal(jobs.length, 0);
  });

  test("drops postings with a null or unparseable date", async () => {
    stubFetch(
      okBody([apiJob(null), apiJob(1, { job_posted_at_datetime_utc: "not-a-date" })])
    );
    const jobs = await fetchJobs("analyst", "India");
    assert.equal(jobs.length, 0);
  });
});

describe("fetchJobs — mapping", () => {
  test("maps API fields onto the normalized Job shape", async () => {
    stubFetch(okBody([apiJob(2)]));

    const [job] = await fetchJobs("analyst", "India");

    assert.equal(job.id, "id-2");
    assert.equal(job.title, "Role 2");
    assert.equal(job.company, "Acme Corp");
    assert.equal(job.location, "Bengaluru, Karnataka, India");
    assert.equal(job.description, "A description");
    assert.equal(job.applyUrl, "https://example.com/apply");
    assert.equal(job.source, "jsearch");
    assert.ok(job.postedDate.endsWith("Z"));
  });

  test("substitutes empty strings for null text fields", async () => {
    stubFetch(
      okBody([
        apiJob(1, {
          job_title: null,
          employer_name: null,
          job_location: null,
          job_description: null,
          job_apply_link: null,
        }),
      ])
    );

    const [job] = await fetchJobs("analyst", "India");

    assert.equal(job.title, "");
    assert.equal(job.company, "");
    assert.equal(job.location, "");
    assert.equal(job.description, "");
    assert.equal(job.applyUrl, "");
  });
});

describe("fetchJobs — request shape", () => {
  test("folds location into the free-text query", async () => {
    const calls = stubFetch(okBody([]));
    await fetchJobs("payments analyst", "India");
    assert.equal(calls[0].searchParams.get("query"), "payments analyst in India");
  });

  test("omits the location clause when location is empty", async () => {
    const calls = stubFetch(okBody([]));
    await fetchJobs("payments analyst", "");
    assert.equal(calls[0].searchParams.get("query"), "payments analyst");
  });

  test("calls the search-v2 endpoint", async () => {
    const calls = stubFetch(okBody([]));
    await fetchJobs("analyst", "India");
    assert.equal(calls[0].pathname, "/search-v2");
    assert.equal(calls[0].host, "jsearch.p.rapidapi.com");
  });
});

describe("fetchJobs — error handling", () => {
  test("throws a config error when the key is missing", async () => {
    delete process.env.RAPIDAPI_KEY;
    await assert.rejects(() => fetchJobs("analyst", "India"), JSearchConfigError);
  });

  test("throws a config error on 403, surfacing the API message", async () => {
    stubFetch({ message: "You are not subscribed to this API." }, { status: 403 });
    await assert.rejects(
      () => fetchJobs("analyst", "India"),
      (err: Error) =>
        err instanceof JSearchConfigError && err.message.includes("not subscribed")
    );
  });

  test("throws a config error on 401", async () => {
    stubFetch({ message: "Invalid API key" }, { status: 401 });
    await assert.rejects(() => fetchJobs("analyst", "India"), JSearchConfigError);
  });

  test("throws an API error on other failure statuses", async () => {
    stubFetch({}, { status: 500, statusText: "Internal Server Error" });
    await assert.rejects(() => fetchJobs("analyst", "India"), JSearchApiError);
  });

  test("throws an API error when the response shape is unexpected", async () => {
    stubFetch({ status: "OK", data: { notJobs: [] } });
    await assert.rejects(() => fetchJobs("analyst", "India"), JSearchApiError);
  });

  test("throws an API error when the network call fails", async () => {
    globalThis.fetch = (async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    await assert.rejects(() => fetchJobs("analyst", "India"), JSearchApiError);
  });
});
