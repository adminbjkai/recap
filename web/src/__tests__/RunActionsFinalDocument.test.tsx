import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RunActionsPanel from "../components/RunActionsPanel";
import type {
  InsightsRunStatus,
  RichReportRunStatus,
} from "../lib/api";

type FetchHandler = (
  url: string,
  init?: RequestInit,
) => Promise<Response> | Response;

function installFetch(handler: FetchHandler) {
  globalThis.fetch = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      return handler(url, init);
    },
  ) as typeof fetch;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const noRunInsights: InsightsRunStatus = {
  job_id: "job_a",
  run_type: "insights",
  status: "no-run",
};

const noRunRich: RichReportRunStatus = {
  job_id: "job_a",
  run_type: "rich-report",
  status: "no-run",
};

describe("RunActionsPanel default provider + final-document chain", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("picks up Groq as the default when /api/insights-providers reports it", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/insights-providers")) {
        return jsonResponse({
          providers: [
            {
              id: "groq",
              label: "Groq",
              category: "cloud",
              available: true,
            },
            {
              id: "mock",
              label: "Mock",
              category: "local",
              available: true,
            },
          ],
          default: "groq",
        });
      }
      if (url.endsWith("/runs/insights/last")) {
        return jsonResponse(noRunInsights);
      }
      if (url.endsWith("/runs/rich-report/last")) {
        return jsonResponse(noRunRich);
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <RunActionsPanel jobId="job_a" insightsPresent={false} />,
    );

    // The final-document blurb names the default provider in bold.
    await waitFor(() => {
      expect(
        screen.getAllByText(/Groq/i).length,
      ).toBeGreaterThan(0);
    });
    // The combobox inside the Advanced disclosure should also
    // preselect "groq" (since the panel read default="groq").
    const combo = screen.getByRole("combobox") as HTMLSelectElement;
    expect(combo.value).toBe("groq");
  });

  it("falls back to Mock default when Groq is unavailable", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/insights-providers")) {
        return jsonResponse({
          providers: [
            {
              id: "groq",
              label: "Groq",
              category: "cloud",
              available: false,
            },
            {
              id: "mock",
              label: "Mock",
              category: "local",
              available: true,
            },
          ],
          default: "mock",
        });
      }
      if (url.endsWith("/runs/insights/last")) {
        return jsonResponse(noRunInsights);
      }
      if (url.endsWith("/runs/rich-report/last")) {
        return jsonResponse(noRunRich);
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <RunActionsPanel jobId="job_a" insightsPresent={false} />,
    );

    await waitFor(() => {
      const combo = screen.getByRole("combobox") as HTMLSelectElement;
      expect(combo.value).toBe("mock");
    });
  });

  it("exposes the Advanced disclosure as collapsed by default", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/insights-providers")) {
        return jsonResponse({
          providers: [
            {
              id: "groq",
              label: "Groq",
              category: "cloud",
              available: false,
            },
            {
              id: "mock",
              label: "Mock",
              category: "local",
              available: true,
            },
          ],
          default: "mock",
        });
      }
      if (url.endsWith("/runs/insights/last")) {
        return jsonResponse(noRunInsights);
      }
      if (url.endsWith("/runs/rich-report/last")) {
        return jsonResponse(noRunRich);
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <RunActionsPanel jobId="job_a" insightsPresent={false} />,
    );

    await waitFor(() => {
      // The Advanced <details> element must exist and start closed
      // so the primary "Generate final document" CTA is the only
      // action visible on first paint.
      const details = document.querySelector<HTMLDetailsElement>(
        "details.advanced-disclosure",
      );
      expect(details).toBeTruthy();
      expect(details!.open).toBe(false);
    });
    // "Advanced" label should still be visible in the summary.
    expect(screen.getByText(/^Advanced$/)).toBeInTheDocument();
  });

  it("chains insights → rich-report when 'Generate final document' is clicked", async () => {
    const insightsPosts: RequestInit[] = [];
    const richPosts: RequestInit[] = [];
    let insightsStatusPayload: InsightsRunStatus = noRunInsights;
    let richStatusPayload: RichReportRunStatus = noRunRich;
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "t" });
      }
      if (url.endsWith("/api/insights-providers")) {
        return jsonResponse({
          providers: [
            {
              id: "groq",
              label: "Groq",
              category: "cloud",
              available: false,
            },
            {
              id: "mock",
              label: "Mock",
              category: "local",
              available: true,
            },
          ],
          default: "mock",
        });
      }
      if (
        url.endsWith("/runs/insights/last") &&
        (!init || init.method !== "POST")
      ) {
        return jsonResponse(insightsStatusPayload);
      }
      if (
        url.endsWith("/runs/rich-report/last") &&
        (!init || init.method !== "POST")
      ) {
        return jsonResponse(richStatusPayload);
      }
      if (
        url.endsWith("/runs/insights") &&
        init &&
        init.method === "POST"
      ) {
        insightsPosts.push(init);
        // Advance insights to success immediately on the POST
        // response so the chain effect moves to rich-report on
        // the next tick.
        insightsStatusPayload = {
          job_id: "job_a",
          run_type: "insights",
          status: "success",
          exit_code: 0,
          provider: "mock",
          force: false,
          started_at: "2026-04-20T00:00:00Z",
          finished_at: "2026-04-20T00:00:01Z",
          elapsed: 1.2,
        };
        return jsonResponse(
          {
            job_id: "job_a",
            run_type: "insights",
            status_url: "/api/jobs/job_a/runs/insights/last",
            react_detail: "/app/job/job_a",
            started_at: "2026-04-20T00:00:00Z",
            provider: "mock",
            force: false,
            stub: true,
          },
          202,
        );
      }
      if (
        url.endsWith("/runs/rich-report") &&
        init &&
        init.method === "POST"
      ) {
        richPosts.push(init);
        richStatusPayload = {
          job_id: "job_a",
          run_type: "rich-report",
          status: "success",
          started_at: "2026-04-20T00:00:02Z",
          finished_at: "2026-04-20T00:00:05Z",
          elapsed: 3.0,
          current_stage: null,
          failed_stage: null,
          stages: [],
        };
        return jsonResponse(
          {
            job_id: "job_a",
            run_type: "rich-report",
            status_url: "/api/jobs/job_a/runs/rich-report/last",
            react_detail: "/app/job/job_a",
            started_at: "2026-04-20T00:00:02Z",
            stub: true,
          },
          202,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(
      <RunActionsPanel jobId="job_a" insightsPresent={false} />,
    );

    // Primary button appears once the insights-providers fetch lands.
    const primary = await screen.findByRole("button", {
      name: /generate final document/i,
    });
    await user.click(primary);

    // Chain should have posted insights first, then rich-report.
    await waitFor(() => {
      expect(insightsPosts).toHaveLength(1);
      expect(richPosts).toHaveLength(1);
    });

    // Insights POST used the default (mock) provider, force=false.
    const insightsBody = JSON.parse(
      (insightsPosts[0].body as string) || "{}",
    );
    expect(insightsBody).toEqual({ provider: "mock", force: false });

    // Success banner eventually shows.
    await waitFor(() => {
      expect(
        screen.getByText(/final document generated/i),
      ).toBeInTheDocument();
    });
  });
});
