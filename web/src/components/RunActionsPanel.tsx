import { useCallback, useEffect, useRef, useState } from "react";
import {
  getInsightsRun,
  getRichReportRun,
  startInsightsRun,
  startRichReportRun,
  type InsightsProvider,
  type InsightsRunStatus,
  type RichReportRunStatus,
} from "../lib/api";
import { formatElapsedSeconds, formatJobDateTime } from "../lib/format";

export type RunActionsPanelProps = {
  jobId: string;
  insightsPresent: boolean;
  onRunCompleted?: (runType: "insights" | "rich-report") => void;
};

const POLL_INTERVAL_MS = 2500;

function describeInsightsStatus(
  status: InsightsRunStatus | null,
): string {
  if (!status || status.status === "no-run") {
    return "No runs yet. The dashboard will show progress here once a run starts.";
  }
  if (status.status === "in-progress") {
    return "Insights are generating. This panel polls automatically.";
  }
  if (status.status === "success") {
    return "Last run completed successfully.";
  }
  return "Last run failed. See error output below.";
}

function describeRichReportStatus(
  status: RichReportRunStatus | null,
): string {
  if (!status || status.status === "no-run") {
    return "No rich-report runs yet. Kicking one off runs 11 stages (scenes → dedupe → window → similarity → chapters → rank → shortlist → verify → assemble → export-html → export-docx).";
  }
  if (status.status === "in-progress") {
    const curr = status.current_stage;
    return curr
      ? `Running · currently at stage: ${curr}.`
      : "Running · stages will appear below as they start.";
  }
  if (status.status === "success") {
    return "Rich report completed successfully.";
  }
  return status.failed_stage
    ? `Rich report failed at stage: ${status.failed_stage}.`
    : "Rich report failed.";
}

function StatusDot({
  kind,
}: {
  kind: "idle" | "running" | "success" | "failed";
}) {
  return (
    <span
      aria-hidden="true"
      className={`run-status-dot run-status-dot--${kind}`}
    />
  );
}

function statusDotKind(
  status: InsightsRunStatus | RichReportRunStatus | null,
): "idle" | "running" | "success" | "failed" {
  if (!status || status.status === "no-run") return "idle";
  if (status.status === "in-progress") return "running";
  if (status.status === "success") return "success";
  return "failed";
}

