import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobDetailPage from "../pages/JobDetailPage";
import type { InsightsDoc, JobSummary } from "../lib/api";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/job/:id" element={<JobDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function sampleJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job_a",
    original_filename: "demo.mp4",
    created_at: "2026-04-20T10:00:00Z",
    updated_at: "2026-04-20T10:05:00Z",
    status: "completed",
    error: null,
    stages: {
      ingest: { status: "completed" },
      normalize: { status: "completed" },
      transcribe: {
        status: "completed",
        engine: "deepgram",
        model: "nova-3",
        segments: 42,
      },
      assemble: { status: "completed" },
    },
    artifacts: {
      transcript_json: true,
      analysis_mp4: true,
      report_md: true,
      report_html: true,
      report_docx: false,
      insights_json: false,
      speaker_names_json: false,
      chapter_candidates_json: false,
      selected_frames_json: false,
    },
    urls: {
      analysis_mp4: "/job/job_a/analysis.mp4",
      transcript: "/api/jobs/job_a/transcript",
      speaker_names: "/api/jobs/job_a/speaker-names",
      detail_html: "/job/job_a/",
      legacy_detail: "/job/job_a/",
      react_detail: "/app/job/job_a",
      react_transcript: "/app/job/job_a/transcript",
      report_md: "/job/job_a/report.md",
      report_html: "/job/job_a/report.html",
      report_docx: "/job/job_a/report.docx",
      insights_json: "/job/job_a/insights.json",
      insights: "/api/jobs/job_a/insights",
    } as unknown as JobSummary["urls"],
    ...overrides,
  };
}

function sampleInsights(): InsightsDoc {
  return {
    version: 1,
    provider: "mock",
    model: "mock-v1",
    generated_at: "2026-04-20T10:06:00Z",
    sources: {
      transcript: "transcript.json",
      chapters: null,
      speaker_names: null,
      selected_frames: null,
    },
    overview: {
      title: "Demo recap",
      short_summary:
        "A short test summary that proves the preview card renders.",
      detailed_summary: "",
      quick_bullets: ["First bullet", "Second bullet"],
    },
    chapters: [
      {
        index: 1,
        start_seconds: 0,
        end_seconds: 30,
        title: "Intro",
        summary: "",
        bullets: [],
        action_items: [],
        speaker_focus: [],
      },
    ],
    action_items: [
      {
        text: "Ship the dashboard",
        chapter_index: 1,
        timestamp_seconds: 12,
        owner: null,
        due: null,
      },
    ],
  };
}

type FetchImpl = (input: RequestInfo | URL) => Promise<Response>;

function installFetch(impl: FetchImpl) {
  globalThis.fetch = vi.fn(impl) as typeof fetch;
}

describe("JobDetailPage", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("shows a loading skeleton while the job is being fetched", () => {
    let resolveJob: (value: Response) => void = () => {};
    installFetch((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs/job_a")) {
        return new Promise<Response>((resolve) => {
          resolveJob = resolve;
        });
      }
      if (url.endsWith("/api/jobs/job_a/insights")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ error: "insights.json missing", reason: "no-insights" }),
            {
              status: 404,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    renderAt("/job/job_a");
    expect(screen.getByText(/Loading job/i)).toBeInTheDocument();
    // let the hanging job promise resolve so the test cleans up.
    resolveJob(
      new Response(JSON.stringify(sampleJob()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("renders hero, timeline, artifacts, and the empty insights state when insights are absent", async () => {
    installFetch((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs/job_a")) {
        return Promise.resolve(
          new Response(JSON.stringify(sampleJob()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/jobs/job_a/insights")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              error: "insights.json missing",
              reason: "no-insights",
            }),
            {
              status: 404,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    renderAt("/job/job_a");

    expect(await screen.findByText("demo.mp4")).toBeInTheDocument();
    // Primary + transcript CTAs.
    const primary = screen.getByRole("link", {
      name: "Open transcript workspace",
    });
    expect(primary).toHaveAttribute("href", "/job/job_a/transcript");
    // Legacy detail link is a ghost button.
    expect(
      screen.getByRole("link", { name: "Legacy detail page" }),
    ).toHaveAttribute("href", "/job/job_a/");
    // Stage timeline.
    expect(
      screen.getByRole("heading", { name: "Ingest" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Transcribe" }),
    ).toBeInTheDocument();
    // Meta chips derived from stages / artifacts.
    expect(screen.getByText("Engine · deepgram")).toBeInTheDocument();
    expect(screen.getByText("42 segments")).toBeInTheDocument();
    // Empty insights state.
    expect(
      await screen.findByText("No structured insights yet"),
    ).toBeInTheDocument();
    // Artifact grid should be labeled.
    expect(
      screen.getByRole("region", { name: "Artifacts" }),
    ).toBeInTheDocument();
  });

  it("renders the insights preview when insights.json is available", async () => {
    installFetch((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs/job_a")) {
        return Promise.resolve(
          new Response(
            JSON.stringify(
              sampleJob({
                artifacts: {
                  ...sampleJob().artifacts,
                  insights_json: true,
                },
              }),
            ),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      if (url.endsWith("/api/jobs/job_a/insights")) {
        return Promise.resolve(
          new Response(JSON.stringify(sampleInsights()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    renderAt("/job/job_a");

    expect(await screen.findByText("demo.mp4")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Demo recap" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(
        "A short test summary that proves the preview card renders.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("First bullet")).toBeInTheDocument();
    expect(screen.getByText("Ship the dashboard")).toBeInTheDocument();
  });

  it("shows a clear error state when insights.json is malformed", async () => {
    installFetch((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs/job_a")) {
        return Promise.resolve(
          new Response(JSON.stringify(sampleJob()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.endsWith("/api/jobs/job_a/insights")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              error: "insights unreadable: ...",
              reason: "insights-unreadable",
            }),
            {
              status: 500,
              headers: { "Content-Type": "application/json" },
            },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    renderAt("/job/job_a");
    expect(
      await screen.findByText("Could not read insights.json"),
    ).toBeInTheDocument();
  });
});
