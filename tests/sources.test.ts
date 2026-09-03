import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { fetchAllJobs } from "../lib/sources/index.js";

const realFetch = globalThis.fetch;
const realKey = process.env.RAPIDAPI_KEY;

function apiJob(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "id-1",
    job_title: "Payments Analyst",
    employer_name: "Acme Corp",
    job_location: "Bengaluru, Karnataka, India",
    job_posted_at_datetime_utc: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    job_description: "A description",
    job_apply_link: "https://example.com/apply",
    ...overrides,
  };
}

function stubFetch(jobs: unknown[], cursor: string | null = null) {
  const state = { calls: 0 };
  globalThis.fetch = (async () => {
    state.calls++;
    return new Response(JSON.stringify({ status: "OK", data: { jobs, cursor } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return state;
}

beforeEach(() => {
  process.env.RAPIDAPI_KEY = "test-key";
});

afterEach(() => {
  globalThis.fetch = realFetch;
  if (realKey === undefined) delete process.env.RAPIDAPI_KEY;
  else process.env.RAPIDAPI_KEY = realKey;
});

describe("fetchAllJobs", () => {
  test("collapses the same posting listed under different ids", async () => {
    stubFetch([apiJob({ job_id: "a" }), apiJob({ job_id: "b" })]);

    const jobs = await fetchAllJobs("analyst", "India");
    assert.equal(jobs.length, 1);
  });

  test("collapses postings that differ only by capitalization or spacing", async () => {
    stubFetch([
      apiJob({ job_id: "a", employer_name: "Acme Corp" }),
      apiJob({ job_id: "b", employer_name: "ACME   CORP" }),
    ]);

    const jobs = await fetchAllJobs("analyst", "India");
    assert.equal(jobs.length, 1);
  });

  test("keeps genuinely distinct postings", async () => {
    stubFetch([
      apiJob({ job_id: "a", job_title: "Payments Analyst" }),
      apiJob({ job_id: "b", job_title: "Billing Analyst" }),
    ]);

    const jobs = await fetchAllJobs("analyst", "India");
    assert.equal(jobs.length, 2);
  });

  test("keeps the first occurrence of a duplicate", async () => {
    stubFetch([
      apiJob({ job_id: "first", job_description: "first copy" }),
      apiJob({ job_id: "second", job_description: "second copy" }),
    ]);

    const jobs = await fetchAllJobs("analyst", "India");
    assert.equal(jobs[0].description, "first copy");
  });

  test("passes fetch options through to the source", async () => {
    // Distinct ids per call so the loop-guard doesn't stop it early.
    let call = 0;
    globalThis.fetch = (async () => {
      call++;
      return new Response(
        JSON.stringify({
          status: "OK",
          data: { jobs: [apiJob({ job_id: `id-${call}` })], cursor: "next" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }) as unknown as typeof fetch;

    await fetchAllJobs("analyst", "India", { maxPages: 2 });
    assert.equal(call, 2, "maxPages should reach the source adapter");
  });

  test("defaults to a single-source depth when no options are given", async () => {
    const state = stubFetch([apiJob()], null);
    await fetchAllJobs("analyst", "India");
    assert.equal(state.calls, 1, "a page with no cursor should stop after one request");
  });

  test("returns an empty list when every posting is too old", async () => {
    stubFetch([
      apiJob({ job_posted_at_datetime_utc: new Date(Date.now() - 60 * 86400000).toISOString() }),
    ]);

    assert.deepEqual(await fetchAllJobs("analyst", "India"), []);
  });
});
