import { Link } from "react-router-dom";
import type { JobSummary } from "../lib/api";
import { formatJobDateTime } from "../lib/format";

type Props = {
  job: JobSummary;
};

type ArtifactKey = keyof JobSummary["artifacts"];

const ARTIFACT_ORDER: { key: ArtifactKey; label: string }[] = [
  { key: "transcript_json", label: "Transcript" },
  { key: "analysis_mp4", label: "Video" },
  { key: "report_md", label: "Report" },
  { key: "report_html", label: "HTML" },
  { key: "report_docx", label: "DOCX" },
  { key: "speaker_names_json", label: "Speakers" },
  { key: "insights_json", label: "Insights" },
];

function statusLabel(status: string | undefined | null): string {
  if (!status) return "unknown";
  return status;
}

export default function JobCard({ job }: Props) {
  const title = job.original_filename || job.job_id;
  const status = statusLabel(job.status);
  const hasReportHtml = Boolean(job.artifacts?.report_html);
  const urls = (job.urls ?? {}) as Record<string, string>;
  const detailHtml =
    urls.detail_html ?? `/job/${encodeURIComponent(job.job_id)}/`;
  const reportHtmlUrl =
    urls.report_html ?? `/job/${encodeURIComponent(job.job_id)}/report.html`;

  return (
    <article
      className={`job-card status-${status}`}
      aria-labelledby={`job-card-title-${job.job_id}`}
    >
      <header className="job-card-head">
        <div className="job-card-title-group">
          <h2
            className="job-card-title"
            id={`job-card-title-${job.job_id}`}
            title={title}
          >
            {title}
          </h2>
          <p className="job-card-id" title={job.job_id}>
            {job.job_id}
          </p>
        </div>
        <span
          className={`status-badge status-${status}`}
          aria-label={`Status: ${status}`}
        >
          {status}
        </span>
      </header>

      <dl className="job-card-meta">
        <div>
          <dt>Created</dt>
          <dd>{formatJobDateTime(job.created_at)}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatJobDateTime(job.updated_at)}</dd>
        </div>
      </dl>

      <ul className="job-card-artifacts" aria-label="Artifacts">
        {ARTIFACT_ORDER.map(({ key, label }) => {
          const present = Boolean(job.artifacts?.[key]);
          return (
            <li
              key={key}
              className={`artifact-chip ${present ? "present" : "missing"}`}
              title={`${label}: ${present ? "ready" : "missing"}`}
            >
              <span className="artifact-chip-dot" aria-hidden />
              {label}
            </li>
          );
        })}
      </ul>

      {job.error ? (
        <p className="job-card-error" role="status">
          {job.error}
        </p>
      ) : null}

      <footer className="job-card-actions">
        <Link
          className="primary-button"
          to={`/job/${encodeURIComponent(job.job_id)}/transcript`}
        >
          Open transcript workspace
        </Link>
        <a className="ghost-button" href={detailHtml}>
          Legacy detail
        </a>
        {hasReportHtml ? (
          <a
            className="ghost-button"
            href={reportHtmlUrl}
            target="_blank"
            rel="noreferrer"
          >
            HTML report
          </a>
        ) : null}
      </footer>
    </article>
  );
}
