import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getChapters,
  getInsights,
  getJob,
  saveJobMetadata,
  type ChapterListPayload,
  type InsightsLoadState,
  type JobMetadataPatch,
  type JobSummary,
} from "../lib/api";
import { formatJobDateTime } from "../lib/format";
import ArtifactGrid from "../components/ArtifactGrid";
import ChaptersCard from "../components/ChaptersCard";
import InsightsPreview from "../components/InsightsPreview";
import RunActionsPanel from "../components/RunActionsPanel";
import StageTimeline from "../components/StageTimeline";

type ChaptersCardState =
  | { status: "loading" }
  | { status: "loaded"; payload: ChapterListPayload }
  | { status: "error"; message: string };

type LoadState =
  | { status: "loading" }
  | { status: "loaded"; job: JobSummary }
  | { status: "error"; message: string };

function jobUrl(job: JobSummary, key: string): string | null {
  const urls = job.urls as unknown as Record<string, string | undefined>;
  const value = urls[key];
  return typeof value === "string" && value ? value : null;
}

function detectEngine(job: JobSummary): string | null {
  const stage = job.stages?.transcribe as Record<string, unknown> | undefined;
  const raw = stage?.engine;
  if (typeof raw === "string" && raw.trim()) return raw;
  return null;
}

function detectModel(job: JobSummary): string | null {
  const stage = job.stages?.transcribe as Record<string, unknown> | undefined;
  const raw = stage?.model;
  if (typeof raw === "string" && raw.trim()) return raw;
  return null;
}

function detectSegmentCount(job: JobSummary): number | null {
  const stage = job.stages?.transcribe as Record<string, unknown> | undefined;
  const raw = stage?.segments ?? stage?.segment_count;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  return null;
}

