import { useEffect, useMemo, useState } from "react";
import { getJobs, type JobSummary } from "../lib/api";
import JobCard from "../components/JobCard";

type LoadState =
  | { status: "loading" }
  | { status: "loaded"; jobs: JobSummary[] }
  | { status: "error"; message: string };

const STATUS_FILTERS = [
  { value: "all", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "pending", label: "Pending" },
] as const;

type StatusFilter = (typeof STATUS_FILTERS)[number]["value"];

type Stats = {
  total: number;
  completed: number;
  running: number;
  failed: number;
  pending: number;
};

function computeStats(jobs: JobSummary[]): Stats {
  const s: Stats = { total: jobs.length, completed: 0, running: 0, failed: 0, pending: 0 };
  for (const job of jobs) {
    const status = (job.status || "").toLowerCase();
    if (status === "completed") s.completed += 1;
    else if (status === "running") s.running += 1;
    else if (status === "failed") s.failed += 1;
    else s.pending += 1;
  }
  return s;
}

export default function JobsIndexPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    getJobs()
      .then((payload) => {
        if (cancelled) return;
        const jobs = Array.isArray(payload?.jobs) ? payload.jobs : [];
        setState({ status: "loaded", jobs });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Could not load jobs.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filteredJobs = useMemo(() => {
    if (state.status !== "loaded") return [];
    const needle = query.trim().toLowerCase();
    return state.jobs.filter((job) => {
      const status = (job.status || "").toLowerCase();
      if (statusFilter !== "all" && status !== statusFilter) {
        return false;
      }
      if (!needle) return true;
      const haystack = [
        job.job_id,
        job.original_filename,
        job.source_path,
      ]
        .filter(Boolean)
        .map((s) => String(s).toLowerCase());
      return haystack.some((s) => s.includes(needle));
    });
  }, [state, query, statusFilter]);

  if (state.status === "loading") {
    return (
      <main className="jobs-shell">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Recap · Jobs</p>
          <h1>Loading jobs…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
          <div className="skeleton-line" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="jobs-shell">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap · Jobs</p>
          <h1>Unable to load jobs</h1>
          <p>{state.message}</p>
          <div className="job-card-actions">
            <a className="primary-button" href="/">
              Return to legacy dashboard
            </a>
          </div>
        </section>
      </main>
    );
  }

  const stats = computeStats(state.jobs);
  const total = stats.total;
  const visible = filteredJobs.length;

  return (
    <main className="jobs-shell">
      <section className="jobs-hero" aria-label="Jobs overview">
        <div className="jobs-hero-top">
          <div>
            <p className="eyebrow">Recap · Jobs</p>
            <h1>Your transcripts &amp; reports</h1>
            <p className="jobs-hero-sub">
              {total === 0
                ? "No jobs yet — start one from the legacy dashboard to see it here."
                : `Showing ${visible} of ${total}`}
            </p>
          </div>
          <a className="primary-button" href="/new">
            New job
          </a>
        </div>
        {total > 0 ? (
          <dl className="jobs-hero-stats" aria-label="Job totals">
            <div className="jobs-stat">
              <dt className="jobs-stat-label">Total</dt>
              <dd className="jobs-stat-value">{stats.total}</dd>
            </div>
            <div className="jobs-stat completed">
              <dt className="jobs-stat-label">Completed</dt>
              <dd className="jobs-stat-value">{stats.completed}</dd>
            </div>
            <div className="jobs-stat running">
              <dt className="jobs-stat-label">Running</dt>
              <dd className="jobs-stat-value">{stats.running}</dd>
            </div>
            <div className="jobs-stat failed">
              <dt className="jobs-stat-label">Failed</dt>
              <dd className="jobs-stat-value">{stats.failed}</dd>
            </div>
            <div className="jobs-stat">
              <dt className="jobs-stat-label">Pending</dt>
              <dd className="jobs-stat-value">{stats.pending}</dd>
            </div>
          </dl>
        ) : null}
      </section>

      {total > 0 ? (
        <section className="jobs-controls" aria-label="Filter jobs">
          <label className="jobs-search">
            <span className="visually-hidden">Search jobs</span>
            <input
              type="search"
              placeholder="Search by filename or job id"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div
            className="jobs-status-filter"
            role="radiogroup"
            aria-label="Status"
          >
            {STATUS_FILTERS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={statusFilter === option.value}
                className={`status-pill ${
                  statusFilter === option.value ? "active" : ""
                }`}
                onClick={() => setStatusFilter(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {total === 0 ? (
        <section className="hero-card empty-card">
          <p className="eyebrow">Empty</p>
          <h2>No jobs yet</h2>
          <p>
            Create a job from the <a className="text-link" href="/new">
              upload form
            </a>
            {" "}on the legacy dashboard. Completed jobs will appear here
            automatically.
          </p>
        </section>
      ) : visible === 0 ? (
        <section className="hero-card empty-card">
          <p className="eyebrow">No matches</p>
          <h2>No jobs match those filters</h2>
          <p>
            Try a different search term or status. You can also{" "}
            <button
              type="button"
              className="text-link"
              onClick={() => {
                setQuery("");
                setStatusFilter("all");
              }}
              style={{ background: "none", border: 0, padding: 0 }}
            >
              reset all filters
            </button>
            .
          </p>
        </section>
      ) : (
        <section className="jobs-grid" aria-label="Jobs">
          {filteredJobs.map((job) => (
            <JobCard key={job.job_id} job={job} />
          ))}
        </section>
      )}
    </main>
  );
}
