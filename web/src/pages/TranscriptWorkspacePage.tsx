import { useEffect, useRef, useState } from "react";
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
import SpeakerLegend from "../components/SpeakerLegend";
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
            message: err instanceof Error ? err.message : "Could not load job.",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const handleSaveNames = async (labels: Record<string, string>) => {
    if (!id || state.status !== "loaded") {
      return;
    }
    const saved = await saveSpeakerNames(id, labels);
    setState({ ...state, names: saved });
    setSavedPulse(true);
    window.setTimeout(() => setSavedPulse(false), 2200);
  };

  if (state.status === "loading") {
    return (
      <main className="app-shell">
        <section className="hero-card skeleton-card">
          <p className="eyebrow">Recap web</p>
          <h1>Loading transcript workspace</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="app-shell">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap web</p>
          <h1>Unable to load transcript</h1>
          <p>{state.message}</p>
          <a className="text-link" href="/">
            Return to legacy dashboard
          </a>
        </section>
      </main>
    );
  }

  const { job, transcript, names } = state;
  const built = attachSpeakers(buildTranscriptRows(transcript));
  const title = job.original_filename || job.job_id;
  const hasVideo = Boolean(job.artifacts.analysis_mp4);
  const engineLine = [
    transcript.engine ? `Engine: ${transcript.engine}` : null,
    transcript.model ? `Model: ${transcript.model}` : null,
    transcript.language ? `Language: ${transcript.language}` : null,
  ].filter(Boolean);

  return (
    <main className="workspace">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">Recap transcript workspace</p>
          <h1>{title}</h1>
          <div className="meta-line">
            <span className={`status-badge status-${job.status || "unknown"}`}>
              {job.status || "unknown"}
            </span>
            <span>{job.job_id}</span>
            {engineLine.length > 0 ? <span>{engineLine.join(" / ")}</span> : null}
          </div>
        </div>
        <div className="header-actions">
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
            <section className="video-card missing-video">
              <p className="eyebrow">Video unavailable</p>
              <p>analysis.mp4 is not present for this job.</p>
            </section>
          )}
          <SpeakerLegend
            speakers={built.speakers}
            labels={names.speakers}
            onSave={handleSaveNames}
          />
          {savedPulse ? (
            <p className="save-toast" role="status">
              Speaker names saved.
            </p>
          ) : null}
          <section className="summary-card">
            <p className="eyebrow">Artifacts</p>
            <dl>
              <div>
                <dt>Transcript</dt>
                <dd>{job.artifacts.transcript_json ? "Ready" : "Missing"}</dd>
              </div>
              <div>
                <dt>Speaker names</dt>
                <dd>{job.artifacts.speaker_names_json ? "Saved" : "Default"}</dd>
              </div>
              <div>
                <dt>Report</dt>
                <dd>{job.artifacts.report_md ? "Ready" : "Missing"}</dd>
              </div>
            </dl>
          </section>
        </aside>

        <TranscriptTable
          rows={built.rows}
          speakerLabels={names.speakers}
          videoRef={videoRef}
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
