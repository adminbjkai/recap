import type { JobSummary } from "../lib/api";

type Props = {
  job: JobSummary;
};

type ArtifactDescriptor = {
  key: keyof JobSummary["artifacts"] | string;
  label: string;
  urlKey?: string;
  urlPath?: string;
  openLabel?: string;
  description: string;
};

const ARTIFACTS: ArtifactDescriptor[] = [
  {
    key: "analysis_mp4",
    label: "Normalized video",
    urlKey: "analysis_mp4",
    openLabel: "Open",
    description: "analysis.mp4 used by the transcript workspace.",
  },
  {
    key: "transcript_json",
    label: "Transcript",
    urlKey: "transcript",
    openLabel: "Open JSON",
    description: "transcript.json with segments and (when available) utterances.",
  },
  {
    key: "report_md",
    label: "Markdown report",
    urlKey: "report_md",
    openLabel: "Open report.md",
    description: "Primary narrative export.",
  },
  {
    key: "report_html",
    label: "HTML report",
    urlKey: "report_html",
    openLabel: "Open report.html",
    description: "Styled report for browsers.",
  },
  {
    key: "report_docx",
    label: "DOCX report",
    urlKey: "report_docx",
    openLabel: "Download .docx",
    description: "Shareable Word document.",
  },
  {
    key: "insights_json",
    label: "Structured insights",
    urlKey: "insights_json",
    openLabel: "Open insights.json",
    description: "Overview, bullets, action items, and chapter summaries.",
  },
  {
    key: "chapter_candidates_json",
    label: "Chapter candidates",
    urlPath: "/job/{id}/chapter_candidates.json",
    openLabel: "Open JSON",
    description: "Proposed chapters from transcript pauses + signals.",
  },
  {
    key: "selected_frames_json",
    label: "Selected frames",
    urlPath: "/job/{id}/selected_frames.json",
    openLabel: "Open JSON",
    description: "Finalized hero and supporting screenshots for chapters.",
  },
  {
    key: "speaker_names_json",
    label: "Speaker names",
    urlKey: "speaker_names",
    openLabel: "Open overlay",
    description: "User-editable speaker label overlay.",
  },
];

function resolveUrl(
  job: JobSummary,
  desc: ArtifactDescriptor,
): string | null {
  if (desc.urlKey) {
    const urls = job.urls as unknown as Record<string, string | undefined>;
    const url = urls[desc.urlKey];
    if (typeof url === "string" && url) return url;
  }
  if (desc.urlPath) {
    return desc.urlPath.replace("{id}", encodeURIComponent(job.job_id));
  }
  return null;
}

export default function ArtifactGrid({ job }: Props) {
  return (
    <section className="artifacts-card" aria-label="Artifacts">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Artifacts</p>
          <h2>On disk</h2>
        </div>
        <span className="artifacts-count">
          {ARTIFACTS.filter((a) => Boolean(job.artifacts?.[a.key])).length} of{" "}
          {ARTIFACTS.length} present
        </span>
      </div>
      <ul className="artifact-grid">
        {ARTIFACTS.map((desc) => {
          const present = Boolean(job.artifacts?.[desc.key]);
          const url = resolveUrl(job, desc);
          return (
            <li
              key={String(desc.key)}
              className={`artifact-tile ${present ? "present" : "missing"}`}
            >
              <div className="artifact-tile-head">
                <h3>{desc.label}</h3>
                <span
                  className={`dot-badge ${present ? "present" : "missing"}`}
                  aria-label={present ? "available" : "missing"}
                  title={present ? "available" : "missing"}
                />
              </div>
              <p className="artifact-tile-desc">{desc.description}</p>
              <div className="artifact-tile-actions">
                {present && url ? (
                  <a
                    className="ghost-button"
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {desc.openLabel || "Open"}
                  </a>
                ) : (
                  <span className="artifact-tile-status">
                    Not generated yet
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
