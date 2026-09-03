import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

/**
 * Project root, derived from this file's location rather than process.cwd(),
 * so scripts work no matter which directory they're launched from — which
 * matters for Task Scheduler, where the working directory is not the project.
 */
export const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Loads .env.local into process.env. Next.js does this automatically, but
 * scripts run through tsx do not, so without this a scheduled run would
 * fail with "Missing RAPIDAPI_KEY" even though the web UI works fine.
 *
 * Existing environment variables always win, so an explicitly exported
 * value can still override the file.
 */
export function loadEnvLocal(): void {
  const envPath = path.join(PROJECT_ROOT, ".env.local");

  let raw: string;
  try {
    raw = readFileSync(envPath, "utf-8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return;
    throw err;
  }

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;

    const key = trimmed.slice(0, eq).trim();
    if (!key || key in process.env) continue;

    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    process.env[key] = value;
  }
}
