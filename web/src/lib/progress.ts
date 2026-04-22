/**
 * Pure helpers for deriving live-progress state from a
 * `JobSummary` polled off `GET /api/jobs/:id`.
 *
 * Kept separate from `lib/api.ts` and `lib/format.ts` so the
 * `JobProgressPanel` + `JobCard` running chip + any future
 * surface can reuse the same logic, and so the helpers can be
 * unit-tested independently without mocking fetch.
 */

import type { JobStage, JobSummary } from "./api";

/** Stable ordered list of stages Recap writes to `job.json`.
 *
 *  Core Phase-1 stages come first in the order `recap run`
 *  executes them; opt-in stages are ordered as they'd fire in
 *  the rich-report chain. If a stage isn't present in
 *  `job.stages`, it's simply skipped — the frontend never needs
 *  to know every stage exists.
 */
export const KNOWN_STAGE_ORDER = [
  "ingest",
  "normalize",
  "transcribe",
  "assemble",
  "scenes",
  "dedupe",
  "window",
  "similarity",
  "chapters",
  "rank",
  "shortlist",
  "verify",
  "insights",
  "export_html",
  "export_docx",
] as const;

const STAGE_LABELS: Record<string, string> = {
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

export function prettyStageName(name: string): string {
  if (STAGE_LABELS[name]) return STAGE_LABELS[name];
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function stringField(stage: JobStage, key: string): string | null {
  const raw = (stage as Record<string, unknown>)[key];
  if (typeof raw !== "string" || !raw.trim()) return null;
  return raw;
}

function numberField(stage: JobStage, key: string): number | null {
  const raw = (stage as Record<string, unknown>)[key];
  if (typeof raw !== "number" || !Number.isFinite(raw)) return null;
  return raw;
}

export type NormalizeExtras = {
  command_mode: string | null;
  phase: string | null;
  percent: number | null;
  elapsed_seconds: number | null;
  output_bytes: number | null;
  input_duration_seconds: number | null;
};

export function readNormalizeExtras(stage: JobStage | undefined): NormalizeExtras {
  if (!stage || typeof stage !== "object") {
    return {
      command_mode: null,
      phase: null,
      percent: null,
      elapsed_seconds: null,
      output_bytes: null,
      input_duration_seconds: null,
    };
  }
  return {
    command_mode: stringField(stage, "command_mode"),
    phase: stringField(stage, "phase"),
    percent: numberField(stage, "percent"),
    elapsed_seconds: numberField(stage, "elapsed_seconds"),
    output_bytes: numberField(stage, "output_bytes"),
    input_duration_seconds: numberField(stage, "input_duration_seconds"),
  };
}

export type StageSlot = {
  name: string;
  label: string;
  status: string;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  raw: JobStage;
};

function orderStageNames(stages: Record<string, JobStage>): string[] {
  const present = new Set(Object.keys(stages || {}));
  const ordered: string[] = [];
  for (const name of KNOWN_STAGE_ORDER) {
    if (present.has(name)) {
      ordered.push(name);
      present.delete(name);
    }
  }
  // Any unknown-to-us stages append in stable alphabetical order.
  for (const name of Array.from(present).sort()) {
    ordered.push(name);
  }
  return ordered;
}

export function stageSlots(stages: Record<string, JobStage>): StageSlot[] {
  return orderStageNames(stages).map((name) => {
    const raw = stages[name] || {};
    return {
      name,
      label: prettyStageName(name),
      status:
        typeof raw.status === "string" && raw.status ? raw.status : "pending",
      startedAt: stringField(raw, "started_at"),
      finishedAt: stringField(raw, "finished_at"),
      error: stringField(raw, "error"),
      raw,
    };
  });
}

export type ProgressSnapshot = {
  /** Overall roll-up: `running`, `completed`, `failed`, or `pending`. */
  overallStatus: "running" | "completed" | "failed" | "pending";
  /** First stage whose status is `running`, if any. */
  currentStage: StageSlot | null;
  /** First stage whose status is `failed`, if any. Takes priority
   *  for the failure banner. */
  failedStage: StageSlot | null;
  /** All stages present in `job.stages`, in canonical order. */
  slots: StageSlot[];
  /** Count of stages in a `completed` state. */
  completedCount: number;
  /** Count of stages in a `failed` state. */
  failedCount: number;
  /** Total stage count present in the summary. */
  totalCount: number;
  /** Normalize extras, if the normalize stage carries any. */
  normalize: NormalizeExtras;
  /** Seconds since the currently-running stage's `started_at`, or
   *  `null` when no stage is running or we can't parse the time. */
  runningElapsedSeconds: number | null;
};

function computeRunningElapsedSeconds(
  startedAt: string | null,
  now: number,
): number | null {
  if (!startedAt) return null;
  const parsed = Date.parse(startedAt);
  if (!Number.isFinite(parsed)) return null;
  const delta = (now - parsed) / 1000;
  return delta > 0 ? delta : 0;
}

/**
 * Derive the entire live-progress snapshot from a job summary.
 *
 * `now` is injected so tests can render against a fixed clock
 * and so render cycles stay deterministic per tick. Callers
 * typically pass `Date.now()`.
 */
export function summarizeJobProgress(
  job: JobSummary | null | undefined,
  now: number = Date.now(),
): ProgressSnapshot {
  const stages = (job?.stages || {}) as Record<string, JobStage>;
  const slots = stageSlots(stages);
  const completedCount = slots.filter((s) => s.status === "completed").length;
  const failedCount = slots.filter((s) => s.status === "failed").length;
  const currentStage = slots.find((s) => s.status === "running") ?? null;
  const failedStage = slots.find((s) => s.status === "failed") ?? null;
  const normalize = readNormalizeExtras(stages["normalize"]);
  const rawStatus =
    typeof job?.status === "string" ? job.status.toLowerCase() : "";
  let overallStatus: ProgressSnapshot["overallStatus"] = "pending";
  if (rawStatus === "failed" || failedStage) {
    overallStatus = "failed";
  } else if (rawStatus === "running" || currentStage) {
    overallStatus = "running";
  } else if (rawStatus === "completed") {
    overallStatus = "completed";
  }
  return {
    overallStatus,
    currentStage,
    failedStage,
    slots,
    completedCount,
    failedCount,
    totalCount: slots.length,
    normalize,
    runningElapsedSeconds: currentStage
      ? computeRunningElapsedSeconds(currentStage.startedAt, now)
      : null,
  };
}

/** True when the job is still progressing and the UI should poll. */
export function isJobActive(job: JobSummary | null | undefined): boolean {
  const snap = summarizeJobProgress(job);
  return snap.overallStatus === "running";
}

/** Running-summary string for compact surfaces (library card). */
export function runningSummary(snap: ProgressSnapshot): string | null {
  if (snap.overallStatus !== "running") return null;
  if (!snap.currentStage) return "Running…";
  const label = snap.currentStage.label;
  const n = snap.completedCount;
  const m = snap.totalCount;
  const pct = snap.normalize.percent;
  if (
    snap.currentStage.name === "normalize" &&
    typeof pct === "number" &&
    Number.isFinite(pct)
  ) {
    return `${label} · ${Math.round(pct)}%`;
  }
  if (m > 0) {
    return `${label} · ${n}/${m}`;
  }
  return label;
}
