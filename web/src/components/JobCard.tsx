import { Link } from "react-router-dom";
import type { JobSummary } from "../lib/api";
import { formatJobDateTime } from "../lib/format";

type Props = {
  job: JobSummary;
};

function statusLabel(status: string | undefined | null): string {
  if (!status) return "unknown";
  return status;
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
    return { ready: false, text: "Transcript not ready yet" };
  }
  if (!haveReport) {
    return { ready: false, text: "Transcript ready · Report not generated" };
  }
  const extras: string[] = [];
  if (a.insights_json) extras.push("Insights");
  if (a.selected_frames_json) extras.push("Screenshots");
  if (a.speaker_names_json) extras.push("Renamed speakers");
  const tail = extras.length > 0 ? ` · ${extras.join(" · ")}` : "";
  return { ready: true, text: `Report ready${tail}` };
}

export default function JobCard({ job }: Props) {
  const title = job.original_filename || job.job_id;
  const status = statusLabel(job.status);
  const readiness = readinessSummary(job);

  return (
    <article
      className={`job-card status-${status} ${
        readiness.ready ? "is-ready" : "is-pending"
      }`}
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
            title={title}
          >
            {title}
          </h2>
          <p className="job-card-subline">
            <span className="job-card-readiness">{readiness.text}</span>
            <span className="job-card-meta-sep" aria-hidden>
              ·
            </span>
            <span className="job-card-time" title={`Updated ${job.updated_at}`}>
              Updated {formatJobDateTime(job.updated_at)}
            </span>
          </p>
        </div>
      </header>

      {job.error ? (
        <p className="job-card-error" role="status">
          {job.error}
        </p>
      ) : null}

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
      </footer>
    </article>
  );
}