export default function JobDetailPage() {
  const { id } = useParams();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [insightsState, setInsightsState] = useState<InsightsLoadState>({
    status: "loading",
  });
  const [chaptersState, setChaptersState] = useState<ChaptersCardState>({
    status: "loading",
  });
  const [editingMetadata, setEditingMetadata] = useState(false);
  const [metadataDraft, setMetadataDraft] = useState<{
    title: string;
    project: string;
  }>({ title: "", project: "" });
  const [metadataSaving, setMetadataSaving] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);

  const loadJob = useCallback((jobId: string) => {
    return getJob(jobId)
      .then((job) => {
        setState({ status: "loaded", job });
      })
      .catch((err) => {
        setState({
          status: "error",
          message:
            err instanceof Error ? err.message : "Could not load job.",
        });
      });
  }, []);

  const loadChapters = useCallback((jobId: string) => {
    setChaptersState({ status: "loading" });
    return getChapters(jobId)
      .then((payload) => {
        setChaptersState({ status: "loaded", payload });
      })
      .catch((err) => {
        setChaptersState({
          status: "error",
          message:
            err instanceof Error
              ? err.message
              : "Could not load chapters.",
        });
      });
  }, []);

  const loadInsights = useCallback((jobId: string) => {
    setInsightsState({ status: "loading" });
    return getInsights(jobId)
      .then((result) => {
        if (result.kind === "loaded") {
          setInsightsState({
            status: "loaded",
            insights: result.insights,
          });
        } else if (result.kind === "absent") {
          setInsightsState({ status: "absent" });
        } else {
          setInsightsState({
            status: "error",
            message: result.message,
            reason: result.reason,
          });
        }
      })
      .catch((err) => {
        setInsightsState({
          status: "error",
          message:
            err instanceof Error
              ? err.message
              : "Could not load insights.",
        });
      });
  }, []);

  useEffect(() => {
    if (!id) {
      setState({ status: "error", message: "Missing job id." });
      return;
    }
    setState({ status: "loading" });
    loadJob(id);
    loadInsights(id);
    loadChapters(id);
  }, [id, loadJob, loadInsights, loadChapters]);

  const handleRunCompleted = useCallback(
    (runType: "insights" | "rich-report") => {
      if (!id) return;
      // Regardless of which run finished, refresh the job summary so
      // artifact flags / stage timeline reflect any new artifacts.
      loadJob(id);
      if (runType === "insights") {
        loadInsights(id);
      }
      // Rich-report can produce both chapter_candidates.json and
      // (via the chain's assemble step) leave insights.json in
      // place, both of which feed the chapter list.
      loadChapters(id);
    },
    [id, loadJob, loadInsights, loadChapters],
  );

  const handleSaveMetadata = useCallback(
    async (patch: JobMetadataPatch) => {
      if (!id) return;
      setMetadataSaving(true);
      setMetadataError(null);
      try {
        const updated = await saveJobMetadata(id, patch);
        setState({ status: "loaded", job: updated });
        setEditingMetadata(false);
      } catch (err) {
        setMetadataError(
          err instanceof Error
            ? err.message
            : "Could not save metadata.",
        );
      } finally {
        setMetadataSaving(false);
      }
    },
    [id],
  );

  const metaChips = useMemo(() => {
    if (state.status !== "loaded") return [] as string[];
    const job = state.job;
    const out: string[] = [];
    const engine = detectEngine(job);
    if (engine) out.push(`Engine · ${engine}`);
    const model = detectModel(job);
    if (model) out.push(`Model · ${model}`);
    const segs = detectSegmentCount(job);
    if (segs != null) out.push(`${segs} segments`);
    const a = job.artifacts as Record<string, unknown> | undefined;
    if (a && a.transcript_notes_json) out.push("Transcript notes");
    return out;
  }, [state]);

  if (state.status === "loading") {
    return (
      <main className="detail-shell">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Recap · Job</p>
          <h1>Loading job…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
          <div className="skeleton-line" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="detail-shell">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap · Job</p>
          <h1>Unable to load job</h1>
          <p>{state.message}</p>
          <div className="job-card-actions">
            <Link className="primary-button" to="/">
              Back to jobs
            </Link>
            <a className="ghost-button" href="/">
              Legacy dashboard
            </a>
          </div>
        </section>
      </main>
    );
  }

  const { job } = state;
  const fallbackTitle = job.original_filename || job.job_id;
  const title =
    (typeof job.display_title === "string" && job.display_title.trim()) ||
    fallbackTitle;
  const isCustomTitle =
    typeof job.custom_title === "string" && job.custom_title.trim().length > 0;
  const project = job.project || null;
  const archived = !!job.archived;
  const status = job.status || "unknown";
  const transcriptUrl = `/job/${encodeURIComponent(job.job_id)}/transcript`;
  const framesUrl = `/job/${encodeURIComponent(job.job_id)}/frames`;
  const legacyDetail =
    jobUrl(job, "legacy_detail") ||
    jobUrl(job, "detail_html") ||
    `/job/${encodeURIComponent(job.job_id)}/`;
  const reportMdUrl = jobUrl(job, "report_md");
  const reportHtmlUrl = jobUrl(job, "report_html");
  const reportDocxUrl = jobUrl(job, "report_docx");
  const insightsJsonUrl = jobUrl(job, "insights_json");

  const reportLinks: Array<{ label: string; href: string; download?: boolean }> =
    [];
  if (reportHtmlUrl && job.artifacts?.report_html) {
    reportLinks.push({ label: "HTML", href: reportHtmlUrl });
  }
  if (reportMdUrl && job.artifacts?.report_md) {
    reportLinks.push({ label: "Markdown", href: reportMdUrl });
  }
  if (reportDocxUrl && job.artifacts?.report_docx) {
    reportLinks.push({ label: "DOCX", href: reportDocxUrl, download: true });
  }

  const haveScreenshots = !!job.artifacts?.selected_frames_json;

  return (
    <main className={`detail-shell${archived ? " is-archived" : ""}`}>
      <header className="detail-hero">
        <div className="detail-hero-top">
          <div className="detail-hero-title-group">
            <p className="eyebrow">Job</p>
            <h1 className="detail-hero-title" title={title}>
              {title}
              {isCustomTitle ? (
                <span
                  className="detail-hero-title-badge"
                  title="Custom title saved in the local library"
                >
                  renamed
                </span>
              ) : null}
              {archived ? (
                <span
                  className="detail-hero-title-badge detail-hero-title-badge--archived"
                  title="Archived in the local library"
                >
                  archived
                </span>
              ) : null}
            </h1>
            <p className="detail-hero-subline">
              <span
                className={`status-badge status-${status}`}
                aria-label={`Status: ${status}`}
              >
                {status}
              </span>
              {project ? (
                <>
                  <span className="detail-hero-meta-sep" aria-hidden>
                    ·
                  </span>
                  <span className="detail-chip" title={`Project: ${project}`}>
                    {project}
                  </span>
                </>
              ) : null}
              <span className="detail-hero-meta-sep" aria-hidden>
                ·
              </span>
              <span className="detail-hero-time">
                Updated {formatJobDateTime(job.updated_at)}
              </span>
              {metaChips.length > 0 ? (
                <>
                  <span className="detail-hero-meta-sep" aria-hidden>
                    ·
                  </span>
                  <span className="detail-hero-chiprow">
                    {metaChips.map((chip, i) => (
                      <span key={i} className="detail-chip">
                        {chip}
                      </span>
                    ))}
                  </span>
                </>
              ) : null}
            </p>
          </div>
        </div>

        {job.error ? (
          <p className="detail-hero-error" role="status">
            {job.error}
          </p>
        ) : null}

        <div className="detail-hero-actions" role="group" aria-label="Job actions">
          <Link className="primary-button" to={transcriptUrl}>
            Open transcript workspace
          </Link>
          <Link
            className={`ghost-button${haveScreenshots ? "" : " is-empty"}`}
            to={framesUrl}
          >
            {haveScreenshots ? "Review screenshots" : "Screenshots (empty)"}
          </Link>
        </div>

        {reportLinks.length > 0 ? (
          <p
            className="detail-hero-downloads"
            aria-label="Open exported report"
          >
            <span className="detail-hero-downloads-label">Downloads</span>
            {reportLinks.map((link, i) => (
              <span key={link.label} className="detail-hero-downloads-item">
                {i > 0 ? (
                  <span className="detail-hero-meta-sep" aria-hidden>
                    ·
                  </span>
                ) : null}
                <a
                  className="text-link"
                  href={link.href}
                  {...(link.download
                    ? {}
                    : { target: "_blank", rel: "noreferrer" })}
                >
                  {link.label}
                </a>
              </span>
            ))}
          </p>
        ) : null}

        <div className="detail-hero-meta-actions" role="group" aria-label="Organize">
          <button
            type="button"
            className="text-link detail-hero-organize"
            onClick={() => {
              setEditingMetadata((curr) => {
                if (!curr) {
                  setMetadataDraft({
                    title: job.custom_title ?? "",
                    project: job.project ?? "",
                  });
                  setMetadataError(null);
                }
                return !curr;
              });
            }}
            aria-expanded={editingMetadata}
          >
            {editingMetadata ? "Close organize" : "Rename / Project"}
          </button>
          <span className="detail-hero-meta-sep" aria-hidden>
            ·
          </span>
          <button
            type="button"
            className="text-link detail-hero-archive"
            onClick={() =>
              handleSaveMetadata({ archived: !archived })
            }
            disabled={metadataSaving}
          >
            {archived ? "Unarchive" : "Archive"}
          </button>
          <a
            className="text-link detail-hero-legacy"
            href={legacyDetail}
          >
            Legacy detail page
          </a>
        </div>

        {editingMetadata ? (
          <div
            className="detail-hero-editor"
            role="group"
            aria-label="Edit library metadata"
          >
            <label className="detail-hero-editor-field">
              <span className="detail-hero-editor-label">Title</span>
              <input
                type="text"
                value={metadataDraft.title}
                maxLength={120}
                placeholder={fallbackTitle}
                onChange={(e) =>
                  setMetadataDraft((d) => ({
                    ...d,
                    title: e.target.value,
                  }))
                }
                aria-label="Custom title"
              />
            </label>
            <label className="detail-hero-editor-field">
              <span className="detail-hero-editor-label">Project</span>
              <input
                type="text"
                value={metadataDraft.project}
                maxLength={80}
                placeholder="e.g. Client demos"
                onChange={(e) =>
                  setMetadataDraft((d) => ({
                    ...d,
                    project: e.target.value,
                  }))
                }
                aria-label="Project"
              />
            </label>
            {metadataError ? (
              <p className="form-error" role="status">
                {metadataError}
              </p>
            ) : null}
            <div className="detail-hero-editor-actions">
              <button
                type="button"
                className="primary-button primary-button--sm"
                onClick={() =>
                  handleSaveMetadata({
                    title: metadataDraft.title.trim(),
                    project: metadataDraft.project.trim(),
                  })
                }
                disabled={metadataSaving}
                aria-busy={metadataSaving}
              >
                {metadataSaving ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                className="ghost-button ghost-button--sm"
                onClick={() => {
                  setEditingMetadata(false);
                  setMetadataError(null);
                }}
                disabled={metadataSaving}
              >
                Cancel
              </button>
              <span className="detail-hero-editor-hint">
                Organization is local to this Recap library. Clearing
                a field removes it; the job directory on disk stays
                put.
              </span>
            </div>
          </div>
        ) : null}
      </header>

      <section className="detail-grid">
        <div className="detail-main">
          <RunActionsPanel
            jobId={job.job_id}
            insightsPresent={!!job.artifacts?.insights_json}
            onRunCompleted={handleRunCompleted}
          />
          <InsightsPreview
            state={insightsState}
            insightsJsonUrl={insightsJsonUrl ?? undefined}
          />
          <ChaptersCard jobId={job.job_id} state={chaptersState} />
          <details className="detail-disclosure">
            <summary>
              <span className="detail-disclosure-label">Artifacts on disk</span>
              <span className="detail-disclosure-hint">
                Raw files this job has produced.
              </span>
            </summary>
            <div className="detail-disclosure-body">
              <ArtifactGrid job={job} />
            </div>
          </details>
        </div>
        <aside className="detail-rail">
          <StageTimeline stages={job.stages || {}} />
        </aside>
      </section>

      <footer className="workspace-footer">
        <Link className="text-link" to="/">
          ← All jobs
        </Link>
      </footer>
    </main>
  );
}
