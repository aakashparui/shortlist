"use client";

import { useEffect, useMemo, useState } from "react";
import type { JobStatus, JobWithStatus } from "@/lib/types";
import FetchForm, { type Prefill } from "./FetchForm";
import ResumePanel from "./ResumePanel";
import {
  Layers,
  MapPin,
  ExternalLink,
  Calendar,
  Globe,
  SlidersHorizontal,
  ArrowDownWideNarrow,
  ArrowUpWideNarrow,
  SearchX,
  Inbox,
} from "lucide-react";

const ACTIONS: { status: Exclude<JobStatus, "new">; label: string }[] = [
  { status: "interested", label: "Interested" },
  { status: "applied", label: "Applied" },
  { status: "dismissed", label: "Dismissed" },
];

const STATUS_LABELS: Record<JobStatus, string> = {
  new: "New",
  interested: "Interested",
  applied: "Applied",
  dismissed: "Dismissed",
};

type StatusFilter = "active" | "all" | JobStatus;

function formatDate(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "Unknown date";
  return new Date(t).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function toStatusMap(jobs: JobWithStatus[]): Record<string, JobStatus> {
  return Object.fromEntries(jobs.map((j) => [j.key, j.status]));
}

/** Initials for the card avatar, e.g. "Turner Construction" -> "TC". */
function initials(company: string): string {
  const words = company.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Deterministic hue per company, so a given employer keeps one colour. */
function monogramStyle(company: string): React.CSSProperties {
  let hash = 0;
  for (let i = 0; i < company.length; i++) {
    hash = (hash * 31 + company.charCodeAt(i)) % 360;
  }
  return {
    background: `hsl(${hash} 62% 94%)`,
    color: `hsl(${hash} 55% 34%)`,
  };
}

export default function JobsBrowser({ jobs }: { jobs: JobWithStatus[] }) {
  const [search, setSearch] = useState("");
  const [company, setCompany] = useState("all");
  const [location, setLocation] = useState("all");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [prefill, setPrefill] = useState<Prefill | undefined>();

  // Local copy so clicks apply instantly; the server write happens in the
  // background and only rolls this back if it fails.
  const [statusMap, setStatusMap] = useState(() => toStatusMap(jobs));
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  // Re-seed when the server sends new data (e.g. after fetching more jobs).
  useEffect(() => {
    setStatusMap(toStatusMap(jobs));
  }, [jobs]);

  const companies = useMemo(
    () => Array.from(new Set(jobs.map((j) => j.company))).sort(),
    [jobs]
  );
  const locations = useMemo(
    () => Array.from(new Set(jobs.map((j) => j.location))).sort(),
    [jobs]
  );

  const counts = useMemo(() => {
    const c: Record<JobStatus, number> = { new: 0, interested: 0, applied: 0, dismissed: 0 };
    for (const job of jobs) c[statusMap[job.key] ?? "new"]++;
    return c;
  }, [jobs, statusMap]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return jobs
      .filter((j) => {
        const status = statusMap[j.key] ?? "new";
        if (statusFilter === "active") return status !== "dismissed";
        if (statusFilter === "all") return true;
        return status === statusFilter;
      })
      .filter((j) => company === "all" || j.company === company)
      .filter((j) => location === "all" || j.location === location)
      .filter(
        (j) =>
          !q ||
          j.title.toLowerCase().includes(q) ||
          j.company.toLowerCase().includes(q) ||
          j.description.toLowerCase().includes(q)
      )
      .sort((a, b) => {
        const da = Date.parse(a.postedDate) || 0;
        const db = Date.parse(b.postedDate) || 0;
        return sortDir === "desc" ? db - da : da - db;
      });
  }, [jobs, search, company, location, sortDir, statusFilter, statusMap]);

  async function updateStatus(key: string, clicked: Exclude<JobStatus, "new">) {
    const previous = statusMap[key] ?? "new";
    // Clicking the active status again clears it back to "new".
    const next: JobStatus = previous === clicked ? "new" : clicked;

    setStatusMap((m) => ({ ...m, [key]: next }));
    setPending((p) => new Set(p).add(key));
    setError("");

    try {
      const res = await fetch("/api/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, status: next }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? "Could not save status.");
      }
    } catch (err) {
      setStatusMap((m) => ({ ...m, [key]: previous }));
      setError(err instanceof Error ? err.message : "Could not save status.");
    } finally {
      setPending((p) => {
        const nextPending = new Set(p);
        nextPending.delete(key);
        return nextPending;
      });
    }
  }

  const hasJobs = jobs.length > 0;

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">
            <Layers size={20} strokeWidth={2.2} />
          </span>
          <div className="brand-text">
            <h1>Shortlist</h1>
            <p>Track roles worth pursuing</p>
          </div>
        </div>

        {hasJobs && (
          <div className="header-stats">
            <div className="hstat">
              <span className="hstat-value">{jobs.length}</span>
              <span className="hstat-label">Total</span>
            </div>
            <div className="hstat hstat-new">
              <span className="hstat-value">{counts.new}</span>
              <span className="hstat-label">New</span>
            </div>
            <div className="hstat hstat-interested">
              <span className="hstat-value">{counts.interested}</span>
              <span className="hstat-label">Saved</span>
            </div>
            <div className="hstat hstat-applied">
              <span className="hstat-value">{counts.applied}</span>
              <span className="hstat-label">Applied</span>
            </div>
          </div>
        )}
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <ResumePanel
            onPick={(query, location) =>
              setPrefill({ query, location: location ?? "", nonce: Date.now() })
            }
          />
          <FetchForm prefill={prefill} />

          {hasJobs && (
            <div className="panel">
              <h2 className="panel-title">
                <SlidersHorizontal size={13} /> Filters
              </h2>

              <div className="field">
                <label className="field-label" htmlFor="f-search">
                  Search
                </label>
                <input
                  id="f-search"
                  type="text"
                  placeholder="Title, company, keyword…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>

              <div className="field">
                <label className="field-label" htmlFor="f-status">
                  Status
                </label>
                <select
                  id="f-status"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
                >
                  <option value="active">Active (hide dismissed)</option>
                  <option value="all">All statuses</option>
                  <option value="new">New only</option>
                  <option value="interested">Interested only</option>
                  <option value="applied">Applied only</option>
                  <option value="dismissed">Dismissed only</option>
                </select>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="f-company">
                  Company
                </label>
                <select
                  id="f-company"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                >
                  <option value="all">All companies</option>
                  {companies.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label className="field-label" htmlFor="f-location">
                  Location
                </label>
                <select
                  id="f-location"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                >
                  <option value="all">All locations</option>
                  {locations.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
        </aside>

        <section className="feed">
          {!hasJobs ? (
            <div className="zero-state">
              <Inbox size={34} strokeWidth={1.5} />
              <h2>No roles yet</h2>
              <p>Run your first search from the panel, or use the CLI:</p>
              <code>npm run fetch-jobs &quot;payments analyst&quot; &quot;India&quot;</code>
            </div>
          ) : (
            <>
              <div className="feed-bar">
                <span className="feed-count">
                  Showing <strong>{filtered.length}</strong> of {jobs.length} roles
                </span>
                <button
                  type="button"
                  className="sort-toggle"
                  onClick={() => setSortDir((d) => (d === "desc" ? "asc" : "desc"))}
                >
                  {sortDir === "desc" ? (
                    <>
                      <ArrowDownWideNarrow size={14} /> Newest first
                    </>
                  ) : (
                    <>
                      <ArrowUpWideNarrow size={14} /> Oldest first
                    </>
                  )}
                </button>
              </div>

              {error && <p className="msg msg-error">{error}</p>}

              {filtered.length === 0 ? (
                <div className="zero-state">
                  <SearchX size={34} strokeWidth={1.5} />
                  <h2>No matches</h2>
                  <p>No roles match your current filters.</p>
                </div>
              ) : (
                <ul className="job-list">
                  {filtered.map((job) => {
                    const status = statusMap[job.key] ?? "new";
                    const isPending = pending.has(job.key);
                    return (
                      <li
                        key={job.key}
                        className={`job-card job-card-${status}${
                          isPending ? " job-card-pending" : ""
                        }`}
                      >
                        <div className="job-top">
                          <span
                            className="monogram"
                            style={monogramStyle(job.company)}
                            aria-hidden="true"
                          >
                            {initials(job.company)}
                          </span>
                          <div className="job-headline">
                            <h3 className="job-title">{job.title}</h3>
                            <p className="job-company">{job.company}</p>
                          </div>
                          {status !== "new" && (
                            <span className={`status-badge status-badge-${status}`}>
                              {STATUS_LABELS[status]}
                            </span>
                          )}
                        </div>

                        <div className="job-meta">
                          <span className="meta-chip">
                            <MapPin size={13} /> {job.location || "Unspecified"}
                          </span>
                          <span className="meta-chip">
                            <Calendar size={13} /> {formatDate(job.postedDate)}
                          </span>
                          <span className="meta-chip">
                            <Globe size={13} /> {job.source}
                          </span>
                        </div>

                        <p className="job-description">{job.description}</p>

                        <div className="job-footer">
                          <a
                            href={job.applyUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="apply-link"
                          >
                            Apply <ExternalLink size={14} />
                          </a>
                          <div className="status-buttons">
                            {ACTIONS.map(({ status: s, label }) => (
                              <button
                                key={s}
                                type="button"
                                data-status={s}
                                className={`status-button${status === s ? " is-active" : ""}`}
                                aria-pressed={status === s}
                                disabled={isPending}
                                onClick={() => updateStatus(job.key, s)}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
