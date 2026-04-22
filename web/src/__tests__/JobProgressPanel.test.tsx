import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import JobProgressPanel from "../components/JobProgressPanel";
import type { JobSummary } from "../lib/api";

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

describe("JobProgressPanel", () => {
  it("renders the running card with normalize extras + progress bar", () => {
    const job = baseJob({
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
          output_bytes: 4 * 1024 * 1024,
          phase: "analysis",
          input_duration_seconds: 600,
        },
        transcribe: { status: "pending" },
        assemble: { status: "pending" },
      },
    });
    render(
      <JobProgressPanel
        job={job}
        now={Date.parse("2026-04-20T10:02:00Z")}
      />,
    );
    // Heading stage name (also appears in the stage-pill list).
    const stageLabels = screen.getAllByText("Normalize");
    expect(stageLabels.length).toBeGreaterThanOrEqual(1);
    // Completed / total.
    expect(screen.getByText("1 / 4 done")).toBeInTheDocument();
    // Normalize command_mode.
    expect(screen.getByText("remux")).toBeInTheDocument();
    // Percent readout.
    expect(screen.getByText(/^42%/)).toBeInTheDocument();
    // Output bytes as a file-size.
    expect(screen.getByText(/^4\.0 MB$/)).toBeInTheDocument();
    // Elapsed seconds since started_at (30 s exactly).
    expect(screen.getByText("30.0 s")).toBeInTheDocument();
    // Progress bar has the correct aria-valuenow.
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "42");
  });

  it("renders the compact completed card once the job is done", () => {
    const job = baseJob({
      status: "completed",
      stages: {
        ingest: { status: "completed" },
        normalize: { status: "completed" },
        transcribe: { status: "completed" },
        assemble: { status: "completed" },
      },
    });
    render(<JobProgressPanel job={job} />);
    expect(
      screen.getByText(/Completed · 4 \/ 4 stages/),
    ).toBeInTheDocument();
    // No progress bar once completed.
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("renders a failed banner naming the failed stage + error", () => {
    const job = baseJob({
      status: "failed",
      error:
        "normalize: ffmpeg stalled: no output growth or stderr activity for 90s",
      stages: {
        ingest: { status: "completed" },
        normalize: {
          status: "failed",
          error:
            "ffmpeg stalled: no output growth or stderr activity for 90s",
        },
      },
    });
    render(<JobProgressPanel job={job} />);
    expect(
      screen.getByText(/Failed · Normalize/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /ffmpeg stalled: no output growth or stderr activity for 90s/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("renders a neutral pending line when no stage has started", () => {
    const job = baseJob({
      status: "pending",
      stages: {},
    });
    render(<JobProgressPanel job={job} />);
    expect(screen.getByText(/Waiting to start/)).toBeInTheDocument();
  });
});
