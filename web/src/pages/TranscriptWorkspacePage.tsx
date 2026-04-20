import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getJob,
  getSpeakerNames,
  getTranscript,
  saveSpeakerNames,
  type JobSummary,
  type SpeakerNamesDoc,
  type TranscriptPayload,
} from "../lib/api";
import { attachSpeakers, buildTranscriptRows } from "../lib/format";
import { computeTranscriptMatches } from "../lib/search";
import SpeakerLegend from "../components/SpeakerLegend";
import TranscriptSearchBar from "../components/TranscriptSearchBar";
import TranscriptTable from "../components/TranscriptTable";
import VideoPlayer from "../components/VideoPlayer";

type LoadState =
  | { status: "loading" }
  | {
      status: "loaded";
      job: JobSummary;
      transcript: TranscriptPayload;
      names: SpeakerNamesDoc;
    }
  | { status: "error"; message: string };

export default function TranscriptWorkspacePage() {
  const { id } = useParams();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [savedPulse, setSavedPulse] = useState(false);
  const [query, setQuery] = useState("");
  const [activeMatchIndex, setActiveMatchIndex] = useState<number | null>(
    null,
  );
  const [hiddenSpeakers, setHiddenSpeakers] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    let cancelled = false;
    if (!id) {
      setState({ status: "error", message: "Missing job id." });
      return;
    }

    setState({ status: "loading" });
    Promise.all([getJob(id), getTranscript(id), getSpeakerNames(id)])
      .then(([job, transcript, names]) => {
        if (!cancelled) {
          setState({ status: "loaded", job, transcript, names });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setState({
            status: "error",
            message:
              err instanceof Error ? err.message : "Could not load job.",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const built = useMemo(() => {
    if (state.status !== "loaded") {
      return {
        speakers: [] as ReturnType<typeof attachSpeakers>["speakers"],
        rows: [] as ReturnType<typeof attachSpeakers>["rows"],
      };
    }
    return attachSpeakers(buildTranscriptRows(state.transcript));
  }, [state]);

  const visibleRows = useMemo(() => {
    if (hiddenSpeakers.size === 0) return built.rows;
    return built.rows.filter(
      (row) => !row.speakerKey || !hiddenSpeakers.has(row.speakerKey),
    );
  }, [built.rows, hiddenSpeakers]);

  const matches = useMemo(
    () => computeTranscriptMatches(visibleRows, query),
    [visibleRows, query],
  );

  // When the match set changes, reset the cursor so it stays valid.
  useEffect(() => {
    if (matches.matches.length === 0) {
      setActiveMatchIndex(null);
      return;
    }
    setActiveMatchIndex((prev) => {
      if (prev == null) return 0;
      if (prev >= matches.matches.length) return 0;
      return prev;
    });
  }, [matches]);

  const handleSaveNames = async (labels: Record<string, string>) => {
    if (!id || state.status !== "loaded") {
      return;
    }
    const saved = await saveSpeakerNames(id, labels);
    setState({ ...state, names: saved });
    setSavedPulse(true);
    window.setTimeout(() => setSavedPulse(false), 2200);
  };

  const toggleSpeaker = useCallback((key: string) => {
    setHiddenSpeakers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const showAllSpeakers = useCallback(() => {
    setHiddenSpeakers(new Set());
  }, []);

  const gotoNext = useCallback(() => {
    if (matches.matches.length === 0) return;
    setActiveMatchIndex((prev) => {
      const base = prev == null ? -1 : prev;
      return (base + 1) % matches.matches.length;
    });
  }, [matches.matches.length]);

  const gotoPrev = useCallback(() => {
    if (matches.matches.length === 0) return;
    setActiveMatchIndex((prev) => {
      const base = prev == null ? matches.matches.length : prev;
      return (base - 1 + matches.matches.length) % matches.matches.length;
    });
  }, [matches.matches.length]);

  if (state.status === "loading") {
    return (
      <main className="workspace">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Recap transcript workspace</p>
          <h1>Loading transcript…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
          <div className="skeleton-line" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="workspace">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap transcript workspace</p>
          <h1>Unable to load transcript</h1>
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

  const { job, transcript, names } = state;
  const title = job.original_filename || job.job_id;
  const hasVideo = Boolean(job.artifacts.analysis_mp4);
  const status = job.status || "unknown";
  const engineLine = [
    transcript.engine ? `Engine · ${transcript.engine}` : null,
    transcript.model ? `Model · ${transcript.model}` : null,
    transcript.language ? `Language · ${transcript.language}` : null,
  ].filter(Boolean);

  return (
    <main className="workspace">
      <header className="workspace-header">
        <div className="workspace-title-group">
          <p className="eyebrow">Transcript workspace</p>
          <h1>{title}</h1>
          <div className="workspace-meta">
            <span
              className={`status-badge status-${status}`}
              aria-label={`Status: ${status}`}
            >
              {status}
            </span>
            <span className="sep">·</span>
            <span title={job.job_id}>
              <code>{job.job_id}</code>
            </span>
            {engineLine.length > 0 ? (
              <>
                <span className="sep">·</span>
                <span>{engineLine.join(" · ")}</span>
              </>
            ) : null}
          </div>
        </div>
        <div className="workspace-actions">
          <Link className="ghost-button" to="/">
            ← All jobs
          </Link>
          <a className="ghost-button" href={`/job/${job.job_id}/transcript`}>
            Legacy transcript
          </a>
          <a className="ghost-button" href={`/job/${job.job_id}/`}>
            Job detail
          </a>
        </div>
      </header>

      <section className="workspace-grid">
        <aside className="left-rail">
          {hasVideo ? (
            <VideoPlayer
              ref={videoRef}
              src={job.urls.analysis_mp4}
              title={title}
            />
          ) : (
            <section
              className="video-card missing-video"
              aria-label="Video unavailable"
            >
              <p className="eyebrow">Video unavailable</p>
              <p>
                <code>analysis.mp4</code> is not present for this job. The
                transcript is still fully navigable.
              </p>
            </section>
          )}
          <SpeakerLegend
            speakers={built.speakers}
            labels={names.speakers}
            hiddenSpeakers={hiddenSpeakers}
            onToggleSpeaker={toggleSpeaker}
            onShowAllSpeakers={showAllSpeakers}
            onSave={handleSaveNames}
          />
          {savedPulse ? (
            <p className="save-toast" role="status">
              Speaker names saved.
            </p>
          ) : null}
          <section className="summary-card" aria-label="Artifacts summary">
            <p className="eyebrow">Artifacts</p>
            <dl>
              <div>
                <dt>Transcript</dt>
                <dd
                  className={
                    job.artifacts.transcript_json
                      ? "summary-ready"
                      : "summary-missing"
                  }
                >
                  {job.artifacts.transcript_json ? "Ready" : "Missing"}
                </dd>
              </div>
              <div>
                <dt>Speaker names</dt>
                <dd
                  className={
                    job.artifacts.speaker_names_json
                      ? "summary-ready"
                      : "summary-missing"
                  }
                >
                  {job.artifacts.speaker_names_json ? "Saved" : "Default"}
                </dd>
              </div>
              <div>
                <dt>Report</dt>
                <dd
                  className={
                    job.artifacts.report_md
                      ? "summary-ready"
                      : "summary-missing"
                  }
                >
                  {job.artifacts.report_md ? "Ready" : "Missing"}
                </dd>
              </div>
              {typeof transcript.duration === "number" ? (
                <div>
                  <dt>Duration</dt>
                  <dd>{formatDuration(transcript.duration)}</dd>
                </div>
              ) : null}
            </dl>
          </section>
        </aside>

        <TranscriptTable
          rows={visibleRows}
          speakerLabels={names.speakers}
          videoRef={videoRef}
          matches={matches}
          activeMatchIndex={activeMatchIndex}
          hiddenSpeakers={hiddenSpeakers}
          totalRowCount={built.rows.length}
          toolbar={
            <TranscriptSearchBar
              query={query}
              onQueryChange={setQuery}
              matchCount={matches.matches.length}
              activeMatchIndex={activeMatchIndex}
              onPrev={gotoPrev}
              onNext={gotoNext}
            />
          }
        />
      </section>
      <footer className="workspace-footer">
        <Link className="text-link" to="/">
          Open another workspace
        </Link>
      </footer>
    </main>
  );
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  if (m > 0) {
    return `${m}m ${String(s).padStart(2, "0")}s`;
  }
  return `${s}s`;
}
