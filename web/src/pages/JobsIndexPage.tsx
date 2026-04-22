import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  getJobs,
  getLibrary,
  saveJobMetadata,
  type JobMetadataPatch,
  type JobSummary,
  type LibrarySummary,
} from "../lib/api";
import JobCard from "../components/JobCard";

type View = "active" | "archived";

type LoadState =
  | { status: "loading" }
  | {
      status: "loaded";
      jobs: JobSummary[];
      library: LibrarySummary | null;
      view: View;
    }
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
  const s: Stats = {
    total: jobs.length,
    completed: 0,
    running: 0,
    failed: 0,
    pending: 0,
  };
  for (const job of jobs) {
    const status = (job.status || "").toLowerCase();
    if (status === "completed") s.completed += 1;
    else if (status === "running") s.running += 1;
    else if (status === "failed") s.failed += 1;
    else s.pending += 1;
  }
  return s;
}

const ALL_PROJECTS = "__all__";
const NO_PROJECT = "__none__";

export default function JobsIndexPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [projectFilter, setProjectFilter] = useState<string>(ALL_PROJECTS);
  const [view, setView] = useState<View>("active");

  const load = useCallback((nextView: View) => {
    setState({ status: "loading" });
    // Archived view wants the full listing (server filter is default-
    // exclude archived, so we pass include_archived=1 and then
    // narrow client-side to the archived rows).
    Promise.all([getJobs(nextView === "archived"), getLibrary()])
      .then(([jobsPayload, library]) => {
        const raw = Array.isArray(jobsPayload?.jobs) ? jobsPayload.jobs : [];
        const filtered = raw.filter((j) =>
          nextView === "archived" ? !!j.archived : !j.archived,
        );
        setState({
          status: "loaded",
          jobs: filtered,
          library,
          view: nextView,
        });
      })
      .catch((err) => {
        setState({
          status: "error",
          message:
            err instanceof Error ? err.message : "Could not load jobs.",
        });
      });
  }, []);

  useEffect(() => {
    load(view);
  }, [load, view]);

  const handleSaveJobMetadata = useCallback(
    async (jobId: string, patch: JobMetadataPatch) => {
      const updated = await saveJobMetadata(jobId, patch);
      setState((curr) => {
        if (curr.status !== "loaded") return curr;
        // If the job changed archived state, drop it from the list
        // when it no longer matches the current view.
        const keepInView =
          curr.view === "archived" ? !!updated.archived : !updated.archived;
        const nextJobs = keepInView
          ? curr.jobs.map((j) => (j.job_id === jobId ? updated : j))
          : curr.jobs.filter((j) => j.job_id !== jobId);
        return { ...curr, jobs: nextJobs };
      });
      // Refresh library rollups in the background so project counts
      // stay accurate without forcing a full reload.
      getLibrary()
        .then((library) => {
          setState((curr) =>
            curr.status === "loaded" ? { ...curr, library } : curr,
          );
        })
        .catch(() => undefined);
    },
    [],
  );

  const filteredJobs = useMemo(() => {
    if (state.status !== "loaded") return [] as JobSummary[];
    const needle = query.trim().toLowerCase();
    return state.jobs.filter((job) => {
      const status = (job.status || "").toLowerCase();
      if (statusFilter !== "all" && status !== statusFilter) {
        return false;
      }
      if (projectFilter === NO_PROJECT) {
        if (job.project) return false;
      } else if (projectFilter !== ALL_PROJECTS) {
        if (job.project !== projectFilter) return false;
      }
      if (!needle) return true;
      const haystack = [
        job.job_id,
        job.display_title,
        job.custom_title ?? "",
        job.original_filename,
        job.source_path,
        job.project ?? "",
      ]
        .filter(Boolean)
        .map((s) => String(s).toLowerCase());
      return haystack.some((s) => s.includes(needle));
    });
  }, [state, query, statusFilter, projectFilter]);

  if (state.status === "loading") {
    return (
      <main className="jobs-shell">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Library</p>
          <h1>Loading library…</h1>
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
          <p className="eyebrow">Library</p>
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
  const library = state.library;
  const libraryCounts = library?.counts ?? {
    total: total,
    active: state.view === "active" ? total : 0,
    archived: state.view === "archived" ? total : 0,
  };
  const projects = library?.projects ?? [];

  return (
    <main className="jobs-shell">
      <section className="jobs-hero" aria-label="Jobs overview">
        <div className="jobs-hero-top">
          <div className="jobs-hero-title-group">
            <p className="eyebrow">Library</p>
            <h1>Recordings &amp; reports</h1>
            <p className="jobs-hero-sub">
              {total === 0
                ? state.view === "archived"
                  ? "No archived recordings."
                  : "No recordings yet. Start one to see it here."
                : `Showing ${visible} of ${total}`}
            </p>
          </div>
          <Link className="primary-button" to="/new">
            New recording
          </Link>
        </div>
      </section>

      {libraryCounts.total > 0 ? (
        <section className="jobs-controls" aria-label="Filter jobs">
          <div
            className="jobs-view-tabs"
            role="tablist"
            aria-label="Library view"
          >
            <button
              type="button"
              role="tab"
              aria-selected={view === "active"}
              className={`status-pill ${view === "active" ? "active" : ""}`}
              onClick={() => {
                if (view !== "active") setView("active");
              }}
            >
              Active ({libraryCounts.active})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "archived"}
              className={`status-pill ${view === "archived" ? "active" : ""}`}
              onClick={() => {
                if (view !== "archived") setView("archived");
              }}
            >
              Archived ({libraryCounts.archived})
            </button>
          </div>
          <label className="jobs-search">
            <span className="visually-hidden">Search jobs</span>
            <input
              type="search"
              placeholder="Search by filename or job id"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label className="jobs-project-filter">
            <span className="visually-hidden">Project</span>
            <select
              value={projectFilter}
              onChange={(e) => setProjectFilter(e.target.value)}
              aria-label="Project"
            >
              <option value={ALL_PROJECTS}>All projects</option>
              <option value={NO_PROJECT}>No project</option>
              {projects.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({view === "archived" ? p.archived : p.active})
                </option>
              ))}
            </select>
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
          <p className="eyebrow">
            {state.view === "archived" ? "Archive" : "Get started"}
          </p>
          <h2>
            {state.view === "archived"
              ? "No archived recordings"
              : "Capture your first recording"}
          </h2>
          <p>
            {state.view === "archived" ? (
              <>
                Nothing has been archived yet. Archive a job from its
                dashboard when you want to hide it from the Active
                view. Archived jobs stay on disk and are reachable
                directly by URL.
              </>
            ) : (
              <>
                Open <Link className="text-link" to="/new">the start page</Link>{" "}
                to record screen + audio in the browser, or pick a
                video file from <code>--sources-root</code>. Completed
                runs appear here.
              </>
            )}
          </p>
        </section>
      ) : visible === 0 ? (
        <section className="hero-card empty-card">
          <p className="eyebrow">No matches</p>
          <h2>No jobs match those filters</h2>
          <p>
            Try a different search term, project, or status. You can
            also{" "}
            <button
              type="button"
              className="text-link"
              onClick={() => {
                setQuery("");
                setStatusFilter("all");
                setProjectFilter(ALL_PROJECTS);
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
            <JobCard
              key={job.job_id}
              job={job}
              onSaveMetadata={(patch) =>
                handleSaveJobMetadata(job.job_id, patch)
              }
            />
          ))}
        </section>
      )}
    </main>
  );
}
