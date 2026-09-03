import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, readFile } from "fs/promises";
import { tmpdir } from "os";
import path from "path";
import { getSavedJobs, saveJobs } from "../lib/storage.js";
import type { Job } from "../lib/types.js";

const originalCwd = process.cwd();
let workDir: string;

// The data helpers resolve paths against process.cwd() on each call, so each
// test can run against a throwaway directory instead of the real data/.
beforeEach(async () => {
  workDir = await mkdtemp(path.join(tmpdir(), "shortlist-test-"));
  process.chdir(workDir);
});

afterEach(async () => {
  process.chdir(originalCwd);
  await rm(workDir, { recursive: true, force: true });
});

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "id-1",
    title: "Payments Analyst",
    company: "Acme Corp",
    location: "Bengaluru, Karnataka, India",
    postedDate: "2026-08-20T00:00:00.000Z",
    description: "A description",
    applyUrl: "https://example.com/apply",
    source: "jsearch",
    ...overrides,
  };
}

const readCsv = () => readFile(path.join(workDir, "data", "jobs.csv"), "utf-8");

describe("getSavedJobs", () => {
  test("returns an empty list when nothing has been saved", async () => {
    assert.deepEqual(await getSavedJobs(), []);
  });
});

describe("saveJobs — accumulation", () => {
  test("saves new jobs and reports what was added", async () => {
    const result = await saveJobs([job({ id: "a" }), job({ id: "b", title: "Billing Analyst" })]);

    assert.equal(result.newlyAdded, 2);
    assert.equal(result.totalSaved, 2);
    assert.equal(result.added.length, 2);
    assert.equal((await getSavedJobs()).length, 2);
  });

  test("adds nothing when the same jobs are saved twice", async () => {
    await saveJobs([job()]);
    const second = await saveJobs([job()]);

    assert.equal(second.newlyAdded, 0);
    assert.equal(second.totalSaved, 1);
    assert.deepEqual(second.added, []);
  });

  test("treats a re-fetch of the same posting as a duplicate despite a new id", async () => {
    await saveJobs([job({ id: "first-fetch" })]);
    const second = await saveJobs([job({ id: "second-fetch" })]);

    assert.equal(second.newlyAdded, 0);
    assert.equal(second.totalSaved, 1);
  });

  test("merges only genuinely new jobs into an existing file", async () => {
    await saveJobs([job({ title: "Payments Analyst" })]);
    const second = await saveJobs([
      job({ title: "Payments Analyst" }),
      job({ title: "Billing Analyst" }),
    ]);

    assert.equal(second.newlyAdded, 1);
    assert.equal(second.totalSaved, 2);
    assert.deepEqual(second.added.map((j) => j.title), ["Billing Analyst"]);
  });

  test("keeps the originally saved record rather than overwriting it", async () => {
    await saveJobs([job({ description: "original" })]);
    await saveJobs([job({ description: "changed" })]);

    const saved = await getSavedJobs();
    assert.equal(saved.length, 1);
    assert.equal(saved[0].description, "original");
  });

  test("deduplicates within a single batch", async () => {
    const result = await saveJobs([job({ id: "a" }), job({ id: "b" })]);
    assert.equal(result.newlyAdded, 1);
  });
});

describe("saveJobs — CSV output", () => {
  test("writes a header plus one row per job", async () => {
    await saveJobs([job(), job({ title: "Billing Analyst" })]);
    const lines = (await readCsv()).trim().split("\n");

    assert.match(lines[0], /^id,title,company,location,postedDate,applyUrl,source,description$/);
    assert.equal(lines.length, 3);
  });

  test("quotes fields containing commas", async () => {
    await saveJobs([job({ location: "Bengaluru, Karnataka, India" })]);
    assert.ok((await readCsv()).includes('"Bengaluru, Karnataka, India"'));
  });

  test("escapes embedded double quotes by doubling them", async () => {
    await saveJobs([job({ title: 'Senior "Lead" Analyst' })]);
    assert.ok((await readCsv()).includes('"Senior ""Lead"" Analyst"'));
  });

  test("quotes fields containing newlines so rows stay intact", async () => {
    await saveJobs([job({ description: "Line one\nLine two" })]);
    const csv = await readCsv();

    assert.ok(csv.includes('"Line one\nLine two"'));
    // Header + a single record that happens to wrap across two physical lines.
    assert.equal(csv.trim().split("\n").length, 3);
  });

  test("leaves plain values unquoted", async () => {
    await saveJobs([job({ company: "Acme", location: "India" })]);
    const csv = await readCsv();

    assert.ok(csv.includes(",Acme,India,"));
  });
});
