import { Link } from "react-router-dom";
import type { ChapterListPayload } from "../lib/api";
import { formatTimestamp } from "../lib/format";

export type ChaptersCardProps = {
  jobId: string;
  state:
    | { status: "loading" }
    | { status: "loaded"; payload: ChapterListPayload }
    | { status: "error"; message: string };
};

const PREVIEW = 5;

export default function ChaptersCard({ jobId, state }: ChaptersCardProps) {
  if (state.status === "loading") {
    return (
      <section className="chapters-dashboard-card" aria-busy="true">
        <p className="eyebrow">Chapters</p>
        <h2>Loading chapter list…</h2>
        <div className="skeleton-line" />
        <div className="skeleton-line short" />
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section
        className="chapters-dashboard-card chapters-dashboard-error"
        role="status"
      >
        <p className="eyebrow">Chapters</p>
        <h2>Could not load chapters</h2>
        <p>{state.message}</p>
      </section>
    );
  }

  const { chapters, sources } = state.payload;
  const transcriptHref = `/app/job/${encodeURIComponent(jobId)}/transcript`;

  if (chapters.length === 0) {
    return (
      <section
        className="chapters-dashboard-card chapters-dashboard-empty"
        aria-label="Chapters"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">Chapters</p>
            <h2>No chapters yet</h2>
          </div>
        </div>
        <p>
          Chapters appear once <code>chapter_candidates.json</code> or
          <code> insights.json</code> exists. Run{" "}
          <strong>Generate insights</strong> or{" "}
          <strong>Generate rich report</strong> from the Actions panel.
        </p>
      </section>
    );
  }

  const shown = chapters.slice(0, PREVIEW);
  const more = chapters.length - shown.length;
  const customCount = chapters.filter(
    (ch) => typeof ch.custom_title === "string",
  ).length;
  const provenance: string[] = [];
  if (sources.chapter_candidates) provenance.push("chapter_candidates.json");
  if (sources.insights) provenance.push("insights.json");
  if (sources.chapter_titles_overlay) provenance.push("chapter_titles.json");

  return (
    <section className="chapters-dashboard-card" aria-label="Chapters">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Chapters</p>
          <h2>
            {chapters.length} chapters
            {customCount > 0 ? (
              <span className="chapters-dashboard-count">
                · {customCount} custom title{customCount === 1 ? "" : "s"}
              </span>
            ) : null}
          </h2>
        </div>
        {provenance.length > 0 ? (
          <span className="chapters-provenance">
            from {provenance.join(" + ")}
          </span>
        ) : null}
      </div>
      <ol className="chapters-dashboard-list">
        {shown.map((ch) => (
          <li key={ch.index} className="chapters-dashboard-item">
            <span className="chapters-dashboard-ts">
              {typeof ch.start_seconds === "number"
                ? formatTimestamp(ch.start_seconds)
                : "—"}
            </span>
            <span className="chapters-dashboard-title">
              {ch.display_title}
              {typeof ch.custom_title === "string" ? (
                <span className="chapter-title-badge" title="Custom title">
                  custom
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
      {more > 0 ? (
        <p className="chapters-dashboard-more">
          +{more} more · open the transcript workspace to view and edit.
        </p>
      ) : null}
      <p className="chapters-dashboard-actions">
        <Link className="text-link" to={transcriptHref}>
          Open chapter sidebar in the transcript workspace →
        </Link>
      </p>
    </section>
  );
}
