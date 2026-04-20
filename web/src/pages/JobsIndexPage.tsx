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
        <section className="hero-card skeleton-card">
          <p className="eyebrow">Recap · Jobs</p>
          <h1>Loading jobs…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
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
          <a className="text-link" href="/">
            Return to legacy dashboard
          </a>
        </section>
      </main>
    );
  }

  const total = state.jobs.length;
  const visible = filteredJobs.length;

  return (
    <main className="jobs-shell">
      <section className="jobs-hero">
        <div>
          <p className="eyebrow">Recap · Jobs</p>
          <h1>All jobs</h1>
          <p className="jobs-hero-sub">
            {total === 0
              ? "No jobs yet — start one from the legacy dashboard."
              : `Showing ${visible} of ${total}`}
          </p>
        </div>
        <a className="primary-button" href="/new">
          New job
        </a>
      </section>

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

      {total === 0 ? (
        <section className="hero-card empty-card">
          <h2>No jobs yet</h2>
          <p>
            Create a job from the <a className="text-link" href="/new">
              upload form
            </a>
            . Completed jobs will appear here automatically.
          </p>
        </section>
      ) : visible === 0 ? (
        <section className="hero-card empty-card">
          <h2>No jobs match those filters</h2>
          <p>Try a different search term or status.</p>
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
