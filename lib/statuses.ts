import { mkdir, readFile, writeFile } from "fs/promises";
import path from "path";
import type { JobStatus } from "./types.js";

// Resolved per call — see the note in storage.ts.
const dataDir = () => path.join(process.cwd(), "data");
const statusPath = () => path.join(dataDir(), "statuses.json");

export interface StatusEntry {
  status: JobStatus;
  updatedAt: string;
}

export type StatusMap = Record<string, StatusEntry>;

/**
 * Serializes read-modify-write cycles. Clicking several status buttons in
 * quick succession fires overlapping requests, and without this the later
 * write would be based on a snapshot taken before the earlier one landed,
 * silently dropping it.
 */
let writeQueue: Promise<unknown> = Promise.resolve();

function enqueue<T>(task: () => Promise<T>): Promise<T> {
  const run = writeQueue.then(task, task);
  writeQueue = run.catch(() => {});
  return run;
}

export async function getStatuses(): Promise<StatusMap> {
  try {
    const raw = await readFile(statusPath(), "utf-8");
    return JSON.parse(raw) as StatusMap;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw err;
  }
}

export async function setStatus(key: string, status: JobStatus): Promise<StatusMap> {
  return enqueue(async () => {
    await mkdir(dataDir(), { recursive: true });
    const statuses = await getStatuses();

    if (status === "new") {
      delete statuses[key];
    } else {
      statuses[key] = { status, updatedAt: new Date().toISOString() };
    }

    await writeFile(statusPath(), JSON.stringify(statuses, null, 2), "utf-8");
    return statuses;
  });
}
