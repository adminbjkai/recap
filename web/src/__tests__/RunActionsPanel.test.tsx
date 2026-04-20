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

describe("RunActionsPanel", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders the missing-insights generate state", async () => {
    installFetch((url) => {
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

    expect(
      await screen.findByRole("button", { name: /generate insights/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /generate rich report/i }),
    ).toBeInTheDocument();
    // When insights.json is present the CTA label flips to "Regenerate".
    expect(
      screen.queryByRole("button", { name: /regenerate insights/i }),
    ).not.toBeInTheDocument();
  });

  it("switches CTA label to 'Regenerate insights' when insights are present", async () => {
    installFetch((url) => {
      if (url.endsWith("/runs/insights/last")) {
        return jsonResponse(noRunInsights);
      }
      if (url.endsWith("/runs/rich-report/last")) {
        return jsonResponse(noRunRich);
      }
      return new Response("{}", { status: 404 });
    });

    render(
      <RunActionsPanel jobId="job_a" insightsPresent={true} />,
    );

    expect(
      await screen.findByRole("button", {
        name: /regenerate insights/i,
      }),
    ).toBeInTheDocument();
  });

  it("starts an insights run and reflects in-progress, then success", async () => {
    const insightsCalls: RequestInit[] = [];
    let insightsStatusPayload: InsightsRunStatus = noRunInsights;
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "t" });
      }
      if (
        url.endsWith("/runs/insights/last") &&
        (!init || init.method !== "POST")
      ) {
        return jsonResponse(insightsStatusPayload);
      }
      if (url.endsWith("/runs/rich-report/last")) {
        return jsonResponse(noRunRich);
      }
      if (
        url.endsWith("/runs/insights") &&
        init &&
        init.method === "POST"
      ) {
        insightsCalls.push(init);
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
      return new Response("{}", { status: 404 });
    });

    const onRunCompleted = vi.fn();
    const user = userEvent.setup();
    render(
      <RunActionsPanel
        jobId="job_a"
        insightsPresent={false}
        onRunCompleted={onRunCompleted}
      />,
    );

    const btn = await screen.findByRole("button", {
      name: /generate insights/i,
    });
    await user.click(btn);

    expect(insightsCalls).toHaveLength(1);
    const headers = (insightsCalls[0].headers || {}) as Record<
      string,
      string
    >;
    expect(headers["X-Recap-Token"]).toBe("t");
    const body = JSON.parse((insightsCalls[0].body as string) || "{}");
    expect(body).toEqual({ provider: "mock", force: false });

    await waitFor(() => {
      expect(onRunCompleted).toHaveBeenCalledWith("insights");
    });
  });

  it("surfaces a server error when the insights POST is rejected", async () => {
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) return jsonResponse({ token: "t" });
      if (
        url.endsWith("/runs/insights/last") &&
        (!init || init.method !== "POST")
      ) {
        return jsonResponse(noRunInsights);
      }
      if (url.endsWith("/runs/rich-report/last")) {
        return jsonResponse(noRunRich);
      }
      if (
        url.endsWith("/runs/insights") &&
        init &&
        init.method === "POST"
      ) {
        return jsonResponse(
          {
            error: "Groq requires GROQ_API_KEY in the server's environment.",
            reason: "groq-unavailable",
          },
          400,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(<RunActionsPanel jobId="job_a" insightsPresent={false} />);

    await screen.findByRole("button", { name: /generate insights/i });
    const select = screen.getByRole("combobox");
    await user.selectOptions(select, "groq");
    await user.click(
      screen.getByRole("button", { name: /generate insights/i }),
    );

    expect(
      await screen.findByText(/groq requires groq_api_key/i),
    ).toBeInTheDocument();
  });

  it("renders a failed insights run with bounded stderr", async () => {
    const failed: InsightsRunStatus = {
      job_id: "job_a",
      run_type: "insights",
      status: "failure",
      exit_code: 1,
      provider: "mock",
      force: true,
      started_at: "2026-04-20T00:00:00Z",
      finished_at: "2026-04-20T00:00:02Z",
      elapsed: 2.0,
      stdout: "",
      stderr: "recap insights failed: no transcript",
    };
    installFetch((url) => {
      if (url.endsWith("/runs/insights/last")) return jsonResponse(failed);
      if (url.endsWith("/runs/rich-report/last")) return jsonResponse(noRunRich);
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(<RunActionsPanel jobId="job_a" insightsPresent={false} />);

    await screen.findByText(/last run failed/i);
    const details = screen.getByText(/show stderr/i);
    await user.click(details);
    expect(
      await screen.findByText(/recap insights failed: no transcript/i),
    ).toBeInTheDocument();
  });

  it("renders the rich-report stage list in order", async () => {
    const stages = [
      "scenes",
      "dedupe",
      "window",
      "similarity",
      "chapters",
      "rank",
      "shortlist",
      "verify",
      "assemble",
      "export-html",
      "export-docx",
    ];
    const rich: RichReportRunStatus = {
      job_id: "job_a",
      run_type: "rich-report",
      status: "success",
      started_at: "2026-04-20T00:00:00Z",
      finished_at: "2026-04-20T00:05:00Z",
      elapsed: 300,
      current_stage: null,
      failed_stage: null,
      stages: stages.map((name) => ({
        name,
        status: "completed",
        exit_code: 0,
        stdout: "",
        stderr: "",
        elapsed: 1.0,
      })),
    };
    installFetch((url) => {
      if (url.endsWith("/runs/insights/last")) return jsonResponse(noRunInsights);
      if (url.endsWith("/runs/rich-report/last")) return jsonResponse(rich);
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(<RunActionsPanel jobId="job_a" insightsPresent={false} />);

    const toggle = await screen.findByRole("button", {
      name: /show stage details/i,
    });
    await user.click(toggle);

    for (const name of stages) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    // List must render in chain order, not alphabetical.
    const items = screen.getAllByRole("listitem");
    const renderedNames = items.map(
      (li) => li.querySelector(".run-stage-name")?.textContent,
    );
    expect(renderedNames).toEqual(stages);
  });

  it("renders a failed rich-report stage with its stderr", async () => {
    const rich: RichReportRunStatus = {
      job_id: "job_a",
      run_type: "rich-report",
      status: "failure",
      started_at: "2026-04-20T00:00:00Z",
      finished_at: "2026-04-20T00:02:00Z",
      elapsed: 120,
      current_stage: null,
      failed_stage: "chapters",
      stages: [
        {
          name: "scenes",
          status: "completed",
          exit_code: 0,
          stdout: "",
          stderr: "",
          elapsed: 1.0,
        },
        {
          name: "chapters",
          status: "failed",
          exit_code: 1,
          stdout: "",
          stderr: "chapters failed: transcript missing",
          elapsed: 0.4,
        },
      ],
    };
    installFetch((url) => {
      if (url.endsWith("/runs/insights/last")) return jsonResponse(noRunInsights);
      if (url.endsWith("/runs/rich-report/last")) return jsonResponse(rich);
      return new Response("{}", { status: 404 });
    });

    render(<RunActionsPanel jobId="job_a" insightsPresent={false} />);
    expect(
      await screen.findByText(/rich report failed at stage: chapters/i),
    ).toBeInTheDocument();
  });
});
