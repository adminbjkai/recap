import { useEffect, useState } from "react";
import type { JobSummary } from "../lib/api";
import {
  formatElapsedSeconds,
  formatFileSize,
} from "../lib/format";
import {
  summarizeJobProgress,
  type ProgressSnapshot,
} from "../lib/progress";

export type JobProgressPanelProps = {
  job: JobSummary;
  /**
   * When true, render the compact "completed" summary (one-line
   * row) suitable for the dashboard after the job has finished.
   * When false (default), render the full live-progress card
   * used while the job is running.
   */
  compact?: boolean;
  /**
   * Optional test override for the clock so running-elapsed
   * renders deterministically. Production callers should omit
   * this and let the panel tick its own `Date.now()` every
   * second.
   */
  now?: number;
};

/**
 * Reassuring live-progress card for a running Recap job.
 *
 * Feeds entirely off the `GET /api/jobs/:id` summary (which
 * already includes the full `stages` dict with the normalize
 * heartbeat fields `command_mode`, `phase`, `percent`,
 * `elapsed_seconds`, `output_bytes`, and `input_duration_seconds`).
 * No new backend surface, no extra polling endpoint.
 *
 * States:
 * - **running** (default card): shows current stage, completed
 *   count, elapsed seconds since the running stage started,
 *   and normalize extras when the normalize stage is live.
 * - **completed**: compact single-line confirmation so the
 *   dashboard does not keep shouting after the job is done.
 * - **failed**: surfaces the failed stage's error one-liner on
 *   a red-tinted surface; never shows a running timer.
 * - **pending**: neutral one-liner ("Waiting to start…").
 */
