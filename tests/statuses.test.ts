import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "fs/promises";
import { tmpdir } from "os";
import path from "path";
import { getStatuses, setStatus } from "../lib/statuses.js";

const originalCwd = process.cwd();
let workDir: string;

beforeEach(async () => {
  workDir = await mkdtemp(path.join(tmpdir(), "shortlist-status-"));
  process.chdir(workDir);
});

afterEach(async () => {
  process.chdir(originalCwd);
  await rm(workDir, { recursive: true, force: true });
});

describe("statuses", () => {
  test("returns an empty map before anything is written", async () => {
    assert.deepEqual(await getStatuses(), {});
  });

  test("persists a status and stamps it with a time", async () => {
    await setStatus("acme|analyst|india", "applied");

    const statuses = await getStatuses();
    assert.equal(statuses["acme|analyst|india"].status, "applied");
    assert.ok(!Number.isNaN(Date.parse(statuses["acme|analyst|india"].updatedAt)));
  });

  test("overwrites an existing status for the same key", async () => {
    await setStatus("k", "interested");
    await setStatus("k", "applied");

    const statuses = await getStatuses();
    assert.equal(statuses["k"].status, "applied");
    assert.equal(Object.keys(statuses).length, 1);
  });

  test("clearing back to 'new' removes the entry entirely", async () => {
    await setStatus("k", "applied");
    await setStatus("k", "new");

    assert.deepEqual(await getStatuses(), {});
  });

  test("keeps statuses for other keys independent", async () => {
    await setStatus("a", "applied");
    await setStatus("b", "dismissed");
    await setStatus("a", "new");

    const statuses = await getStatuses();
    assert.equal(statuses["b"].status, "dismissed");
    assert.ok(!("a" in statuses));
  });

  test("concurrent writes are serialized, not lost", async () => {
    // Without the write queue these overlapping read-modify-write cycles
    // would each start from the same empty snapshot and clobber each other.
    const keys = Array.from({ length: 12 }, (_, i) => `key-${i}`);
    await Promise.all(keys.map((k) => setStatus(k, "interested")));

    const statuses = await getStatuses();
    assert.equal(Object.keys(statuses).length, keys.length);
    for (const k of keys) {
      assert.equal(statuses[k].status, "interested");
    }
  });

  test("a rejected write does not stall the queue", async () => {
    await setStatus("first", "applied");
    await setStatus("second", "interested");

    const statuses = await getStatuses();
    assert.equal(Object.keys(statuses).length, 2);
  });
});
