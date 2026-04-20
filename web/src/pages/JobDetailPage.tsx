import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getInsights,
  getJob,
  type InsightsLoadState,
  type JobSummary,
} from "../lib/api";
import { formatJobDateTime } from "../lib/format";
import ArtifactGrid from "../components/ArtifactGrid";
import InsightsPreview from "../components/InsightsPreview";
import RunActionsPanel from "../components/RunActionsPanel";
import StageTimeline from "../components/StageTimeline";

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
  }, [id, loadJob, loadInsights]);

  const handleRunCompleted = useCallback(
    (runType: "insights" | "rich-report") => {
      if (!id) return;
      // Regardless of which run finished, refresh the job summary so
      // artifact flags / stage timeline reflect any new artifacts.
      loadJob(id);
      if (runType === "insights") {
        loadInsights(id);
      }
    },
    [id, loadJob, loadInsights],
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
    const artifacts = job.artifacts || {};
    if (artifacts.report_md) out.push("report.md");
    if (artifacts.insights_json) out.push("insights.json");
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
  const title = job.original_filename || job.job_id;
  const status = job.status || "unknown";
  const transcriptUrl = `/job/${encodeURIComponent(job.job_id)}/transcript`;
  const legacyDetail =
    jobUrl(job, "legacy_detail") ||
    jobUrl(job, "detail_html") ||
    `/job/${encodeURIComponent(job.job_id)}/`;
  const reportMdUrl = jobUrl(job, "report_md");
  const reportHtmlUrl = jobUrl(job, "report_html");
  const reportDocxUrl = jobUrl(job, "report_docx");
  const insightsJsonUrl = jobUrl(job, "insights_json");

  return (
    <main className="detail-shell">
      <header className="detail-hero">
        <div className="detail-hero-top">
          <div className="detail-hero-title-group">
            <p className="eyebrow">Recap · Job</p>
            <h1 className="detail-hero-title" title={title}>
              {title}
            </h1>
            <p className="detail-hero-id" title={job.job_id}>
              <code>{job.job_id}</code>
            </p>
          </div>
          <span
            className={`status-badge status-${status}`}
            aria-label={`Status: ${status}`}
          >
            {status}
          </span>
        </div>

        <dl className="detail-hero-meta" aria-label="Job metadata">
          <div>
            <dt>Created</dt>
            <dd>{formatJobDateTime(job.created_at)}</dd>
          </div>
          <div>
            <dt>Updated</dt>
            <dd>{formatJobDateTime(job.updated_at)}</dd>
          </div>
        </dl>

        {metaChips.length > 0 ? (
          <ul className="detail-hero-chips" aria-label="Job facts">
            {metaChips.map((chip, i) => (
              <li key={i} className="detail-chip">
                {chip}
              </li>
            ))}
          </ul>
        ) : null}

        {job.error ? (
          <p className="detail-hero-error" role="status">
            {job.error}
          </p>
        ) : null}

        <div className="detail-hero-actions">
          <Link className="primary-button" to={transcriptUrl}>
            Open transcript workspace
          </Link>
          <a className="ghost-button" href={legacyDetail}>
            Legacy detail page
          </a>
          {reportHtmlUrl && job.artifacts?.report_html ? (
            <a
              className="ghost-button"
              href={reportHtmlUrl}
              target="_blank"
              rel="noreferrer"
            >
              Open HTML report
            </a>
          ) : null}
          {reportMdUrl && job.artifacts?.report_md ? (
            <a
              className="ghost-button"
              href={reportMdUrl}
              target="_blank"
              rel="noreferrer"
            >
              Open report.md
            </a>
          ) : null}
          {reportDocxUrl && job.artifacts?.report_docx ? (
            <a className="ghost-button" href={reportDocxUrl}>
              Download .docx
            </a>
          ) : null}
        </div>
      </header>

      <section className="detail-grid">
        <div className="detail-main">
          <InsightsPreview
            state={insightsState}
            insightsJsonUrl={insightsJsonUrl ?? undefined}
          />
          <RunActionsPanel
            jobId={job.job_id}
            insightsPresent={!!job.artifacts?.insights_json}
            onRunCompleted={handleRunCompleted}
          />
          <ArtifactGrid job={job} />
        </div>
        <aside className="detail-rail">
          <StageTimeline stages={job.stages || {}} />
          <section className="next-actions-card" aria-label="Next actions">
            <p className="eyebrow">Next</p>
            <h2>What you can do now</h2>
            <ul className="next-actions-list">
              <li>
                <Link className="text-link" to={transcriptUrl}>
                  Open the transcript workspace
                </Link>
                <p>
                  Search, filter speakers, and rename voices inline.
                </p>
              </li>
              <li>
                <a className="text-link" href={legacyDetail}>
                  Open the legacy HTML detail page
                </a>
                <p>
                  The stdlib dashboard remains live as a fallback —
                  exporter reruns and the legacy rich-report form are
                  still available there.
                </p>
              </li>
            </ul>
          </section>
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
