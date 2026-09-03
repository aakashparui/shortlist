import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { fetchJobs } from "../lib/sources/jsearch.js";

const DAY = 24 * 60 * 60 * 1000;
const realFetch = globalThis.fetch;
const realKey = process.env.RAPIDAPI_KEY;

function apiJob(id: string, ageDays = 1) {
  return {
    job_id: id,
    job_title: `Role ${id}`,
    employer_name: `Company ${id}`,
    job_location: "India",
    job_posted_at_datetime_utc: new Date(Date.now() - ageDays * DAY).toISOString(),
    job_description: "desc",
    job_apply_link: "https://example.com",
  };
}

/**
 * Serves a scripted sequence of pages, recording the cursor sent with each
 * request so tests can assert the client actually follows the chain.
 */
function stubPages(pages: { jobs: unknown[]; cursor?: string | null }[]) {
  const cursorsSent: (string | null)[] = [];
  let call = 0;

  globalThis.fetch = (async (input: URL) => {
    cursorsSent.push(input.searchParams.get("cursor"));
    const page = pages[Math.min(call, pages.length - 1)];
    call++;
    return new Response(
      JSON.stringify({ status: "OK", data: { jobs: page.jobs, cursor: page.cursor ?? null } }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }) as unknown as typeof fetch;

  return {
    cursorsSent,
    get callCount() {
      return call;
    },
  };
}

beforeEach(() => {
  process.env.RAPIDAPI_KEY = "test-key";
});

afterEach(() => {
  globalThis.fetch = realFetch;
  if (realKey === undefined) delete process.env.RAPIDAPI_KEY;
  else process.env.RAPIDAPI_KEY = realKey;
});

describe("fetchJobs — pagination", () => {
  test("aggregates jobs across pages instead of stopping at the first", async () => {
    stubPages([
      { jobs: [apiJob("a1"), apiJob("a2")], cursor: "c1" },
      { jobs: [apiJob("b1"), apiJob("b2")], cursor: "c2" },
      { jobs: [apiJob("c1x")], cursor: null },
    ]);

    const jobs = await fetchJobs("analyst", "India");

    assert.equal(jobs.length, 5);
    assert.deepEqual(jobs.map((j) => j.id), ["a1", "a2", "b1", "b2", "c1x"]);
  });

  test("sends no cursor on the first request, then the one it was given", async () => {
    const stub = stubPages([
      { jobs: [apiJob("a")], cursor: "cursor-one" },
      { jobs: [apiJob("b")], cursor: "cursor-two" },
      { jobs: [apiJob("c")], cursor: null },
    ]);

    await fetchJobs("analyst", "India");

    assert.deepEqual(stub.cursorsSent, [null, "cursor-one", "cursor-two"]);
  });

  test("stops at the page cap even when more pages are offered", async () => {
    const stub = stubPages([
      { jobs: [apiJob("a")], cursor: "c1" },
      { jobs: [apiJob("b")], cursor: "c2" },
      { jobs: [apiJob("c")], cursor: "c3" },
      { jobs: [apiJob("d")], cursor: "c4" },
    ]);

    const jobs = await fetchJobs("analyst", "India");

    assert.equal(stub.callCount, 3, "should request exactly the default 3 pages");
    assert.equal(jobs.length, 3);
  });

  test("honours an explicit maxPages", async () => {
    const stub = stubPages([
      { jobs: [apiJob("a")], cursor: "c1" },
      { jobs: [apiJob("b")], cursor: "c2" },
      { jobs: [apiJob("c")], cursor: "c3" },
    ]);

    await fetchJobs("analyst", "India", { maxPages: 1 });
    assert.equal(stub.callCount, 1);
  });

  test("treats maxPages below 1 as a single page", async () => {
    const stub = stubPages([{ jobs: [apiJob("a")], cursor: "c1" }]);
    await fetchJobs("analyst", "India", { maxPages: 0 });
    assert.equal(stub.callCount, 1);
  });

  test("stops early when the API returns no cursor", async () => {
    const stub = stubPages([
      { jobs: [apiJob("a")], cursor: null },
      { jobs: [apiJob("b")], cursor: "c2" },
    ]);

    const jobs = await fetchJobs("analyst", "India");

    assert.equal(stub.callCount, 1);
    assert.equal(jobs.length, 1);
  });

  test("stops early when a page comes back empty", async () => {
    const stub = stubPages([
      { jobs: [apiJob("a")], cursor: "c1" },
      { jobs: [], cursor: "c2" },
    ]);

    const jobs = await fetchJobs("analyst", "India");

    assert.equal(stub.callCount, 2);
    assert.equal(jobs.length, 1);
  });

  test("breaks out of a cursor that keeps returning the same page", async () => {
    // Every page repeats the same job and offers another cursor — without the
    // loop guard this would spend the full page budget re-reading one page.
    const stub = stubPages([{ jobs: [apiJob("same")], cursor: "always" }]);

    const jobs = await fetchJobs("analyst", "India", { maxPages: 10 });

    assert.equal(stub.callCount, 2, "should stop as soon as a page adds nothing new");
    assert.equal(jobs.length, 1);
  });

  test("applies the 14-day filter across every page, not just the first", async () => {
    stubPages([
      { jobs: [apiJob("fresh", 1)], cursor: "c1" },
      { jobs: [apiJob("stale", 40)], cursor: "c2" },
      { jobs: [apiJob("also-fresh", 3)], cursor: null },
    ]);

    const jobs = await fetchJobs("analyst", "India");

    assert.deepEqual(jobs.map((j) => j.id), ["fresh", "also-fresh"]);
  });

  test("surfaces an error raised on a later page", async () => {
    let call = 0;
    globalThis.fetch = (async () => {
      call++;
      if (call === 1) {
        return new Response(
          JSON.stringify({ status: "OK", data: { jobs: [apiJob("a")], cursor: "c1" } }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 500, statusText: "Server Error" });
    }) as unknown as typeof fetch;

    await assert.rejects(() => fetchJobs("analyst", "India"));
  });
});
