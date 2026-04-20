import type { InsightsLoadState } from "../lib/api";
import { formatJobDateTime, formatTimestamp } from "../lib/format";

type Props = {
  state: InsightsLoadState;
  insightsJsonUrl?: string;
};

export default function InsightsPreview({ state, insightsJsonUrl }: Props) {
  if (state.status === "loading") {
    return (
      <section className="insights-card" aria-busy="true">
        <p className="eyebrow">Insights</p>
        <h2>Loading…</h2>
        <div className="skeleton-line" />
        <div className="skeleton-line short" />
      </section>
    );
  }

  if (state.status === "absent") {
    return (
      <section className="insights-card insights-empty">
        <p className="eyebrow">Insights</p>
        <h2>No structured insights yet</h2>
        <p>
          Generate a summary, quick bullets, action items, and
          per-chapter titles by running:
        </p>
        <pre className="insights-command" aria-label="Command example">
{`.venv/bin/python -m recap insights --job jobs/<id> --provider groq --force
.venv/bin/python -m recap assemble --job jobs/<id> --force
.venv/bin/python -m recap export-html --job jobs/<id> --force
.venv/bin/python -m recap export-docx --job jobs/<id> --force`}
        </pre>
        <p className="insights-help">
          Use <code>--provider mock</code> for a deterministic offline
          preview. The Groq provider requires <code>GROQ_API_KEY</code>
          {" "}in your environment. A React action surface is coming in a
          later slice — for now insights still run through the CLI.
        </p>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className="insights-card insights-error" role="status">
        <p className="eyebrow">Insights</p>
        <h2>Could not read insights.json</h2>
        <p>{state.message}</p>
        <p className="insights-help">
          Re-run <code>recap insights --force</code> to regenerate the
          artifact. If the file is present but unreadable, the server
          logs the reason without leaking its contents.
        </p>
      </section>
    );
  }

  const { insights } = state;
  const overview = insights.overview;
  const bullets = overview.quick_bullets || [];
  const actions = insights.action_items || [];
  const chapterCount = insights.chapters?.length ?? 0;

  return (
    <section className="insights-card" aria-label="Structured insights">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Insights</p>
          <h2>{overview.title || "Overview"}</h2>
        </div>
        <span className="insights-badge">
          {insights.provider} · {insights.model}
        </span>
      </div>

      {overview.short_summary ? (
        <p className="insights-summary">{overview.short_summary}</p>
      ) : null}

      <dl className="insights-meta">
        <div>
          <dt>Generated</dt>
          <dd>{formatJobDateTime(insights.generated_at)}</dd>
        </div>
        <div>
          <dt>Chapters</dt>
          <dd>{chapterCount}</dd>
        </div>
        <div>
          <dt>Action items</dt>
          <dd>{actions.length}</dd>
        </div>
      </dl>

      {bullets.length > 0 ? (
        <div className="insights-block">
          <h3>Quick bullets</h3>
          <ul className="insights-bullets">
            {bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {actions.length > 0 ? (
        <div className="insights-block">
          <h3>Action items</h3>
          <ul className="insights-actions">
            {actions.map((ai, i) => {
              const chips: string[] = [];
              if (typeof ai.timestamp_seconds === "number") {
                chips.push(formatTimestamp(ai.timestamp_seconds));
              }
              if (typeof ai.chapter_index === "number") {
                chips.push(`Ch. ${ai.chapter_index}`);
              }
              if (ai.owner) chips.push(`Owner: ${ai.owner}`);
              if (ai.due) chips.push(`Due: ${ai.due}`);
              return (
                <li key={i}>
                  <span className="insights-action-text">{ai.text}</span>
                  {chips.length > 0 ? (
                    <span className="insights-action-chips">
                      {chips.map((c, j) => (
                        <span key={j} className="insights-chip">
                          {c}
                        </span>
                      ))}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {insightsJsonUrl ? (
        <footer className="insights-card-footer">
          <a
            className="text-link"
            href={insightsJsonUrl}
            target="_blank"
            rel="noreferrer"
          >
            View raw insights.json →
          </a>
        </footer>
      ) : null}
    </section>
  );
}
