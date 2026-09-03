import type { ResumeAnalysis, SuggestedSearch } from "./types.js";

/**
 * Role titles worth searching for, grouped by the domain they belong to.
 * Matching is on whole phrases, so "data analyst" beats a bare "analyst".
 */
const ROLE_TITLES: string[] = [
  "payments analyst",
  "payment operations analyst",
  "business analyst",
  "data analyst",
  "data engineer",
  "data scientist",
  "business intelligence analyst",
  "bi developer",
  "bi analyst",
  "power bi developer",
  "financial analyst",
  "finance analyst",
  "billing analyst",
  "operations analyst",
  "product analyst",
  "reporting analyst",
  "reconciliation analyst",
  "settlements analyst",
  "risk analyst",
  "credit analyst",
  "treasury analyst",
  "supply chain analyst",
  "quality analyst",
  "systems analyst",
  "frontend developer",
  "front end developer",
  "backend developer",
  "full stack developer",
  "software engineer",
  "software developer",
  "web developer",
  "mobile developer",
  "android developer",
  "ios developer",
  "devops engineer",
  "cloud engineer",
  "platform engineer",
  "qa engineer",
  "automation engineer",
  "test engineer",
  "machine learning engineer",
  "analytics engineer",
  "product manager",
  "project manager",
  "program manager",
  "account manager",
  "operations manager",
  "consultant",
  "accountant",
  "auditor",
  "ui ux designer",
  "product designer",
  "graphic designer",
];

/**
 * Skills that imply a role even when the resume never names that title —
 * someone listing DAX and Power BI is a BI candidate whether or not the
 * words "BI developer" appear anywhere.
 */
/**
 * Skills whose name is ambiguous across domains. If any disqualifying phrase
 * is present, the skill is not counted — "SWIFT" on a banking resume means the
 * payment messaging network, not Apple's language.
 */
const AMBIGUOUS_SKILLS: Record<string, string[]> = {
  swift: ["swift messaging", "swift mt", "swift payment", "swift code", "iso 20022", "mt103"],
  spark: ["spark plug"],
  go: ["go to market"],
};

const SKILL_TO_ROLE: { skill: string; role: string }[] = [
  { skill: "power bi", role: "power bi developer" },
  { skill: "tableau", role: "business intelligence analyst" },
  { skill: "looker", role: "business intelligence analyst" },
  { skill: "dax", role: "power bi developer" },
  { skill: "sql", role: "data analyst" },
  { skill: "excel", role: "business analyst" },
  { skill: "python", role: "data analyst" },
  { skill: "pandas", role: "data analyst" },
  { skill: "react", role: "frontend developer" },
  { skill: "angular", role: "frontend developer" },
  { skill: "vue", role: "frontend developer" },
  { skill: "javascript", role: "frontend developer" },
  { skill: "typescript", role: "frontend developer" },
  { skill: "node.js", role: "backend developer" },
  { skill: "django", role: "backend developer" },
  { skill: "spring boot", role: "backend developer" },
  { skill: "kubernetes", role: "devops engineer" },
  { skill: "terraform", role: "devops engineer" },
  { skill: "docker", role: "devops engineer" },
  { skill: "selenium", role: "qa engineer" },
  { skill: "swift", role: "ios developer" },
  { skill: "kotlin", role: "android developer" },
  { skill: "figma", role: "product designer" },
  { skill: "swift messaging", role: "payments analyst" },
  { skill: "iso 20022", role: "payments analyst" },
  { skill: "reconciliation", role: "reconciliation analyst" },
  { skill: "accounts payable", role: "billing analyst" },
];

/** Skills surfaced to the user, independent of role inference. */
const SKILLS: string[] = [
  ...new Set(SKILL_TO_ROLE.map((s) => s.skill)),
  "power query",
  "snowflake",
  "airflow",
  "spark",
  "aws",
  "azure",
  "gcp",
  "git",
  "jira",
  "sap",
  "oracle",
  "tally",
  "salesforce",
];

/** Indian cities plus a few common country names, for location detection. */
const LOCATIONS: string[] = [
  "bengaluru",
  "bangalore",
  "mumbai",
  "delhi",
  "new delhi",
  "gurgaon",
  "gurugram",
  "noida",
  "hyderabad",
  "chennai",
  "pune",
  "kolkata",
  "ahmedabad",
  "jaipur",
  "kochi",
  "coimbatore",
  "chandigarh",
  "indore",
  "india",
  "singapore",
  "dubai",
  "london",
  "remote",
];

