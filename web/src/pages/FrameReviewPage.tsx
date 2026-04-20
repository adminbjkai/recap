import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getFrames,
  getJob,
  saveFrameReview,
  type FrameChapterContext,
  type FrameItem,
  type FrameListPayload,
  type FrameReviewEntry,
  type JobSummary,
} from "../lib/api";
import FrameCard from "../components/FrameCard";

type LoadState =
  | { status: "loading" }
  | {
      status: "loaded";
      job: JobSummary;
      frames: FrameListPayload;
    }
  | { status: "error"; message: string };

type Filter = "all" | "selected" | "shortlist" | "with-review";

function matchesFilter(frame: FrameItem, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "selected") {
    return (
      frame.decision === "selected_hero" ||
      frame.decision === "selected_supporting"
    );
  }
  if (filter === "shortlist") {
    return (
      frame.shortlist_decision === "hero" ||
      frame.shortlist_decision === "supporting"
    );
  }
  if (filter === "with-review") {
    return (
      frame.review?.decision === "keep" ||
      frame.review?.decision === "reject"
    );
  }
  return true;
}

export default function FrameReviewPage() {
  const { id } = useParams();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [pending, setPending] = useState<
    Record<string, FrameReviewEntry>
  >({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedPulse, setSavedPulse] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback((jobId: string) => {
    setState({ status: "loading" });
    Promise.all([getJob(jobId), getFrames(jobId)])
      .then(([job, frames]) => {
        setState({ status: "loaded", job, frames });
      })
      .catch((err) => {
        setState({
          status: "error",
          message:
            err instanceof Error
              ? err.message
              : "Could not load frames.",
        });
      });
  }, []);

  useEffect(() => {
    if (!id) {
      setState({
        status: "error",
        message: "Missing job id.",
      });
      return;
    }
    load(id);
  }, [id, load]);

  const chapterByIndex = useMemo(() => {
    const map = new Map<number, FrameChapterContext>();
    if (state.status === "loaded") {
      for (const ch of state.frames.chapters) {
        if (typeof ch.index === "number") {
          map.set(ch.index, ch);
        }
      }
    }
    return map;
  }, [state]);

  const visibleFrames = useMemo(() => {
    if (state.status !== "loaded") return [] as FrameItem[];
    return state.frames.frames.filter((f) => matchesFilter(f, filter));
  }, [state, filter]);

  const dirtyCount = Object.keys(pending).length;

  const handleChange = useCallback(
    (frameFile: string, entry: FrameReviewEntry | null) => {
      setPending((prev) => {
        const next = { ...prev };
        if (entry === null) {
          delete next[frameFile];
        } else {
          next[frameFile] = entry;
        }
        return next;
      });
    },
    [],
  );

  const handleDiscard = useCallback(() => {
    setPending({});
    setSaveError(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (!id || state.status !== "loaded" || dirtyCount === 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveFrameReview(id, pending);
      setPending({});
      setSavedPulse(true);
      window.setTimeout(() => setSavedPulse(false), 2200);
      // Refresh merged view so the stored overlay re-appears.
      const fresh = await getFrames(id);
      setState((curr) =>
        curr.status === "loaded" ? { ...curr, frames: fresh } : curr,
      );
    } catch (err) {
      setSaveError(
        err instanceof Error
          ? err.message
          : "Could not save frame review.",
      );
    } finally {
      setSaving(false);
    }
  }, [id, state, pending, dirtyCount]);

  if (state.status === "loading") {
    return (
      <main className="frames-shell">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Recap · Frame review</p>
          <h1>Loading frames…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="frames-shell">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap · Frame review</p>
          <h1>Could not load frames</h1>
          <p>{state.message}</p>
          <div className="job-card-actions">
            <Link className="primary-button" to={`/job/${id ?? ""}`}>
              Back to dashboard
            </Link>
          </div>
        </section>
      </main>
    );
  }

  const { job, frames } = state;
  const jobTitle = job.original_filename || job.job_id;
  const dashboardHref = `/job/${encodeURIComponent(job.job_id)}`;
  const legacyDashboard = `/job/${encodeURIComponent(job.job_id)}/`;

  const hasAnyFrames = frames.frames.length > 0;
  const hasSelected = frames.sources.selected_frames;
  const hasCandidates = frames.sources.candidate_frames_dir;

  if (!hasAnyFrames) {
    return (
      <main className="frames-shell">
        <header className="frames-header">
          <div className="frames-header-group">
            <p className="eyebrow">Recap · Frame review</p>
            <h1 className="frames-title">{jobTitle}</h1>
            <p className="frames-sub">
              <code>{job.job_id}</code>
            </p>
          </div>
          <div className="frames-actions">
            <Link className="ghost-button" to={dashboardHref}>
              ← Dashboard
            </Link>
          </div>
        </header>

        <section className="hero-card empty-card" aria-label="No frames yet">
          <p className="eyebrow">No visual artifacts yet</p>
          <h2>Nothing to review</h2>
          <p>
            This job doesn't have any candidate frames, scene metadata,
            or a shortlist. Generate the rich report to produce
            screenshot candidates, or run the individual stages via
            the CLI:
          </p>
          <pre className="frames-empty-cmd">
{`.venv/bin/python -m recap scenes --job jobs/<id>
.venv/bin/python -m recap dedupe --job jobs/<id>
.venv/bin/python -m recap shortlist --job jobs/<id>
.venv/bin/python -m recap verify --job jobs/<id> --provider mock`}
          </pre>
          <p className="frames-hint">
            Or use <strong>Generate rich report</strong> from the job
            dashboard — it runs the full chain in one click.
          </p>
          <div className="job-card-actions">
            <Link className="primary-button" to={dashboardHref}>
              Open dashboard
            </Link>
            <a className="ghost-button" href={legacyDashboard}>
              Legacy HTML detail page
            </a>
          </div>
        </section>
      </main>
    );
  }

  const totals = {
    total: frames.frames.length,
    selected: frames.frames.filter(
      (f) =>
        f.decision === "selected_hero" ||
        f.decision === "selected_supporting",
    ).length,
    shortlist: frames.frames.filter(
      (f) =>
        f.shortlist_decision === "hero" ||
        f.shortlist_decision === "supporting",
    ).length,
    review: frames.frames.filter(
      (f) =>
        f.review?.decision === "keep" ||
        f.review?.decision === "reject",
    ).length,
  };

  return (
    <main className="frames-shell">
      <header className="frames-header">
        <div className="frames-header-group">
          <p className="eyebrow">Recap · Frame review</p>
          <h1 className="frames-title">{jobTitle}</h1>
          <p className="frames-sub">
            <code>{job.job_id}</code>
          </p>
          <ul className="frames-stats" aria-label="Frame counts">
            <li>
              <span className="frames-stat-label">Candidates</span>
              <span className="frames-stat-value">{totals.total}</span>
            </li>
            <li>
              <span className="frames-stat-label">Shortlist</span>
              <span className="frames-stat-value">
                {totals.shortlist}
              </span>
            </li>
            <li>
              <span className="frames-stat-label">Selected</span>
              <span className="frames-stat-value">{totals.selected}</span>
            </li>
            <li>
              <span className="frames-stat-label">Reviewed</span>
              <span className="frames-stat-value">{totals.review}</span>
            </li>
          </ul>
        </div>
        <div className="frames-actions">
          <Link className="ghost-button" to={dashboardHref}>
            ← Dashboard
          </Link>
          <Link
            className="ghost-button"
            to={`/job/${encodeURIComponent(job.job_id)}/transcript`}
          >
            Transcript workspace
          </Link>
          <a className="ghost-button" href={legacyDashboard}>
            Legacy detail
          </a>
        </div>
      </header>

      <section
        className="frames-toolbar"
        aria-label="Frame review controls"
      >
        <div
          className="frames-filter"
          role="tablist"
          aria-label="Frame filter"
        >
          {(
            [
              { value: "all", label: `All (${totals.total})` },
              {
                value: "selected",
                label: `Selected (${totals.selected})`,
              },
              {
                value: "shortlist",
                label: `Shortlist (${totals.shortlist})`,
              },
              {
                value: "with-review",
                label: `Reviewed (${totals.review})`,
              },
            ] as Array<{ value: Filter; label: string }>
          ).map((opt) => (
            <button
              key={opt.value}
              type="button"
              role="tab"
              aria-selected={filter === opt.value}
              className={`frames-filter-tab${
                filter === opt.value ? " active" : ""
              }`}
              onClick={() => setFilter(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="frames-save-bar">
          {dirtyCount > 0 ? (
            <span className="frames-dirty-count" role="status">
              {dirtyCount} unsaved change{dirtyCount === 1 ? "" : "s"}
            </span>
          ) : null}
          {savedPulse ? (
            <span className="save-toast" role="status">
              Review saved.
            </span>
          ) : null}
          {saveError ? (
            <span className="form-error" role="status">
              {saveError}
            </span>
          ) : null}
          <button
            type="button"
            className="ghost-button"
            onClick={handleDiscard}
            disabled={dirtyCount === 0 || saving}
          >
            Discard changes
          </button>
          <button
            type="button"
            className="primary-button"
            onClick={handleSave}
            disabled={dirtyCount === 0 || saving}
            aria-busy={saving}
          >
            {saving
              ? "Saving…"
              : `Save review${
                  dirtyCount > 0 ? ` (${dirtyCount})` : ""
                }`}
          </button>
        </div>
      </section>

      <p className="frames-provenance">
        Sources:{" "}
        {[
          hasSelected ? "selected_frames.json" : null,
          frames.sources.frame_scores ? "frame_scores.json" : null,
          frames.sources.scenes ? "scenes.json" : null,
          hasCandidates ? "candidate_frames/" : null,
          frames.sources.frame_review_overlay
            ? "frame_review.json"
            : null,
        ]
          .filter(Boolean)
          .join(" · ") || "candidate_frames/ only"}
      </p>

      {visibleFrames.length === 0 ? (
        <p className="frames-empty-filter">
          No frames match the <strong>{filter}</strong> filter.
        </p>
      ) : (
        <section className="frames-grid">
          {visibleFrames.map((frame) => (
            <FrameCard
              key={frame.frame_file}
              frame={frame}
              chapter={
                typeof frame.chapter_index === "number"
                  ? chapterByIndex.get(frame.chapter_index) ?? null
                  : null
              }
              pending={pending[frame.frame_file] ?? null}
              onChange={(entry) => handleChange(frame.frame_file, entry)}
              disabled={saving}
            />
          ))}
        </section>
      )}

      <footer className="workspace-footer">
        <Link className="text-link" to="/">
          ← All jobs
        </Link>
      </footer>
    </main>
  );
}
