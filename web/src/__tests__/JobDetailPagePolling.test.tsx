import { act, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobDetailPage from "../pages/JobDetailPage";
import type { JobSummary } from "../lib/api";

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
      transcribe: { status: "completed" },
      assemble: { status: "completed" },
    },
    artifacts: {
      transcript_json: true,
      analysis_mp4: true,
      report_md: true,
    },
    urls: {
      analysis_mp4: "/job/job_a/analysis.mp4",
      transcript: "/api/jobs/job_a/transcript",
      speaker_names: "/api/jobs/job_a/speaker-names",
      legacy_detail: "/job/job_a/",
    } as JobSummary["urls"],
    ...overrides,
  };
}

type FetchImpl = (input: RequestInfo | URL) => Promise<Response>;
function installFetch(impl: FetchImpl) {
  globalThis.fetch = vi.fn(impl) as typeof fetch;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** Drain microtasks so pending fetch promises resolve after the
 *  fake timer advances. `act()` flushes React state updates. */
async function flushMicrotasks() {
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

describe("JobDetailPage live polling", () => {
  const originalFetch = globalThis.fetch;
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("stops polling /api/jobs/:id once the summary is completed", async () => {
    const jobFetches: number[] = [];
    installFetch((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs/job_a")) {
        jobFetches.push(Date.now());
        return Promise.resolve(jsonResponse(sampleJob()));
      }
      if (url.endsWith("/api/jobs/job_a/insights")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              error: "insights.json missing",
              reason: "no-insights",
            }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.endsWith("/api/jobs/job_a/chapters")) {
        return Promise.resolve(
          jsonResponse({
            chapters: [],
            overlay: { titles: {}, updated_at: null, path: null },
            sources: {
              chapter_candidates: false,
              insights: false,
              overlay: false,
            },
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    renderAt("/job/job_a");
    // Let mount effects + initial fetches resolve.
    await flushMicrotasks();
    expect(jobFetches.length).toBe(1);

    // Advance ~10 seconds; a running job would produce ~4 extra
    // ticks. A completed snapshot must stay at the mount fetch.
    for (let i = 0; i < 5; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500);
      });
      await flushMicrotasks();
    }
    expect(jobFetches.length).toBe(1);
  });

  it("polls /api/jobs/:id while the job is still running", async () => {
    const runningJob = sampleJob({
      status: "running",
      stages: {
        ingest: { status: "completed" },
        normalize: {
          status: "running",
          started_at: "2026-04-20T10:01:00Z",
          command_mode: "reencode",
          percent: 15,
        },
        transcribe: { status: "pending" },
        assemble: { status: "pending" },
      },
    });
    const jobFetches: number[] = [];
    let currentJob: JobSummary = runningJob;
    installFetch((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/jobs/job_a")) {
        jobFetches.push(Date.now());
        return Promise.resolve(jsonResponse(currentJob));
      }
      if (url.endsWith("/api/jobs/job_a/insights")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              error: "insights.json missing",
              reason: "no-insights",
            }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.endsWith("/api/jobs/job_a/chapters")) {
        return Promise.resolve(
          jsonResponse({
            chapters: [],
            overlay: { titles: {}, updated_at: null, path: null },
            sources: {
              chapter_candidates: false,
              insights: false,
              overlay: false,
            },
          }),
        );
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });

    renderAt("/job/job_a");
    await flushMicrotasks();
    expect(jobFetches.length).toBe(1);

    // Three poll intervals while the job is running.
    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2500);
      });
      await flushMicrotasks();
    }
    expect(jobFetches.length).toBeGreaterThanOrEqual(4);

    // Flip to completed — the next tick fetches one last time,
    // observes the terminal state, and the interval is torn down.
    currentJob = sampleJob();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    await flushMicrotasks();
    const countAfterFlip = jobFetches.length;

    // Advance 10 s more; no further fetches should land.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    await flushMicrotasks();
    expect(jobFetches.length).toBe(countAfterFlip);
  });
});