/** Seniority prefixes we strip before matching, then re-apply for display. */
const SENIORITY = ["senior", "lead", "principal", "junior", "associate", "sr", "jr"];

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[‐-―]/g, "-")
    .replace(/[^a-z0-9+.#\s-]/g, " ")
    .replace(/\s+/g, " ");
}

/** Counts non-overlapping whole-phrase occurrences of `phrase` in `text`. */
function countPhrase(text: string, phrase: string): number {
  const escaped = phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matches = text.match(new RegExp(`(?<![a-z0-9])${escaped}(?![a-z0-9])`, "g"));
  return matches ? matches.length : 0;
}

/** True when a skill is present and not disqualified by its context. */
function hasSkill(text: string, skill: string): boolean {
  if (countPhrase(text, skill) === 0) return false;
  const disqualifiers = AMBIGUOUS_SKILLS[skill];
  if (disqualifiers?.some((phrase) => countPhrase(text, phrase) > 0)) return false;
  return true;
}

function detectSkills(text: string): string[] {
  const found = SKILLS.filter((skill) => hasSkill(text, skill));
  // Drop a skill that is wholly contained in another match, so "SWIFT
  // messaging" doesn't also surface a bare "swift" chip beside it.
  return found
    .filter((skill) => !found.some((other) => other !== skill && other.includes(skill)))
    .sort();
}

function detectLocation(text: string): string | null {
  // Prefer the most specific match: a city beats the bare country name.
  const hits = LOCATIONS.filter((loc) => countPhrase(text, loc) > 0);
  if (hits.length === 0) return null;
  const city = hits.find((h) => h !== "india" && h !== "remote");
  return city ?? hits[0];
}

function titleCase(value: string): string {
  return value.replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

/**
 * Derives search suggestions from resume text without calling any model.
 * Titles named outright in the resume score highest; roles implied only by
 * skills score lower, and are capped so they can't outrank explicit titles.
 */
export function analyzeResumeHeuristic(resumeText: string): ResumeAnalysis {
  const text = normalize(resumeText);
  const scores = new Map<string, { score: number; reasons: string[] }>();

  const bump = (role: string, amount: number, reason: string) => {
    const entry = scores.get(role) ?? { score: 0, reasons: [] };
    entry.score += amount;
    if (!entry.reasons.includes(reason)) entry.reasons.push(reason);
    scores.set(role, entry);
  };

  // 1. Titles stated in the resume.
  for (const title of ROLE_TITLES) {
    const count = countPhrase(text, title);
    if (count > 0) {
      bump(title, 3 + Math.min(count - 1, 3), `titled "${titleCase(title)}" in your resume`);
    }

    // Also catch "senior payments analyst" when the list has "payments analyst".
    for (const level of SENIORITY) {
      if (countPhrase(text, `${level} ${title}`) > 0) {
        bump(title, 1, `appears as ${titleCase(level)} ${titleCase(title)}`);
      }
    }
  }

  // 2. Roles implied by skills, capped below the weight of a stated title.
  const skillRoleHits = new Map<string, string[]>();
  for (const { skill, role } of SKILL_TO_ROLE) {
    if (hasSkill(text, skill)) {
      const list = skillRoleHits.get(role) ?? [];
      list.push(skill);
      skillRoleHits.set(role, list);
    }
  }
  for (const [role, skills] of skillRoleHits) {
    const weight = Math.min(skills.length, 2.5);
    bump(role, weight, `skills present: ${skills.map(titleCase).join(", ")}`);
  }

  const ranked = [...scores.entries()]
    .sort((a, b) => b[1].score - a[1].score || a[0].localeCompare(b[0]))
    .slice(0, 5);

  const topScore = ranked[0]?.[1].score ?? 1;
  const searches: SuggestedSearch[] = ranked.map(([role, { score, reasons }]) => ({
    query: role,
    reason: reasons[0],
    confidence: Math.round(Math.min(score / Math.max(topScore, 1), 1) * 100) / 100,
  }));

  return {
    searches,
    skills: detectSkills(text),
    location: detectLocation(text),
    method: "heuristic",
  };
}
