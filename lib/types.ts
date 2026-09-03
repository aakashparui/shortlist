export interface Job {
  id: string;
  title: string;
  company: string;
  location: string;
  postedDate: string;
  description: string;
  applyUrl: string;
  source: string;
}

/** Per-call tuning shared by every source adapter. */
export interface FetchOptions {
  /**
   * Maximum result pages to walk. Each page is one API round trip, so this
   * trades freshness of coverage against latency and request quota.
   */
  maxPages?: number;
}

export const JOB_STATUSES = ["new", "interested", "applied", "dismissed"] as const;

export type JobStatus = (typeof JOB_STATUSES)[number];

/**
 * A saved job paired with its tracked status. `key` is the normalized
 * company+title+location hash used everywhere as a job's stable identity —
 * it survives re-fetches, unlike the source-specific `id`.
 */
export interface JobWithStatus extends Job {
  key: string;
  status: JobStatus;
}
