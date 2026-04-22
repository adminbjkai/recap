import { useState } from "react";
import { Link } from "react-router-dom";
import type { JobMetadataPatch, JobSummary } from "../lib/api";
import { formatJobDateTime } from "../lib/format";
import { runningSummary, summarizeJobProgress } from "../lib/progress";

type Props = {
  job: JobSummary;
  onSaveMetadata?: (patch: JobMetadataPatch) => Promise<void>;
};

function statusLabel(status: string | undefined | null): string {
  if (!status) return "unknown";
  return status;
}

function deriveDisplayTitle(job: JobSummary): string {
  const explicit = job.display_title;
  if (typeof explicit === "string" && explicit.trim()) {
    return explicit.trim();
  }
  return job.original_filename || job.job_id;
}

type ReadinessSlot = {
  key: "T" | "R" | "I";
  label: string;
  ready: boolean;
};

function readinessSlots(job: JobSummary): ReadinessSlot[] {
  const a = job.artifacts || {};
  const haveReport =
    Boolean(a.report_md) || Boolean(a.report_html) || Boolean(a.report_docx);
  return [
    { key: "T", label: "Transcript", ready: Boolean(a.transcript_json) },
    { key: "R", label: "Report", ready: haveReport },
    { key: "I", label: "Insights", ready: Boolean(a.insights_json) },
  ];
}

function readinessSummary(job: JobSummary): {
  ready: boolean;
  text: string;
} {
  const a = job.artifacts || {};
  const haveReport =
    Boolean(a.report_md) || Boolean(a.report_html) || Boolean(a.report_docx);
  const haveTranscript = Boolean(a.transcript_json);
  if (!haveTranscript) {
    return { ready: false, text: "Transcript pending" };
  }
  if (!haveReport) {
    return { ready: false, text: "Transcript ready" };
  }
  return { ready: true, text: "Ready" };
}

export default function JobCard({ job, onSaveMetadata }: Props) {
  const displayTitle = deriveDisplayTitle(job);
  const status = statusLabel(job.status);
  const readiness = readinessSummary(job);
  const slots = readinessSlots(job);
  const archived = !!job.archived;
  const project = job.project || null;
  const isCustomTitle =
    typeof job.custom_title === "string" && job.custom_title.trim().length > 0;
  const progressSnap = summarizeJobProgress(job);
  const runningLine =
    progressSnap.overallStatus === "running"
      ? runningSummary(progressSnap)
      : null;

  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(
    job.custom_title ?? job.original_filename ?? "",
  );
  const [draftProject, setDraftProject] = useState(job.project ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openEditor = () => {
    setDraftTitle(job.custom_title ?? job.original_filename ?? "");
    setDraftProject(job.project ?? "");
    setError(null);
    setEditing(true);
  };

  const handleSave = async () => {
    if (!onSaveMetadata) return;
    setSaving(true);
    setError(null);
    try {
      await onSaveMetadata({
        title: draftTitle.trim(),
        project: draftProject.trim(),
      });
      setEditing(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not save changes.",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleArchiveToggle = async () => {
    if (!onSaveMetadata) return;
    setSaving(true);
    setError(null);
    try {
      await onSaveMetadata({ archived: !archived });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not update archive.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <article
      className={`job-card status-${status} ${
        readiness.ready ? "is-ready" : "is-pending"
      }${archived ? " is-archived" : ""}`}
      aria-labelledby={`job-card-title-${job.job_id}`}
    >
      <header className="job-card-head">
        <div className="job-card-title-group">
          <span
            className={`status-badge status-${status}`}
            aria-label={`Status: ${status}`}
          >
            {status}
          </span>
          <h2
            className="job-card-title"
            id={`job-card-title-${job.job_id}`}
            title={displayTitle}
          >
            {displayTitle}
            {isCustomTitle ? (
              <span
                className="job-card-title-badge"
                title="Custom title saved in the local library"
              >
                renamed
              </span>
            ) : null}
            {archived ? (
              <span
                className="job-card-title-badge job-card-title-badge--archived"
                title="Archived in the local library"
              >
                archived
              </span>
            ) : null}
          </h2>
          <p className="job-card-subline">
            {project ? (
              <>
                <span
                  className="job-card-project"
                  title={`Project: ${project}`}
                >
                  {project}
                </span>
                <span className="job-card-meta-sep" aria-hidden>
                  ·
                </span>
              </>
            ) : null}
            <span
              className="readiness-dots"
              aria-label={`Readiness: ${readiness.text}`}
              title={readiness.text}
            >
              {slots.map((slot) => (
                <span
                  key={slot.key}
                  className={`readiness-dot${
                    slot.ready ? " is-ready" : ""
                  }`}
                  aria-hidden
                >
                  {slot.key}
                </span>
              ))}
              <span className="visually-hidden">
                {slots
                  .map(
                    (s) => `${s.label} ${s.ready ? "ready" : "pending"}`,
                  )
                  .join(", ")}
              </span>
            </span>
            <span className="job-card-meta-sep" aria-hidden>
              ·
            </span>
            <span className="job-card-time" title={`Updated ${job.updated_at}`}>
              {formatJobDateTime(job.updated_at)}
            </span>
          </p>
        </div>
      </header>

      {runningLine ? (
        <p className="job-card-running" role="status" aria-live="polite">
          <span className="job-card-running-dot" aria-hidden />
          {runningLine}
        </p>
      ) : null}

      {job.error ? (
        <p className="job-card-error" role="status">
          {job.error}
        </p>
      ) : null}

      {editing ? (
        <div className="job-card-editor" role="group" aria-label="Edit metadata">
          <label className="job-card-editor-field">
            <span className="job-card-editor-label">Title</span>
            <input
              type="text"
              value={draftTitle}
              maxLength={120}
              placeholder={job.original_filename ?? job.job_id}
              onChange={(e) => setDraftTitle(e.target.value)}
              aria-label="Job title"
            />
          </label>
          <label className="job-card-editor-field">
            <span className="job-card-editor-label">Project</span>
            <input
              type="text"
              value={draftProject}
              maxLength={80}
              placeholder="e.g. Client demos"
              onChange={(e) => setDraftProject(e.target.value)}
              aria-label="Project"
            />
          </label>
          {error ? (
            <p className="form-error" role="status">
              {error}
            </p>
          ) : null}
          <div className="job-card-editor-actions">
            <button
              type="button"
              className="primary-button primary-button--sm"
              onClick={handleSave}
              disabled={saving || !onSaveMetadata}
              aria-busy={saving}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="ghost-button ghost-button--sm"
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
              disabled={saving}
            >
              Cancel
            </button>
            <span className="job-card-editor-hint">
              Local library only. Clearing a field removes it.
            </span>
          </div>
        </div>
      ) : (
        <footer className="job-card-actions">
          <Link
            className="primary-button"
            to={`/job/${encodeURIComponent(job.job_id)}`}
          >
            Open job dashboard
          </Link>
          <Link
            className="text-link job-card-link"
            to={`/job/${encodeURIComponent(job.job_id)}/transcript`}
          >
            Transcript
          </Link>
          {onSaveMetadata ? (
            <>
              <button
                type="button"
                className="text-link job-card-link"
                onClick={openEditor}
              >
                Edit
              </button>
              <button
                type="button"
                className="text-link job-card-link"
                onClick={handleArchiveToggle}
                disabled={saving}
                aria-busy={saving}
              >
                {archived ? "Unarchive" : "Archive"}
              </button>
            </>
          ) : null}
          {error ? (
            <span className="form-error job-card-link" role="status">
              {error}
            </span>
          ) : null}
        </footer>
      )}
    </article>
  );
}
