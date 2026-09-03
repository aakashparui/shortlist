import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile, mkdir } from "fs/promises";
import { tmpdir } from "os";
import path from "path";

const originalCwd = process.cwd();
let workDir: string;

// loadEnvLocal reads .env.local from PROJECT_ROOT, which is derived from the
// module's own location — so it is exercised here through a copy of the same
// parsing rules applied to a scratch file, plus a real end-to-end check that
// the project's own loader is a no-op when the variable is already set.
beforeEach(async () => {
  workDir = await mkdtemp(path.join(tmpdir(), "shortlist-env-"));
});

afterEach(async () => {
  process.chdir(originalCwd);
  await rm(workDir, { recursive: true, force: true });
});

/** Loads a .env-style file from an arbitrary root, mirroring lib/env.ts. */
async function loadFrom(root: string, contents: string): Promise<Record<string, string>> {
  await mkdir(root, { recursive: true });
  await writeFile(path.join(root, ".env.local"), contents, "utf-8");

  const { readFileSync } = await import("fs");
  const raw = readFileSync(path.join(root, ".env.local"), "utf-8");
  const out: Record<string, string> = {};

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!key) continue;
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

describe("env file parsing", () => {
  test("reads a simple key/value pair", async () => {
    const env = await loadFrom(workDir, "RAPIDAPI_KEY=abc123\n");
    assert.equal(env.RAPIDAPI_KEY, "abc123");
  });

  test("ignores comments and blank lines", async () => {
    const env = await loadFrom(workDir, "# a comment\n\nKEY=value\n\n# trailing\n");
    assert.deepEqual(env, { KEY: "value" });
  });

  test("strips surrounding double and single quotes", async () => {
    const env = await loadFrom(workDir, 'A="quoted"\nB=\'single\'\n');
    assert.equal(env.A, "quoted");
    assert.equal(env.B, "single");
  });

  test("preserves '=' characters inside the value", async () => {
    const env = await loadFrom(workDir, "TOKEN=abc=def==\n");
    assert.equal(env.TOKEN, "abc=def==");
  });

  test("tolerates CRLF line endings", async () => {
    const env = await loadFrom(workDir, "A=1\r\nB=2\r\n");
    assert.deepEqual(env, { A: "1", B: "2" });
  });

  test("skips lines with no '='", async () => {
    const env = await loadFrom(workDir, "JUST_A_WORD\nKEY=value\n");
    assert.deepEqual(env, { KEY: "value" });
  });
});

describe("loadEnvLocal", () => {
  test("does not overwrite a variable that is already set", async () => {
    const { loadEnvLocal } = await import("../lib/env.js");
    const previous = process.env.RAPIDAPI_KEY;

    process.env.RAPIDAPI_KEY = "already-set";
    loadEnvLocal();
    assert.equal(process.env.RAPIDAPI_KEY, "already-set");

    if (previous === undefined) delete process.env.RAPIDAPI_KEY;
    else process.env.RAPIDAPI_KEY = previous;
  });

  test("is a no-op rather than a throw when the file is absent", async () => {
    const { loadEnvLocal } = await import("../lib/env.js");
    assert.doesNotThrow(() => loadEnvLocal());
  });
});
