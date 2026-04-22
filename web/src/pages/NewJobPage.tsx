import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  getEngines,
  getSources,
  startJob,
  type EngineEntry,
  type RecordingUploadResponse,
  type SourceEntry,
  type StartSourceSpec,
} from "../lib/api";
import { formatFileSize, formatJobDateTime } from "../lib/format";
import RecordingPanel from "../components/RecordingPanel";

type LoadState =
  | { status: "loading" }
  | {
      status: "loaded";
      sources: SourceEntry[];
      sourcesRoot: string | null;
      sourcesRootExists: boolean;
      extensions: string[];
      engines: EngineEntry[];
      defaultEngine: string;
    }
  | { status: "error"; message: string };

type Mode = "pick" | "record" | "absolute";

type StartState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "error"; message: string; reason?: string }
  | { kind: "accepted"; jobId: string };

function sourceSpecFromState(
  mode: Mode,
  pickedName: string,
  absolutePath: string,
): StartSourceSpec | null {
  if (mode === "pick") {
    if (!pickedName) return null;
    return { kind: "sources-root", name: pickedName };
  }
  const trimmed = absolutePath.trim();
  if (!trimmed) return null;
  return { kind: "absolute-path", path: trimmed };
}

export default function NewJobPage() {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [mode, setMode] = useState<Mode>("pick");
  const [pickedName, setPickedName] = useState("");
  const [absolutePath, setAbsolutePath] = useState("");
  const [engine, setEngine] = useState("faster-whisper");
  const [startState, setStartState] = useState<StartState>({ kind: "idle" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    Promise.all([getSources(), getEngines()])
      .then(([sources, engines]) => {
        if (cancelled) return;
        setState({
          status: "loaded",
          sources: sources.sources,
          sourcesRoot: sources.sources_root,
          sourcesRootExists: sources.sources_root_exists,
          extensions: sources.extensions,
          engines: engines.engines,
          defaultEngine: engines.default,
        });
        setEngine(engines.default);
        if (sources.sources.length > 0) {
          setPickedName(sources.sources[0].name);
          setMode("pick");
        } else {
          setMode("absolute");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          status: "error",
          message:
            err instanceof Error
              ? err.message
              : "Could not load /api/sources or /api/engines.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const spec = useMemo(
    () => sourceSpecFromState(mode, pickedName, absolutePath),
    [mode, pickedName, absolutePath],
  );

  const selectedEngineAvailable = useMemo(() => {
    if (state.status !== "loaded") return false;
    const entry = state.engines.find((e) => e.id === engine);
    return entry ? entry.available : false;
  }, [state, engine]);

  const canSubmit =
    state.status === "loaded" &&
    spec !== null &&
    selectedEngineAvailable &&
    startState.kind !== "submitting";

  const handleRecordingSaved = (saved: RecordingUploadResponse) => {
    setState((current) => {
      if (current.status !== "loaded") return current;
      const entry: SourceEntry = {
        name: saved.name,
        size_bytes: saved.size_bytes,
        modified_at: saved.modified_at,
      };
      const existing = current.sources.filter(
        (src) => src.name !== saved.name,
      );
      return {
        ...current,
        sources: [entry, ...existing],
      };
    });
    setPickedName(saved.name);
    setMode("pick");
  };

  const handleStart = async () => {
    if (!spec) return;
    setStartState({ kind: "submitting" });
    const result = await startJob({ source: spec, engine });
    if (result.kind === "accepted") {
      setStartState({ kind: "accepted", jobId: result.response.job_id });
      // Navigate to the new React dashboard; SPA router will pick it up.
      navigate(`/job/${encodeURIComponent(result.response.job_id)}`);
      return;
    }
    setStartState({
      kind: "error",
      message: result.message,
      reason: result.reason,
    });
  };

  if (state.status === "loading") {
    return (
      <main className="new-job-shell">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Recap · New job</p>
          <h1>Loading sources and engines…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="new-job-shell">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap · New job</p>
          <h1>Unable to load the new-job page</h1>
          <p>{state.message}</p>
          <div className="job-card-actions">
            <Link className="primary-button" to="/">
              Back to jobs
            </Link>
            <a className="ghost-button" href="/new">
              Legacy /new page
            </a>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="new-job-shell">
      <header className="new-job-hero">
        <p className="eyebrow">Recap · New job</p>
        <h1>Start a recap</h1>
        <p className="new-job-hero-sub">
          Record the screen directly in the browser, or point Recap at
          a file you already have. Processing stays local-first; cloud
          engines are opt-in.
        </p>
      </header>

      <section className="new-job-grid">
        <section
          className="new-job-card source-card"
          aria-label="Source video"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">1 · Source video</p>
              <h2>Pick a file</h2>
            </div>
            <span className="source-root-chip">
              {state.sourcesRoot ? (
                <>
                  <span className="source-root-label">Sources root</span>
                  <code>{state.sourcesRoot}</code>
                </>
              ) : (
                <em>No sources root configured</em>
              )}
            </span>
          </div>

          <div
            className="mode-toggle"
            role="tablist"
            aria-label="Source input mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={mode === "pick"}
              className={`mode-tab ${mode === "pick" ? "active" : ""}`}
              onClick={() => setMode("pick")}
              disabled={state.sources.length === 0}
              title={
                state.sources.length === 0
                  ? "No files under the sources root"
                  : undefined
              }
            >
              Sources root
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "record"}
              className={`mode-tab ${mode === "record" ? "active" : ""}`}
              onClick={() => setMode("record")}
            >
              Record screen
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === "absolute"}
              className={`mode-tab ${mode === "absolute" ? "active" : ""}`}
              onClick={() => setMode("absolute")}
            >
              Absolute path
            </button>
          </div>

          {mode === "pick" ? (
            state.sources.length > 0 ? (
              <ul
                className="source-list"
                role="radiogroup"
                aria-label="Available source videos"
              >
                {state.sources.map((src) => {
                  const checked = src.name === pickedName;
                  return (
                    <li key={src.name}>
                      <label
                        className={`source-row ${checked ? "checked" : ""}`}
                      >
                        <input
                          type="radio"
                          name="source-picker"
                          value={src.name}
                          checked={checked}
                          onChange={() => setPickedName(src.name)}
                        />
                        <span className="source-row-body">
                          <span className="source-row-name">{src.name}</span>
                          <span className="source-row-meta">
                            {formatFileSize(src.size_bytes)} ·{" "}
                            {formatJobDateTime(src.modified_at)}
                          </span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="source-empty">
                <h3>No videos under the sources root yet</h3>
                <p>
                  {state.sourcesRootExists
                    ? `Drop a file (${state.extensions.join(" ")}) into `
                    : "Create the directory and drop a file into "}
                  <code>{state.sourcesRoot ?? "sample_videos/"}</code>,
                  record a screen clip in the "Record screen" tab, or
                  switch to "Absolute path" to point at a file anywhere
                  on disk.
                </p>
              </div>
            )
          ) : mode === "record" ? (
            <RecordingPanel onSaved={handleRecordingSaved} />
          ) : (
            <div className="absolute-path-field">
              <label htmlFor="absolute-path-input">
                Absolute path to a video file
              </label>
              <input
                id="absolute-path-input"
                type="text"
                inputMode="url"
                spellCheck={false}
                autoComplete="off"
                placeholder={
                  state.sourcesRoot
                    ? `${state.sourcesRoot}/your-file.mp4`
                    : "/absolute/path/to/video.mp4"
                }
                value={absolutePath}
                onChange={(e) => setAbsolutePath(e.target.value)}
              />
              <p className="absolute-path-help">
                Must live under the configured sources root
                {state.sourcesRoot ? (
                  <>
                    {" "}
                    (<code>{state.sourcesRoot}</code>)
                  </>
                ) : null}{" "}
                for safety. Use this when the file lives in a
                subdirectory or needs an explicit path.
              </p>
            </div>
          )}
        </section>

        <section
          className="new-job-card engine-card"
          aria-label="Transcription engine"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">2 · Transcription</p>
              <h2>Engine</h2>
            </div>
          </div>
          <p className="engine-default-line">
            {(() => {
              const def = state.engines.find(
                (e) => e.id === state.defaultEngine,
              );
              const label = def?.label ?? state.defaultEngine;
              return (
                <>
                  Using <strong>{label}</strong> by default
                  {state.defaultEngine === "deepgram" ? (
                    <> — Deepgram detected in the server environment.</>
                  ) : (
                    <> — local and fully offline.</>
                  )}
                </>
              );
            })()}
          </p>
          <details className="advanced-disclosure">
            <summary>
              <span className="advanced-disclosure-label">
                Advanced
              </span>
              <span className="advanced-disclosure-hint">
                Pick a different engine
              </span>
            </summary>
            <ul
              className="engine-list"
              role="radiogroup"
              aria-label="Transcription engine"
            >
              {state.engines.map((entry) => {
                const checked = engine === entry.id;
                const disabled = !entry.available;
                return (
                  <li key={entry.id}>
                    <label
                      className={`engine-row ${
                        checked ? "checked" : ""
                      } ${disabled ? "disabled" : ""}`}
                    >
                      <input
                        type="radio"
                        name="engine"
                        value={entry.id}
                        checked={checked}
                        disabled={disabled}
                        onChange={() => setEngine(entry.id)}
                      />
                      <span className="engine-row-body">
                        <span className="engine-row-title">
                          <span className="engine-row-label">
                            {entry.label}
                          </span>
                          <span className="engine-row-tag">
                            {entry.category}
                          </span>
                          {disabled ? (
                            <span className="engine-row-badge">
                              Unavailable
                            </span>
                          ) : null}
                        </span>
                        {entry.note ? (
                          <span className="engine-row-note">
                            {entry.note}
                          </span>
                        ) : null}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </details>
        </section>

        <section
          className="new-job-card next-card"
          aria-label="What happens next"
        >
          <details className="next-steps-disclosure">
            <summary>
              <span className="eyebrow">3 · What happens next</span>
              <span className="next-steps-summary">
                Ingest → normalize → transcribe → assemble.
              </span>
            </summary>
            <ol className="next-steps">
              <li>
                <strong>Ingest</strong> — the source file is copied into a
                new job directory under <code>jobs/</code>.
              </li>
              <li>
                <strong>Normalize</strong> — FFmpeg produces
                <code> analysis.mp4</code> and <code>audio.wav</code>.
              </li>
              <li>
                <strong>Transcribe</strong> — faster-whisper or Deepgram
                writes <code>transcript.json</code>.
              </li>
              <li>
                <strong>Assemble</strong> — a Markdown{" "}
                <code>report.md</code> is generated. Structured insights
                and rich reports are still opt-in via the CLI.
              </li>
            </ol>
          </details>
        </section>

        <section
          className="new-job-card launch-card"
          aria-label="Start job"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Start</p>
              <h2>Ready to go?</h2>
            </div>
          </div>
          {startState.kind === "error" ? (
            <p className="form-error" role="status">
              {startState.message}
            </p>
          ) : null}
          {startState.kind === "accepted" ? (
            <p className="save-toast" role="status">
              Job {startState.jobId} started. Redirecting to the
              dashboard…
            </p>
          ) : null}
          <div className="launch-actions">
            <button
              type="button"
              className="primary-button"
              onClick={handleStart}
              disabled={!canSubmit}
              aria-disabled={!canSubmit}
            >
              {startState.kind === "submitting"
                ? "Starting…"
                : "Start job"}
            </button>
            <Link className="text-link" to="/">
              Cancel
            </Link>
            <a className="text-link launch-legacy" href="/new">
              Use legacy /new
            </a>
          </div>
          <p className="launch-hint">
            Thin client on top of the existing{" "}
            <code>recap run</code> pipeline. Legacy <code>/new</code>{" "}
            stays live as a fallback.
          </p>
        </section>
      </section>
    </main>
  );
}
