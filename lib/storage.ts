import { mkdir, readFile, writeFile } from "fs/promises";
import path from "path";
import type { Job } from "./types.js";
import { dedupeKey } from "./sources/index.js";

// Resolved per call rather than at module load: scripts chdir to the project
// root on startup, and a value captured at import time could be stale.
const dataDir = () => path.join(process.cwd(), "data");
const jsonPath = () => path.join(dataDir(), "jobs.json");
const csvPath = () => path.join(dataDir(), "jobs.csv");

const CSV_COLUMNS: (keyof Job)[] = [
  "id",
  "title",
  "company",
  "location",
  "postedDate",
  "applyUrl",
  "source",
  "description",
];

export async function getSavedJobs(): Promise<Job[]> {
  try {
    const raw = await readFile(jsonPath(), "utf-8");
    return JSON.parse(raw) as Job[];
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
}

function escapeCsvField(value: string): string {
  if (/[",\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function toCsv(jobs: Job[]): string {
  const header = CSV_COLUMNS.join(",");
  const rows = jobs.map((job) =>
    CSV_COLUMNS.map((col) => escapeCsvField(String(job[col] ?? ""))).join(",")
  );
  return [header, ...rows].join("\n") + "\n";
}

export interface SaveResult {
  newlyAdded: number;
  totalSaved: number;
  /** The jobs that were actually new this run, for reporting what changed. */
  added: Job[];
}

export async function saveJobs(newJobs: Job[]): Promise<SaveResult> {
  await mkdir(dataDir(), { recursive: true });

  const existingJobs = await getSavedJobs();
  const seen = new Set(existingJobs.map(dedupeKey));

  const merged = [...existingJobs];
  const added: Job[] = [];

  for (const job of newJobs) {
    const key = dedupeKey(job);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(job);
    added.push(job);
  }

  await writeFile(jsonPath(), JSON.stringify(merged, null, 2), "utf-8");
  await writeFile(csvPath(), toCsv(merged), "utf-8");

  return { newlyAdded: added.length, totalSaved: merged.length, added };
}
