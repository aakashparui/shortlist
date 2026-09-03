import { getSavedJobs } from "@/lib/storage";
import { dedupeKey } from "@/lib/sources/index";
import { getStatuses } from "@/lib/statuses";
import type { JobWithStatus } from "@/lib/types";
import JobsBrowser from "./JobsBrowser";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [jobs, statuses] = await Promise.all([getSavedJobs(), getStatuses()]);

  // dedupeKey lives with the source adapters (server-only), so the join
  // happens here rather than in the client component.
  const jobsWithStatus: JobWithStatus[] = jobs.map((job) => {
    const key = dedupeKey(job);
    return { ...job, key, status: statuses[key]?.status ?? "new" };
  });

  return <JobsBrowser jobs={jobsWithStatus} />;
}
