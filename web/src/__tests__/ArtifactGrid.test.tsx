import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ArtifactGrid from "../components/ArtifactGrid";
import type { JobSummary } from "../lib/api";

function makeJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job_a",
    original_filename: "demo.mp4",
    created_at: "2026-04-20T10:00:00Z",
    updated_at: "2026-04-20T10:05:00Z",
    status: "completed",
    error: null,
    stages: {},
    artifacts: {
      transcript_json: true,
      analysis_mp4: true,
      report_md: true,
      report_html: false,
      report_docx: false,
      insights_json: true,
      speaker_names_json: false,
      chapter_candidates_json: true,
      selected_frames_json: false,
    },
    urls: {
      analysis_mp4: "/job/job_a/analysis.mp4",
      transcript: "/api/jobs/job_a/transcript",
      speaker_names: "/api/jobs/job_a/speaker-names",
      report_md: "/job/job_a/report.md",
      report_html: "/job/job_a/report.html",
      report_docx: "/job/job_a/report.docx",
      insights_json: "/job/job_a/insights.json",
    } as unknown as JobSummary["urls"],
    ...overrides,
  };
}

describe("ArtifactGrid", () => {
  it("offers open links for artifacts that exist and a missing label otherwise", () => {
    render(<ArtifactGrid job={makeJob()} />);

    const mdLink = screen.getByRole("link", { name: "Open report.md" });
    expect(mdLink).toHaveAttribute("href", "/job/job_a/report.md");

    const insightsLink = screen.getByRole("link", {
      name: "Open insights.json",
    });
    expect(insightsLink).toHaveAttribute("href", "/job/job_a/insights.json");

    // Missing artifacts get a "Not generated yet" status chip instead
    // of a disabled link — the DOCX is not present in this fixture.
    const missingChips = screen.getAllByText("Not generated yet");
    expect(missingChips.length).toBeGreaterThan(0);
  });

  it("reports how many artifacts are present vs total", () => {
    render(<ArtifactGrid job={makeJob()} />);
    // 9 defined artifacts: 5 present in fixture, 4 missing.
    expect(screen.getByText(/5 of 9 present/)).toBeInTheDocument();
  });

  it("synthesizes a fallback URL for chapter_candidates when no explicit url is given", () => {
    const job = makeJob();
    // Force chapter_candidates_json to render as present so we can
    // assert the synthesized url path.
    render(<ArtifactGrid job={job} />);
    const cc = screen.getByRole("heading", { name: "Chapter candidates" });
    const tile = cc.closest(".artifact-tile");
    expect(tile).not.toBeNull();
    const link = tile?.querySelector("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).toBe(
      "/job/job_a/chapter_candidates.json",
    );
  });
});