export default function RunActionsPanel({
  jobId,
  insightsPresent,
  onRunCompleted,
}: RunActionsPanelProps) {
  const [insightsStatus, setInsightsStatus] =
    useState<InsightsRunStatus | null>(null);
  const [richStatus, setRichStatus] = useState<RichReportRunStatus | null>(
    null,
  );
  const [provider, setProvider] = useState<InsightsProvider>("mock");
  const [forceRerun, setForceRerun] = useState(false);
  const [insightsSubmitting, setInsightsSubmitting] = useState(false);
  const [richSubmitting, setRichSubmitting] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [richError, setRichError] = useState<string | null>(null);
  const [showRichDetails, setShowRichDetails] = useState(false);

  const insightsPrevRef = useRef<string | null>(null);
  const richPrevRef = useRef<string | null>(null);

  const refreshInsightsStatus = useCallback(async () => {
    try {
      const data = await getInsightsRun(jobId);
      setInsightsStatus(data);
      const prev = insightsPrevRef.current;
      if (
        prev === "in-progress" &&
        data.status !== "in-progress" &&
        data.status !== "no-run"
      ) {
        onRunCompleted?.("insights");
      }
      insightsPrevRef.current = data.status;
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : "Could not read insights run status.";
      setInsightsError(msg);
    }
  }, [jobId, onRunCompleted]);

  const refreshRichStatus = useCallback(async () => {
    try {
      const data = await getRichReportRun(jobId);
      setRichStatus(data);
      const prev = richPrevRef.current;
      if (
        prev === "in-progress" &&
        data.status !== "in-progress" &&
        data.status !== "no-run"
      ) {
        onRunCompleted?.("rich-report");
      }
      richPrevRef.current = data.status;
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : "Could not read rich-report run status.";
      setRichError(msg);
    }
  }, [jobId, onRunCompleted]);

  useEffect(() => {
    refreshInsightsStatus();
    refreshRichStatus();
  }, [refreshInsightsStatus, refreshRichStatus]);

  useEffect(() => {
    const active =
      insightsStatus?.status === "in-progress" ||
      richStatus?.status === "in-progress";
    if (!active) return;
    const id = window.setInterval(() => {
      if (insightsStatus?.status === "in-progress") {
        refreshInsightsStatus();
      }
      if (richStatus?.status === "in-progress") {
        refreshRichStatus();
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [
    insightsStatus?.status,
    richStatus?.status,
    refreshInsightsStatus,
    refreshRichStatus,
  ]);

  const handleStartInsights = useCallback(async () => {
    setInsightsError(null);
    setInsightsSubmitting(true);
    const result = await startInsightsRun(jobId, {
      provider,
      force: forceRerun,
    });
    setInsightsSubmitting(false);
    if (result.kind === "error") {
      setInsightsError(result.message);
      return;
    }
    // Seed an optimistic in-progress state so the polling loop wakes up
    // even before the first GET round-trip resolves.
    setInsightsStatus({
      job_id: jobId,
      run_type: "insights",
      status: "in-progress",
      started_at: result.response.started_at,
      provider: result.response.provider,
      force: result.response.force,
    });
    insightsPrevRef.current = "in-progress";
    refreshInsightsStatus();
  }, [jobId, provider, forceRerun, refreshInsightsStatus]);

  const handleStartRichReport = useCallback(async () => {
    setRichError(null);
    setRichSubmitting(true);
    const result = await startRichReportRun(jobId);
    setRichSubmitting(false);
    if (result.kind === "error") {
      setRichError(result.message);
      return;
    }
    setRichStatus({
      job_id: jobId,
      run_type: "rich-report",
      status: "in-progress",
      started_at: result.response.started_at,
      current_stage: null,
      failed_stage: null,
      stages: [],
    });
    richPrevRef.current = "in-progress";
    setShowRichDetails(true);
    refreshRichStatus();
  }, [jobId, refreshRichStatus]);

  const insightsBusy =
    insightsSubmitting || insightsStatus?.status === "in-progress";
  const richBusy =
    richSubmitting || richStatus?.status === "in-progress";
  const anyBusy = insightsBusy || richBusy;

  return (
    <section
      className="run-actions-card"
      aria-label="Run actions"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Actions</p>
          <h2>Generate &amp; enrich</h2>
        </div>
      </div>
      <p className="run-actions-intro">
        Kick off insights or the full rich-report chain from here. Runs
        happen on the server and this panel polls every{" "}
        {(POLL_INTERVAL_MS / 1000).toFixed(1)}s while something is in
        flight. The legacy HTML dashboard is still live as a fallback.
      </p>

      <div className="run-action-subcard" aria-label="Insights action">
        <div className="run-action-header">
          <div className="run-action-title">
            <StatusDot kind={statusDotKind(insightsStatus)} />
            <h3>
              {insightsPresent
                ? "Regenerate insights"
                : "Generate insights"}
            </h3>
          </div>
          <span
            className={`run-status-pill run-status-pill--${statusDotKind(
              insightsStatus,
            )}`}
          >
            {insightsStatus?.status ?? "no-run"}
          </span>
        </div>
        <p className="run-action-sub">
          {describeInsightsStatus(insightsStatus)}
        </p>
        <div className="run-action-fields">
          <label className="run-field">
            <span className="run-field-label">Provider</span>
            <select
              value={provider}
              onChange={(e) =>
                setProvider(e.target.value as InsightsProvider)
              }
              disabled={insightsBusy}
            >
              <option value="mock">mock (offline, deterministic)</option>
              <option value="groq">groq (cloud, requires GROQ_API_KEY)</option>
            </select>
          </label>
          <label className="run-field run-field--inline">
            <input
              type="checkbox"
              checked={forceRerun}
              onChange={(e) => setForceRerun(e.target.checked)}
              disabled={insightsBusy}
            />
            <span>Force regenerate (pass --force)</span>
          </label>
        </div>
        {provider === "groq" ? (
          <p className="run-action-note">
            The Groq provider requires{" "}
            <code>GROQ_API_KEY</code> in the server's environment. The
            server never echoes the key; if it's missing the request
            returns <code>400 groq-unavailable</code>.
          </p>
        ) : null}
        {insightsError ? (
          <p className="form-error" role="status">
            {insightsError}
          </p>
        ) : null}
        <div className="run-action-cta-row">
          <button
            type="button"
            className="primary-button"
            onClick={handleStartInsights}
            disabled={insightsBusy || anyBusy}
            aria-busy={insightsBusy}
          >
            {insightsSubmitting
              ? "Starting…"
              : insightsStatus?.status === "in-progress"
                ? "Generating…"
                : insightsPresent
                  ? "Regenerate insights"
                  : "Generate insights"}
          </button>
          {insightsStatus?.started_at ? (
            <span className="run-action-timestamp">
              Last started{" "}
              {formatJobDateTime(insightsStatus.started_at)}
              {typeof insightsStatus.elapsed === "number" ? (
                <>
                  {" · "}
                  {formatElapsedSeconds(insightsStatus.elapsed)}
                </>
              ) : null}
            </span>
          ) : null}
        </div>
        {insightsStatus?.status === "failure" &&
        (insightsStatus.stderr || insightsStatus.stdout) ? (
          <details className="run-action-output">
            <summary>Show stderr / stdout</summary>
            {insightsStatus.stderr ? (
              <pre className="run-action-pre run-action-pre--err">
                {insightsStatus.stderr}
              </pre>
            ) : null}
            {insightsStatus.stdout ? (
              <pre className="run-action-pre">
                {insightsStatus.stdout}
              </pre>
            ) : null}
          </details>
        ) : null}
      </div>

      <div className="run-action-subcard" aria-label="Rich report action">
        <div className="run-action-header">
          <div className="run-action-title">
            <StatusDot kind={statusDotKind(richStatus)} />
            <h3>Generate rich report</h3>
          </div>
          <span
            className={`run-status-pill run-status-pill--${statusDotKind(
              richStatus,
            )}`}
          >
            {richStatus?.status ?? "no-run"}
          </span>
        </div>
        <p className="run-action-sub">
          {describeRichReportStatus(richStatus)}
        </p>
        {richError ? (
          <p className="form-error" role="status">
            {richError}
          </p>
        ) : null}
        <div className="run-action-cta-row">
          <button
            type="button"
            className="primary-button"
            onClick={handleStartRichReport}
            disabled={richBusy || anyBusy}
            aria-busy={richBusy}
          >
            {richSubmitting
              ? "Starting…"
              : richStatus?.status === "in-progress"
                ? "Running…"
                : "Generate rich report"}
          </button>
          {richStatus?.started_at ? (
            <span className="run-action-timestamp">
              Last started{" "}
              {formatJobDateTime(richStatus.started_at)}
              {typeof richStatus.elapsed === "number" ? (
                <>
                  {" · "}
                  {formatElapsedSeconds(richStatus.elapsed)}
                </>
              ) : null}
            </span>
          ) : null}
        </div>
        {richStatus && richStatus.stages && richStatus.stages.length > 0 ? (
          <div className="run-action-stages">
            <button
              type="button"
              className="run-toggle"
              onClick={() => setShowRichDetails((v) => !v)}
              aria-expanded={showRichDetails}
            >
              {showRichDetails
                ? "Hide stage details"
                : "Show stage details"}
            </button>
            {showRichDetails ? (
              <ol className="run-stage-list">
                {richStatus.stages.map((row) => (
                  <li
                    key={row.name}
                    className={`run-stage-row run-stage-row--${row.status}`}
                  >
                    <div className="run-stage-row-head">
                      <StatusDot
                        kind={
                          row.status === "completed"
                            ? "success"
                            : row.status === "failed"
                              ? "failed"
                              : row.status === "running"
                                ? "running"
                                : "idle"
                        }
                      />
                      <span className="run-stage-name">{row.name}</span>
                      <span className="run-stage-status">{row.status}</span>
                      {typeof row.elapsed === "number" ? (
                        <span className="run-stage-elapsed">
                          {formatElapsedSeconds(row.elapsed)}
                        </span>
                      ) : null}
                    </div>
                    {row.status === "failed" && row.stderr ? (
                      <pre className="run-action-pre run-action-pre--err">
                        {row.stderr}
                      </pre>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : null}
        <p className="run-action-note">
          Runs the legacy 11-stage chain under the same global
          single-job slot. While this is running, other long jobs on
          this server will get <code>429 slot</code> until it finishes.
        </p>
        <p className="run-action-note">
          Need progress on the legacy HTML page?{" "}
          <a
            className="text-link"
            href={`/job/${encodeURIComponent(jobId)}/run/rich-report/last`}
          >
            Open the legacy rich-report status page
          </a>
          .
        </p>
      </div>
    </section>
  );
}
