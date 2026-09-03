import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { dedupeKey } from "../lib/sources/index.js";
import type { Job } from "../lib/types.js";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "id-1",
    title: "Payments Analyst",
    company: "Acme Corp",
    location: "Bengaluru, Karnataka, India",
    postedDate: "2026-08-20T00:00:00.000Z",
    description: "desc",
    applyUrl: "https://example.com/apply",
    source: "jsearch",
    ...overrides,
  };
}

describe("dedupeKey", () => {
  test("is case-insensitive", () => {
    assert.equal(
      dedupeKey(job({ company: "ACME CORP", title: "PAYMENTS ANALYST" })),
      dedupeKey(job({ company: "acme corp", title: "payments analyst" }))
    );
  });

  test("collapses runs of whitespace and trims", () => {
    assert.equal(
      dedupeKey(job({ company: "  Acme   Corp ", title: "Payments\t\tAnalyst" })),
      dedupeKey(job({ company: "Acme Corp", title: "Payments Analyst" }))
    );
  });

  test("ignores the source-specific id", () => {
    assert.equal(dedupeKey(job({ id: "aaa" })), dedupeKey(job({ id: "zzz" })));
  });

  test("ignores fields that change between fetches", () => {
    assert.equal(
      dedupeKey(job({ postedDate: "2020-01-01T00:00:00.000Z", applyUrl: "https://other" })),
      dedupeKey(job())
    );
  });

  test("distinguishes different companies, titles and locations", () => {
    const base = dedupeKey(job());
    assert.notEqual(base, dedupeKey(job({ company: "Other Corp" })));
    assert.notEqual(base, dedupeKey(job({ title: "Billing Analyst" })));
    assert.notEqual(base, dedupeKey(job({ location: "Pune, Maharashtra, India" })));
  });

  test("treats empty and missing values as equivalent", () => {
    const withEmpty = dedupeKey(job({ location: "" }));
    const withNull = dedupeKey(job({ location: null as unknown as string }));
    assert.equal(withEmpty, withNull);
  });

  test("does not collide across field boundaries", () => {
    // "ab" + "c" must not equal "a" + "bc" once joined.
    assert.notEqual(
      dedupeKey(job({ company: "ab", title: "c", location: "x" })),
      dedupeKey(job({ company: "a", title: "bc", location: "x" }))
    );
  });
});
