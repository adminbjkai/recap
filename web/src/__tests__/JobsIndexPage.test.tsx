import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobsIndexPage from "../pages/JobsIndexPage";
import JobCard from "../components/JobCard";
import type { JobSummary } from "../lib/api";

function makeJob(overrides: Partial<JobSummary>): JobSummary {
  return {
    job_id: "job_a",
    original_filename: "meeting.mov",
    created_at: "2026-04-17T10:00:00",
    updated_at: "2026-04-17T10:05:00",
    status: "completed",
    error: null,
    stages: {},
    artifacts: {
      transcript_json: true,
      analysis_mp4: true,
      report_md: true,
      report_html: false,
      report_docx: false,
      speaker_names_json: false,
    },
    urls: {
      analysis_mp4: "/job/job_a/analysis.mp4",
      transcript: "/api/jobs/job_a/transcript",
      speaker_names: "/api/jobs/job_a/speaker-names",
    } as JobSummary["urls"],
    ...overrides,
  };
}

const jobA = makeJob({});
const jobB = makeJob({
  job_id: "job_b",
  original_filename: "sprint_review.mp4",
  status: "failed",
  error: "transcribe failed",
});

describe("JobCard", () => {
  it("renders the job title, status, and a link to the transcript workspace", () => {
    render(
      <MemoryRouter>
        <JobCard job={jobA} />
      </MemoryRouter>,
    );
    expect(screen.getByText("meeting.mov")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open transcript workspace" });
    expect(link).toHaveAttribute("href", "/job/job_a/transcript");
  });

  it("shows the error message when a job failed", () => {
    render(
      <MemoryRouter>
        <JobCard job={jobB} />
      </MemoryRouter>,
    );
    expect(screen.getByText("transcribe failed")).toBeInTheDocument();
  });
});

describe("JobsIndexPage", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs")) {
        return new Response(
          JSON.stringify({ jobs: [jobA, jobB] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response("{}", { status: 404 });
    }) as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("lists jobs fetched from /api/jobs", async () => {
    render(
      <MemoryRouter>
        <JobsIndexPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("meeting.mov")).toBeInTheDocument();
    expect(screen.getByText("sprint_review.mp4")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2")).toBeInTheDocument();
  });

  it("filters by search term and by status pill", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <JobsIndexPage />
      </MemoryRouter>,
    );
    await screen.findByText("meeting.mov");

    await user.type(
      screen.getByPlaceholderText("Search by filename or job id"),
      "sprint",
    );
    await waitFor(() => {
      expect(screen.queryByText("meeting.mov")).not.toBeInTheDocument();
    });
    expect(screen.getByText("sprint_review.mp4")).toBeInTheDocument();

    await user.clear(
      screen.getByPlaceholderText("Search by filename or job id"),
    );
    await user.click(screen.getByRole("radio", { name: "Completed" }));
    await waitFor(() => {
      expect(screen.queryByText("sprint_review.mp4")).not.toBeInTheDocument();
    });
    expect(screen.getByText("meeting.mov")).toBeInTheDocument();
  });
});
