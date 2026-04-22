import { useCallback, useEffect, useRef, useState } from "react";
import {
  getInsightsProviders,
  getInsightsRun,
  getRichReportRun,
  startInsightsRun,
  startRichReportRun,
  type InsightsProvider,
  type InsightsProvidersPayload,
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

type ChainStep =
  | "idle"
  | "insights"
  | "rich-report"
  | "done"
  | "failed";

function describeInsightsStatus(
  status: InsightsRunStatus | null,
): string {
  if (!status || status.status === "no-run") {
    return "Generate an overview, bullets, action items, and chapter summaries.";
  }
  if (status.status === "in-progress") {
    return "Generating… this panel refreshes automatically.";
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
    return "Run the 11-stage chain to produce chapters, screenshots, captions, and the full report set.";
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
  const [providers, setProviders] =
    useState<InsightsProvidersPayload | null>(null);
  const [provider, setProvider] = useState<InsightsProvider>("mock");
  const [forceRerun, setForceRerun] = useState(false);
  const [insightsSubmitting, setInsightsSubmitting] = useState(false);
  const [richSubmitting, setRichSubmitting] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [richError, setRichError] = useState<string | null>(null);
  const [showRichDetails, setShowRichDetails] = useState(false);
  const [chainStep, setChainStep] = useState<ChainStep>("idle");
  const [chainError, setChainError] = useState<string | null>(null);

  const insightsPrevRef = useRef<string | null>(null);
  const richPrevRef = useRef<string | null>(null);

  // Fetch the default insights provider once on mount. If Groq is
  // available in the server environment, the dropdown + chain flip
  // to "groq"; otherwise we stay on "mock". Provider availability
  // is surfaced from /api/insights-providers which never echoes the
  // key itself.
  useEffect(() => {
    let cancelled = false;
    getInsightsProviders()
      .then((payload) => {
        if (cancelled) return;
        setProviders(payload);
        const def = payload.default === "groq" ? "groq" : "mock";
        setProvider(def);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

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
      return { ok: false, message: result.message } as const;
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
    return { ok: true } as const;
  }, [jobId, refreshRichStatus]);

  // "Generate final document" — one-click chain: insights (using the
  // server's default provider: Groq when available, otherwise mock)
  // then rich-report. The effect below watches both statuses and
  // progresses chainStep when each step completes.
  const handleGenerateFinalDocument = useCallback(async () => {
    setChainError(null);
    setChainStep("insights");
    setInsightsError(null);
    setInsightsSubmitting(true);
    const result = await startInsightsRun(jobId, {
      provider,
      force: forceRerun,
    });
    setInsightsSubmitting(false);
    if (result.kind === "error") {
      setInsightsError(result.message);
      setChainError(result.message);
      setChainStep("failed");
      return;
    }
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

  // Chain advance: when insights success lands while we're in the
  // chain, kick rich-report. When either step fails, surface the
  // error and stop.
  useEffect(() => {
    if (chainStep === "insights") {
      const s = insightsStatus?.status;
      if (s === "success") {
        setChainStep("rich-report");
        // Fire-and-forget; handleStartRichReport updates error state.
        void handleStartRichReport().then((res) => {
          if (res && !res.ok) {
            setChainError(res.message ?? "Rich report failed to start.");
            setChainStep("failed");
          }
        });
      } else if (s === "failure") {
        setChainError(
          insightsStatus?.stderr
            ? "Insights stage failed; see stderr below."
            : "Insights stage failed.",
        );
        setChainStep("failed");
      }
    } else if (chainStep === "rich-report") {
      const s = richStatus?.status;
      if (s === "success") {
        setChainStep("done");
      } else if (s === "failure") {
        setChainError(
          richStatus?.failed_stage
            ? `Rich report failed at stage: ${richStatus.failed_stage}.`
            : "Rich report failed.",
        );
        setChainStep("failed");
      }
    }
  }, [
    chainStep,
    insightsStatus?.status,
    insightsStatus?.stderr,
    richStatus?.status,
    richStatus?.failed_stage,
    handleStartRichReport,
  ]);

  const insightsBusy =
    insightsSubmitting || insightsStatus?.status === "in-progress";
  const richBusy =
    richSubmitting || richStatus?.status === "in-progress";
  const anyBusy = insightsBusy || richBusy;

  const chainRunning =
    chainStep === "insights" || chainStep === "rich-report";
  const chainDone = chainStep === "done";
  const chainFailed = chainStep === "failed";
  const defaultProvider = providers?.default === "groq" ? "groq" : "mock";
  const finalPrimaryLabel = chainRunning
    ? chainStep === "insights"
      ? "Generating insights…"
      : "Running rich report…"
    : chainDone
      ? "Update final document"
      : insightsPresent
        ? "Update final document"
        : "Generate final document";
  return (
    <section
      className="run-actions-card"
      aria-label="Run actions"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Final document</p>
          <h2>Generate &amp; enrich</h2>
        </div>
      </div>

      <div className="run-action-subcard run-action-final" aria-label="Final document">
        <p className="run-action-sub">
          One click to generate (or refresh) the full Recap document
          set: insights with{" "}
          <strong>
            {defaultProvider === "groq" ? "Groq" : "Mock"}
          </strong>
          {" "}then chapters, screenshots, captions, and the HTML /
          Markdown / DOCX exports.
        </p>
        {chainError ? (
          <p className="form-error" role="status">
            {chainError}
          </p>
        ) : null}
        {chainDone ? (
          <p className="save-toast" role="status">
            Final document generated.
          </p>
        ) : null}
        <div className="run-action-cta-row">
          <button
            type="button"
            className="primary-button"
            onClick={handleGenerateFinalDocument}
            disabled={chainRunning || anyBusy}
            aria-busy={chainRunning}
          >
            {finalPrimaryLabel}
          </button>
          <span className="run-action-timestamp">
            Uses {defaultProvider === "groq" ? "Groq (cloud)" : "Mock (offline)"}
            {" · "}
            advanced below
          </span>
        </div>
        {chainRunning ? (
          <p className="run-action-note">
            {chainStep === "insights"
              ? "Step 1 of 2 · writing insights.json…"
              : "Step 2 of 2 · scenes → … → export-docx"}
          </p>
        ) : null}
      </div>

      <details className="advanced-disclosure">
        <summary>
          <span className="advanced-disclosure-label">
            Advanced
          </span>
          <span className="advanced-disclosure-hint">
            Run steps individually, pick a provider, or force re-generate
          </span>
        </summary>

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
              <option value="mock">mock · offline</option>
              <option value="groq">groq · cloud</option>
            </select>
          </label>
          <label className="run-field run-field--inline">
            <input
              type="checkbox"
              checked={forceRerun}
              onChange={(e) => setForceRerun(e.target.checked)}
              disabled={insightsBusy}
            />
            <span>Force regenerate</span>
          </label>
        </div>
        {provider === "groq" ? (
          <p className="run-action-note">
            Groq requires <code>GROQ_API_KEY</code> in the server
            environment. The key is never echoed.
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
              Last run · {" "}
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
              Last run · {" "}
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
        <details className="run-action-output">
          <summary>About this run</summary>
          <p className="run-action-note">
            Runs scenes → dedupe → window → similarity → chapters →
            rank → shortlist → verify → assemble → export-html →
            export-docx as one chain under the global single-job slot.
            Other long jobs on this server queue with{" "}
            <code>429 slot</code> until it finishes.
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
        </details>
      </div>
      </details>
    </section>
  );
}
