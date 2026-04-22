import { describe, expect, it } from "vitest";
import type { JobSummary } from "../lib/api";
import {
  isJobActive,
  runningSummary,
  stageSlots,
  summarizeJobProgress,
} from "../lib/progress";

function baseJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job_a",
    original_filename: "demo.mp4",
    created_at: "2026-04-20T10:00:00Z",
    updated_at: "2026-04-20T10:05:00Z",
    status: "pending",
    error: null,
    stages: {},
    artifacts: {},
    urls: {} as JobSummary["urls"],
    ...overrides,
  };
}

describe("lib/progress", () => {
  it("orders stages by the known pipeline order", () => {
    const slots = stageSlots({
      assemble: { status: "pending" },
      ingest: { status: "completed" },
      custom_late_stage: { status: "running" },
      normalize: { status: "running" },
    });
    expect(slots.map((s) => s.name)).toEqual([
      "ingest",
      "normalize",
      "assemble",
      "custom_late_stage",
    ]);
    expect(slots.map((s) => s.label)).toEqual([
      "Ingest",
      "Normalize",
      "Assemble",
      "Custom Late Stage",
    ]);
  });

  it("identifies the currently running stage and completed count", () => {
    const snap = summarizeJobProgress(
      baseJob({
        status: "running",
        stages: {
          ingest: {
            status: "completed",
            finished_at: "2026-04-20T10:01:00Z",
          },
          normalize: {
            status: "running",
            started_at: "2026-04-20T10:01:30Z",
            command_mode: "remux",
            percent: 42,
            output_bytes: 12345678,
            phase: "analysis",
          },
          transcribe: { status: "pending" },
          assemble: { status: "pending" },
        },
      }),
      Date.parse("2026-04-20T10:02:00Z"),
    );
    expect(snap.overallStatus).toBe("running");
    expect(snap.currentStage?.name).toBe("normalize");
    expect(snap.completedCount).toBe(1);
    expect(snap.totalCount).toBe(4);
    expect(snap.normalize.command_mode).toBe("remux");
    expect(snap.normalize.percent).toBe(42);
    expect(snap.normalize.output_bytes).toBe(12345678);
    expect(snap.runningElapsedSeconds).toBe(30);
    expect(isJobActive(snap as unknown as JobSummary)).toBe(false); // sanity
    // runningSummary formats normalize specially via percent.
    expect(runningSummary(snap)).toBe("Normalize · 42%");
  });

  it("falls back to stage · N/M when the current stage has no percent", () => {
    const snap = summarizeJobProgress(
      baseJob({
        status: "running",
        stages: {
          ingest: { status: "completed" },
          normalize: { status: "completed" },
          transcribe: {
            status: "running",
            started_at: "2026-04-20T10:02:00Z",
          },
          assemble: { status: "pending" },
        },
      }),
      Date.parse("2026-04-20T10:03:10Z"),
    );
    expect(snap.currentStage?.name).toBe("transcribe");
    expect(runningSummary(snap)).toBe("Transcribe · 2/4");
  });

  it("prefers failed over running for overallStatus", () => {
    const snap = summarizeJobProgress(
      baseJob({
        status: "running",
        stages: {
          ingest: { status: "completed" },
          normalize: {
            status: "failed",
            error: "ffmpeg stalled: no output growth",
          },
          transcribe: { status: "running" },
        },
      }),
    );
    expect(snap.overallStatus).toBe("failed");
    expect(snap.failedStage?.name).toBe("normalize");
    expect(snap.failedStage?.error).toContain("ffmpeg stalled");
    expect(runningSummary(snap)).toBeNull();
  });

  it("treats a completed job as terminal with no running chip", () => {
    const job = baseJob({
      status: "completed",
      stages: {
        ingest: { status: "completed" },
        normalize: { status: "completed" },
        transcribe: { status: "completed" },
        assemble: { status: "completed" },
      },
    });
    const snap = summarizeJobProgress(job);
    expect(snap.overallStatus).toBe("completed");
    expect(snap.currentStage).toBeNull();
    expect(snap.failedStage).toBeNull();
    expect(snap.completedCount).toBe(4);
    expect(runningSummary(snap)).toBeNull();
    expect(isJobActive(job)).toBe(false);
  });

  it("isJobActive returns true only while running and no stage failed", () => {
    const running = baseJob({
      status: "running",
      stages: { ingest: { status: "running" } },
    });
    const completed = baseJob({
      status: "completed",
      stages: { ingest: { status: "completed" } },
    });
    const failed = baseJob({
      status: "failed",
      stages: { ingest: { status: "failed", error: "boom" } },
    });
    expect(isJobActive(running)).toBe(true);
    expect(isJobActive(completed)).toBe(false);
    expect(isJobActive(failed)).toBe(false);
    expect(isJobActive(null)).toBe(false);
    expect(isJobActive(undefined)).toBe(false);
  });
});
