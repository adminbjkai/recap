import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import NewJobPage from "../pages/NewJobPage";

type Handler = (
  url: string,
  init?: RequestInit,
) => Promise<Response> | Response;

function installFetch(handler: Handler) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    return handler(url, init);
  }) as typeof fetch;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderWithRoutes() {
  return render(
    <MemoryRouter initialEntries={["/new"]}>
      <Routes>
        <Route path="/new" element={<NewJobPage />} />
        <Route
          path="/job/:id"
          element={<div data-testid="dashboard-route" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("NewJobPage", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("shows a loading state before data arrives", () => {
    installFetch(
      () =>
        new Promise<Response>(() => {
          // Never resolve so we stay in loading.
        }),
    );
    renderWithRoutes();
    expect(screen.getByText(/loading sources and engines/i)).toBeInTheDocument();
  });

  it("renders sources and lets the user pick one", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/sources")) {
        return jsonResponse({
          sources_root: "/tmp/sources",
          sources_root_exists: true,
          extensions: [".mp4"],
          sources: [
            {
              name: "demo.mp4",
              size_bytes: 12_345_678,
              modified_at: "2026-04-19T10:00:00Z",
            },
            {
              name: "other.mp4",
              size_bytes: 4_000_000,
              modified_at: "2026-04-18T09:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/api/engines")) {
        return jsonResponse({
          engines: [
            {
              id: "faster-whisper",
              label: "faster-whisper (default, local)",
              category: "local",
              default: true,
              available: true,
              note: "Runs locally.",
            },
            {
              id: "deepgram",
              label: "deepgram (cloud)",
              category: "cloud",
              default: false,
              available: true,
              note: "Key detected.",
            },
          ],
          default: "faster-whisper",
        });
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    renderWithRoutes();

    expect(await screen.findByText("demo.mp4")).toBeInTheDocument();
    expect(screen.getByText("other.mp4")).toBeInTheDocument();

    const firstRadio = screen.getByRole("radio", {
      name: /demo\.mp4/,
    }) as HTMLInputElement;
    expect(firstRadio.checked).toBe(true);

    const second = screen.getByRole("radio", {
      name: /other\.mp4/,
    });
    await user.click(second);
    expect((second as HTMLInputElement).checked).toBe(true);
  });

  it("disables the Deepgram engine when the server reports it unavailable", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/sources")) {
        return jsonResponse({
          sources_root: "/tmp/sources",
          sources_root_exists: true,
          extensions: [".mp4"],
          sources: [
            {
              name: "demo.mp4",
              size_bytes: 100,
              modified_at: "2026-04-19T10:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/api/engines")) {
        return jsonResponse({
          engines: [
            {
              id: "faster-whisper",
              label: "faster-whisper (default, local)",
              category: "local",
              default: true,
              available: true,
              note: "Runs locally.",
            },
            {
              id: "deepgram",
              label: "deepgram (cloud)",
              category: "cloud",
              default: false,
              available: false,
              note: "Set DEEPGRAM_API_KEY to enable.",
            },
          ],
          default: "faster-whisper",
        });
      }
      return new Response("{}", { status: 404 });
    });

    renderWithRoutes();
    await screen.findByText("demo.mp4");
    const deepgramRadio = screen.getByRole("radio", {
      name: /deepgram/i,
    }) as HTMLInputElement;
    expect(deepgramRadio.disabled).toBe(true);
    expect(
      screen.getByText(/set deepgram_api_key to enable/i),
    ).toBeInTheDocument();
  });

  it("starts a job and redirects to the React dashboard on success", async () => {
    const startCalls: RequestInit[] = [];
    installFetch((url, init) => {
      if (url.endsWith("/api/sources")) {
        return jsonResponse({
          sources_root: "/tmp/sources",
          sources_root_exists: true,
          extensions: [".mp4"],
          sources: [
            {
              name: "demo.mp4",
              size_bytes: 100,
              modified_at: "2026-04-19T10:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/api/engines")) {
        return jsonResponse({
          engines: [
            {
              id: "faster-whisper",
              label: "faster-whisper (default, local)",
              category: "local",
              default: true,
              available: true,
            },
          ],
          default: "faster-whisper",
        });
      }
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "test-token" });
      }
      if (url.endsWith("/api/jobs/start")) {
        startCalls.push(init || {});
        return jsonResponse(
          {
            job_id: "stub-42",
            engine: "faster-whisper",
            react_detail: "/app/job/stub-42",
            legacy_detail: "/job/stub-42/",
            started_at: "2026-04-20T00:00:00Z",
            stub: true,
          },
          202,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    renderWithRoutes();
    await screen.findByText("demo.mp4");
    await user.click(screen.getByRole("button", { name: /start job/i }));

    await waitFor(() => {
      expect(screen.getByTestId("dashboard-route")).toBeInTheDocument();
    });

    expect(startCalls).toHaveLength(1);
    const headers = (startCalls[0].headers || {}) as Record<string, string>;
    expect(headers["X-Recap-Token"]).toBe("test-token");
    const body = JSON.parse((startCalls[0].body as string) || "{}");
    expect(body).toEqual({
      source: { kind: "sources-root", name: "demo.mp4" },
      engine: "faster-whisper",
    });
  });

  it("renders the server-provided error when /api/jobs/start rejects", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/sources")) {
        return jsonResponse({
          sources_root: "/tmp/sources",
          sources_root_exists: true,
          extensions: [".mp4"],
          sources: [
            {
              name: "demo.mp4",
              size_bytes: 100,
              modified_at: "2026-04-19T10:00:00Z",
            },
          ],
        });
      }
      if (url.endsWith("/api/engines")) {
        return jsonResponse({
          engines: [
            {
              id: "faster-whisper",
              label: "faster-whisper (default, local)",
              category: "local",
              default: true,
              available: true,
            },
          ],
          default: "faster-whisper",
        });
      }
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "test-token" });
      }
      if (url.endsWith("/api/jobs/start")) {
        return jsonResponse(
          { error: "ingest failed: broken pipe", reason: "ingest-failed" },
          400,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    renderWithRoutes();
    await screen.findByText("demo.mp4");
    await user.click(screen.getByRole("button", { name: /start job/i }));

    expect(
      await screen.findByText(/ingest failed: broken pipe/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("dashboard-route")).not.toBeInTheDocument();
  });
});
