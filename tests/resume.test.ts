import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { analyzeResumeHeuristic } from "../lib/resume/heuristic.js";
import { analyzeResume, EmptyResumeError } from "../lib/resume/index.js";

const realKey = process.env.ANTHROPIC_API_KEY;

const PAYMENTS_RESUME = `
Akash Kumar — Chennai, India

Summary
Payments Analyst with 4 years processing cross-border payments and trade remittance
transactions for a global bank.

Experience
Senior Payments Analyst, Mizuho — Chennai
- Created and processed SWIFT payment messages including MT103 and MT202.
- Processed and understood ISO 20022 payment messages.
- Handled reconciliation of nostro accounts and daily settlement breaks.

Payments Analyst, HSBC — Chennai
- Investigated payment rejections and coordinated with correspondent banks.

Skills
SWIFT messaging, ISO 20022, reconciliation, Excel, SQL
`;

const FRONTEND_RESUME = `
Priya Sharma — Bengaluru, India

Summary
Frontend developer building single page applications for five years.

Experience
Frontend Developer, Acme — Bengaluru
- Built dashboards in React and TypeScript.
- Migrated a large Angular codebase to React.

Skills
React, TypeScript, JavaScript, Figma, Git
`;

beforeEach(() => {
  delete process.env.ANTHROPIC_API_KEY;
});

afterEach(() => {
  if (realKey === undefined) delete process.env.ANTHROPIC_API_KEY;
  else process.env.ANTHROPIC_API_KEY = realKey;
});

describe("analyzeResumeHeuristic", () => {
  test("ranks the stated job title first", () => {
    const result = analyzeResumeHeuristic(PAYMENTS_RESUME);
    assert.equal(result.searches[0].query, "payments analyst");
  });

  test("distinguishes a different profession", () => {
    const result = analyzeResumeHeuristic(FRONTEND_RESUME);
    assert.equal(result.searches[0].query, "frontend developer");
    assert.ok(!result.searches.some((s) => s.query === "payments analyst"));
  });

  test("infers a role from skills even when the title is absent", () => {
    const result = analyzeResumeHeuristic(
      "Experienced professional. Skills: Power BI, DAX, SQL, data modelling, dashboards. " +
        "Built reporting for finance teams across three regions over several years."
    );
    assert.ok(
      result.searches.some((s) => s.query === "power bi developer"),
      "Power BI + DAX should imply a Power BI role"
    );
  });

  test("gives a stated title more weight than a skill-implied one", () => {
    const result = analyzeResumeHeuristic(FRONTEND_RESUME);
    const frontend = result.searches.find((s) => s.query === "frontend developer");
    const others = result.searches.filter((s) => s.query !== "frontend developer");
    for (const other of others) {
      assert.ok(
        frontend!.confidence >= other.confidence,
        `frontend developer should outrank ${other.query}`
      );
    }
  });

  test("detects the city rather than the country when both appear", () => {
    assert.equal(analyzeResumeHeuristic(PAYMENTS_RESUME).location, "chennai");
    assert.equal(analyzeResumeHeuristic(FRONTEND_RESUME).location, "bengaluru");
  });

  test("returns null location when none is recognizable", () => {
    const result = analyzeResumeHeuristic(
      "A candidate with SQL and Excel experience across several reporting projects."
    );
    assert.equal(result.location, null);
  });

  test("lists detected skills", () => {
    const skills = analyzeResumeHeuristic(FRONTEND_RESUME).skills;
    assert.ok(skills.includes("react"));
    assert.ok(skills.includes("typescript"));
    assert.ok(skills.includes("figma"));
  });

  test("reads SWIFT on a banking resume as the payment network, not the language", () => {
    const result = analyzeResumeHeuristic(PAYMENTS_RESUME);
    assert.ok(
      !result.searches.some((s) => s.query === "ios developer"),
      "SWIFT messaging must not imply iOS development"
    );
    assert.ok(!result.skills.includes("swift"), "bare 'swift' chip should be suppressed");
    assert.ok(result.skills.includes("swift messaging"));
  });

  test("still reads Swift as the language on a mobile resume", () => {
    const result = analyzeResumeHeuristic(
      "Mobile engineer with six years building iPhone apps. Skills: Swift, Xcode, UIKit. " +
        "Shipped several consumer applications to the App Store over that period."
    );
    assert.ok(result.searches.some((s) => s.query === "ios developer"));
  });

  test("does not match a skill inside a longer word", () => {
    // "reactor" must not register as "react".
    const result = analyzeResumeHeuristic(
      "Nuclear reactor technician. Managed reactor maintenance schedules and safety audits " +
        "for a large industrial plant across a ten year career in the energy sector."
    );
    assert.ok(!result.skills.includes("react"));
  });

  test("never returns more than five suggestions", () => {
    const kitchenSink =
      PAYMENTS_RESUME + FRONTEND_RESUME + " Power BI Tableau Kubernetes Selenium Django Swift";
    assert.ok(analyzeResumeHeuristic(kitchenSink).searches.length <= 5);
  });

  test("confidence is normalized to the 0–1 range", () => {
    for (const s of analyzeResumeHeuristic(PAYMENTS_RESUME).searches) {
      assert.ok(s.confidence > 0 && s.confidence <= 1, `${s.query}: ${s.confidence}`);
    }
  });

  test("every suggestion carries a reason", () => {
    for (const s of analyzeResumeHeuristic(PAYMENTS_RESUME).searches) {
      assert.ok(s.reason.length > 0);
    }
  });
});

describe("analyzeResume", () => {
  test("uses the heuristic when no Anthropic key is set", async () => {
    const result = await analyzeResume(PAYMENTS_RESUME);
    assert.equal(result.method, "heuristic");
    assert.ok(result.searches.length > 0);
  });

  test("rejects text too short to be a resume", async () => {
    await assert.rejects(() => analyzeResume("analyst"), EmptyResumeError);
  });

  test("rejects whitespace-only input", async () => {
    await assert.rejects(() => analyzeResume("   \n\n   "), EmptyResumeError);
  });

  test("falls back to the heuristic when the Claude call fails", async () => {
    // A syntactically valid but unusable key: the SDK will reject the call,
    // and the orchestrator should degrade rather than surface an error.
    process.env.ANTHROPIC_API_KEY = "sk-ant-invalid-key-for-testing";
    const result = await analyzeResume(PAYMENTS_RESUME);

    assert.equal(result.method, "heuristic");
    assert.ok(result.fallbackReason, "should record why it fell back");
    assert.ok(result.searches.length > 0, "should still produce suggestions");
  });
});
