import { formatJobDateTime } from "../lib/format";
import type { JobStage } from "../lib/api";

type Props = {
  stages: Record<string, JobStage>;
};

// Core Phase 1 stages appear in a fixed order at the top; any
// additional stages (scenes, insights, export_html, etc.) are
// rendered afterwards in stable alphabetical order.
const CORE_ORDER = [
  "ingest",
  "normalize",
  "transcribe",
  "assemble",
] as const;

const PRETTY: Record<string, string> = {
  ingest: "Ingest",
  normalize: "Normalize",
  transcribe: "Transcribe",
  assemble: "Assemble",
  scenes: "Scenes",
  dedupe: "Dedupe",
  window: "Window",
  similarity: "Similarity",
  chapters: "Chapters",
  rank: "Rank",
  shortlist: "Shortlist",
  verify: "Verify",
  insights: "Insights",
  export_html: "Export HTML",
  export_docx: "Export DOCX",
};

function prettyName(name: string): string {
  return (
    PRETTY[name] ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function statusKey(stage: JobStage): string {
  const s = typeof stage.status === "string" ? stage.status : "pending";
  return s;
}

type ExtraPair = { label: string; value: string };

function extraPairs(stage: JobStage): ExtraPair[] {
  const skip = new Set([
    "status",
    "started_at",
    "finished_at",
    "error",
  ]);
  const pairs: ExtraPair[] = [];
  for (const key of Object.keys(stage).sort()) {
    if (skip.has(key)) continue;
    const raw = (stage as Record<string, unknown>)[key];
    if (raw === null || raw === undefined) continue;
    let value: string;
    if (typeof raw === "object") {
      try {
        value = JSON.stringify(raw);
      } catch {
        value = String(raw);
      }
    } else if (typeof raw === "boolean") {
      value = raw ? "yes" : "no";
    } else {
      value = String(raw);
    }
    if (value.length > 80) {
      value = value.slice(0, 77) + "…";
    }
    pairs.push({ label: key, value });
  }
  return pairs;
}

export default function StageTimeline({ stages }: Props) {
  const present = new Set(Object.keys(stages || {}));
  const core = CORE_ORDER.filter((s) => present.has(s));
  const extras = Array.from(present)
    .filter((s) => !(CORE_ORDER as readonly string[]).includes(s))
    .sort();
  const ordered = [...core, ...extras];

  if (ordered.length === 0) {
    return (
      <section className="timeline-card" aria-label="Pipeline stages">
        <p className="eyebrow">Pipeline</p>
        <p className="timeline-empty">No stages recorded yet.</p>
      </section>
    );
  }

  const completed = ordered.filter(
    (name) => statusKey(stages[name] || {}) === "completed",
  ).length;
  const failed = ordered.filter(
    (name) => statusKey(stages[name] || {}) === "failed",
  ).length;

  return (
    <section className="timeline-card" aria-label="Pipeline stages">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Pipeline</p>
          <h2>Stage timeline</h2>
        </div>
        <span className="timeline-count" aria-label="Stage progress">
          {completed} / {ordered.length} done
          {failed > 0 ? ` · ${failed} failed` : ""}
        </span>
      </div>
      <ol className="timeline-list">
        {ordered.map((name) => {
          const stage = stages[name] || {};
          const status = statusKey(stage);
          const finished = stage.finished_at
            ? formatJobDateTime(stage.finished_at)
            : null;
          const started = stage.started_at
            ? formatJobDateTime(stage.started_at)
            : null;
          const extras = extraPairs(stage);
          return (
            <li key={name} className={`timeline-item status-${status}`}>
              <span
                className="timeline-marker"
                aria-hidden
                data-status={status}
              />
              <div className="timeline-body">
                <header className="timeline-head">
                  <h3 className="timeline-name">{prettyName(name)}</h3>
                  <span
                    className={`status-badge status-${status}`}
                    aria-label={`Status: ${status}`}
                  >
                    {status}
                  </span>
                </header>
                {(finished || started) && (
                  <p className="timeline-times">
                    {finished ? (
                      <span>Finished {finished}</span>
                    ) : started ? (
                      <span>Started {started}</span>
                    ) : null}
                  </p>
                )}
                {status === "failed" && stage.error ? (
                  <p className="timeline-error" role="status">
                    {stage.error}
                  </p>
                ) : null}
                {extras.length > 0 ? (
                  <details className="timeline-extras-disclosure">
                    <summary>
                      <span className="timeline-extras-summary-label">
                        Details
                      </span>
                      <span className="timeline-extras-count">
                        {extras.length}
                      </span>
                    </summary>
                    <dl className="timeline-extras">
                      {extras.map(({ label, value }) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd>{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