export default function JobProgressPanel({
  job,
  compact,
  now,
}: JobProgressPanelProps) {
  // Tick a local clock once per second while a stage is running
  // so the "Elapsed" readout advances even between polls.
  const [tick, setTick] = useState<number>(() => now ?? Date.now());
  useEffect(() => {
    if (typeof now === "number") {
      // Test-controlled clock — do not start a timer.
      setTick(now);
      return undefined;
    }
    const snap = summarizeJobProgress(job);
    if (snap.overallStatus !== "running") {
      return undefined;
    }
    const id = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [job, now]);

  const snap = summarizeJobProgress(job, tick);

  if (snap.overallStatus === "failed") {
    return renderFailed(snap);
  }
  if (snap.overallStatus === "completed") {
    return renderCompleted(snap, compact ?? true);
  }
  if (snap.overallStatus === "running") {
    return renderRunning(snap);
  }
  return renderPending(snap);
}

function renderPending(snap: ProgressSnapshot) {
  return (
    <section
      className="progress-panel progress-panel--pending"
      aria-label="Job progress"
      role="status"
    >
      <div className="progress-panel-head">
        <span className="progress-panel-status">Waiting to start…</span>
        {snap.totalCount > 0 ? (
          <span className="progress-panel-count">
            {snap.completedCount}/{snap.totalCount} stages
          </span>
        ) : null}
      </div>
    </section>
  );
}

function renderRunning(snap: ProgressSnapshot) {
  const current = snap.currentStage;
  const pct = snap.normalize.percent;
  const isNormalize = current?.name === "normalize";
  const showNormalizeExtras =
    isNormalize &&
    (snap.normalize.command_mode !== null ||
      typeof pct === "number" ||
      snap.normalize.output_bytes !== null ||
      snap.normalize.phase !== null);
  return (
    <section
      className="progress-panel progress-panel--running"
      aria-label="Job progress"
      role="status"
      aria-live="polite"
    >
      <div className="progress-panel-head">
        <span className="progress-panel-label">
          <span className="progress-panel-dot" aria-hidden />
          <span className="progress-panel-stage">
            {current ? current.label : "Starting…"}
          </span>
        </span>
        <span className="progress-panel-count" aria-label="Stage progress">
          {snap.completedCount} / {snap.totalCount} done
        </span>
      </div>

      {typeof pct === "number" && Number.isFinite(pct) ? (
        <div
          className="progress-panel-bar"
          role="progressbar"
          aria-label={`${current?.label ?? "Stage"} progress`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.max(0, Math.min(100, Math.round(pct)))}
        >
          <div
            className="progress-panel-bar-fill"
            style={{
              width: `${Math.max(0, Math.min(100, Math.round(pct)))}%`,
            }}
          />
        </div>
      ) : null}

      <dl className="progress-panel-meta">
        {current ? (
          <div>
            <dt>Elapsed</dt>
            <dd>
              {snap.runningElapsedSeconds != null
                ? formatElapsedSeconds(snap.runningElapsedSeconds)
                : "—"}
            </dd>
          </div>
        ) : null}
        {showNormalizeExtras && snap.normalize.command_mode ? (
          <div>
            <dt>Mode</dt>
            <dd className="progress-panel-mode">
              {snap.normalize.command_mode}
            </dd>
          </div>
        ) : null}
        {showNormalizeExtras && typeof pct === "number" ? (
          <div>
            <dt>Progress</dt>
            <dd>
              {Math.round(pct)}%
              {snap.normalize.input_duration_seconds ? (
                <span className="progress-panel-sub">
                  {" "}of {formatElapsedSeconds(
                    snap.normalize.input_duration_seconds,
                  )}
                </span>
              ) : null}
            </dd>
          </div>
        ) : null}
        {showNormalizeExtras && snap.normalize.output_bytes != null ? (
          <div>
            <dt>Output</dt>
            <dd>{formatFileSize(snap.normalize.output_bytes)}</dd>
          </div>
        ) : null}
        {showNormalizeExtras && snap.normalize.phase ? (
          <div>
            <dt>Phase</dt>
            <dd>{snap.normalize.phase}</dd>
          </div>
        ) : null}
      </dl>

      {snap.totalCount > 0 ? (
        <ol
          className="progress-panel-stages"
          aria-label="Pipeline stages"
        >
          {snap.slots.map((s) => (
            <li
              key={s.name}
              className={`progress-panel-stage-pill progress-panel-stage-pill--${s.status}`}
              aria-current={
                current && current.name === s.name ? "step" : undefined
              }
              title={`${s.label}: ${s.status}`}
            >
              <span className="progress-panel-stage-pill-label">
                {s.label}
              </span>
              <span className="visually-hidden">{s.status}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function renderCompleted(snap: ProgressSnapshot, compact: boolean) {
  if (compact) {
    return (
      <section
        className="progress-panel progress-panel--completed progress-panel--compact"
        aria-label="Job progress"
        role="status"
      >
        <span className="progress-panel-dot" aria-hidden />
        <span className="progress-panel-label">
          Completed · {snap.completedCount} / {snap.totalCount} stages
        </span>
        {snap.failedCount > 0 ? (
          <span className="progress-panel-count progress-panel-count--warn">
            {snap.failedCount} failed
          </span>
        ) : null}
      </section>
    );
  }
  return (
    <section
      className="progress-panel progress-panel--completed"
      aria-label="Job progress"
      role="status"
    >
      <div className="progress-panel-head">
        <span className="progress-panel-label">Run complete</span>
        <span className="progress-panel-count">
          {snap.completedCount} / {snap.totalCount} stages
        </span>
      </div>
    </section>
  );
}

function renderFailed(snap: ProgressSnapshot) {
  const stage = snap.failedStage;
  return (
    <section
      className="progress-panel progress-panel--failed"
      aria-label="Job progress"
      role="status"
    >
      <div className="progress-panel-head">
        <span className="progress-panel-label">
          <span className="progress-panel-dot" aria-hidden />
          Failed · {stage ? stage.label : "stage unknown"}
        </span>
        <span className="progress-panel-count">
          {snap.completedCount} / {snap.totalCount} stages
        </span>
      </div>
      {stage?.error ? (
        <p className="progress-panel-error" role="status">
          {stage.error}
        </p>
      ) : null}
    </section>
  );
}
