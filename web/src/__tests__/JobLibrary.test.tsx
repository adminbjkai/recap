import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobCard from "../components/JobCard";
import JobsIndexPage from "../pages/JobsIndexPage";
import type {
  JobMetadataPatch,
  JobSummary,
  LibrarySummary,
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

function makeJob(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job_a",
    original_filename: "meeting.mov",
    created_at: "2026-04-21T10:00:00Z",
    updated_at: "2026-04-21T10:05:00Z",
    status: "completed",
    error: null,
    stages: {},
    artifacts: {
      transcript_json: true,
      analysis_mp4: true,
      report_md: true,
      report_html: false,
      report_docx: false,
      insights_json: false,
      speaker_names_json: false,
      chapter_candidates_json: false,
      selected_frames_json: false,
    } as unknown as JobSummary["artifacts"],
    urls: {
      analysis_mp4: "/job/job_a/analysis.mp4",
      transcript: "/api/jobs/job_a/transcript",
      speaker_names: "/api/jobs/job_a/speaker-names",
    } as unknown as JobSummary["urls"],
    display_title: "meeting.mov",
    custom_title: null,
    project: null,
    archived: false,
    ...overrides,
  };
}

function makeLibrary(
  overrides: Partial<LibrarySummary> = {},
): LibrarySummary {
  return {
    version: 1,
    updated_at: null,
    sidecar_path: "/tmp/.recap_library.json",
    sidecar_present: false,
    counts: { total: 2, active: 2, archived: 0 },
    projects: [],
    ...overrides,
  };
}

describe("JobCard library organization", () => {
  it("renders the custom title, project chip, and renamed badge when set", () => {
    const job = makeJob({
      display_title: "Kickoff call",
      custom_title: "Kickoff call",
      project: "Client demos",
    });
    render(
      <MemoryRouter>
        <JobCard job={job} onSaveMetadata={async () => undefined} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Kickoff call")).toBeInTheDocument();
    expect(screen.getByText("Client demos")).toBeInTheDocument();
    expect(screen.getByText("renamed")).toBeInTheDocument();
    // Primary CTA still works.
    expect(
      screen.getByRole("link", { name: "Open job dashboard" }),
    ).toHaveAttribute("href", "/job/job_a");
  });

  it("shows archived badge + archive toggle label flip when archived", () => {
    const job = makeJob({ archived: true });
    render(
      <MemoryRouter>
        <JobCard job={job} onSaveMetadata={async () => undefined} />
      </MemoryRouter>,
    );
    expect(screen.getByText("archived")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /unarchive/i }),
    ).toBeInTheDocument();
  });

  it("opens an inline editor and posts title + project", async () => {
    const onSaveMetadata = vi.fn(async (_patch: JobMetadataPatch) =>
      undefined,
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <JobCard job={makeJob()} onSaveMetadata={onSaveMetadata} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    const titleInput = screen.getByRole("textbox", { name: /job title/i });
    await user.clear(titleInput);
    await user.type(titleInput, "Kickoff call");
    const projectInput = screen.getByRole("textbox", { name: /project/i });
    await user.type(projectInput, "Client demos");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => {
      expect(onSaveMetadata).toHaveBeenCalledTimes(1);
    });
    expect(onSaveMetadata.mock.calls[0][0]).toEqual({
      title: "Kickoff call",
      project: "Client demos",
    });
  });

  it("surfaces the server error when saving metadata fails", async () => {
    const onSaveMetadata = vi.fn(async () => {
      throw new Error("Title exceeds 120 characters.");
    });
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <JobCard job={makeJob()} onSaveMetadata={onSaveMetadata} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    expect(
      await screen.findByText(/title exceeds 120 characters/i),
    ).toBeInTheDocument();
  });
});

describe("JobsIndexPage library filters", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // nothing
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("filters by project and posts archive toggles via /api/jobs/<id>/metadata", async () => {
    const jobs = [
      makeJob({
        job_id: "job_a",
        original_filename: "kickoff.mov",
        display_title: "Kickoff call",
        custom_title: "Kickoff call",
        project: "Client demos",
      }),
      makeJob({
        job_id: "job_b",
        original_filename: "retro.mov",
        display_title: "retro.mov",
        project: "Engineering",
      }),
    ];
    const library = makeLibrary({
      sidecar_present: true,
      counts: { total: 2, active: 2, archived: 0 },
      projects: [
        { name: "Client demos", total: 1, active: 1, archived: 0 },
        { name: "Engineering", total: 1, active: 1, archived: 0 },
      ],
    });
    const posts: RequestInit[] = [];
    installFetch((url, init) => {
      if (url.endsWith("/api/library")) return jsonResponse(library);
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "tok" });
      }
      if (
        url.includes("/api/jobs/job_a/metadata") &&
        init?.method === "POST"
      ) {
        posts.push(init);
        return jsonResponse(
          {
            ...jobs[0],
            archived: true,
          },
          200,
        );
      }
      if (
        url.includes("/api/jobs") &&
        !url.includes("/api/jobs/") &&
        (!init || init.method !== "POST")
      ) {
        return jsonResponse({
          jobs,
          include_archived: url.includes("include_archived=1"),
        });
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <JobsIndexPage />
      </MemoryRouter>,
    );

    // Both jobs appear under the default "All projects" filter.
    expect(
      await screen.findByText("Kickoff call"),
    ).toBeInTheDocument();
    expect(screen.getByText("retro.mov")).toBeInTheDocument();

    // Filter by Engineering project.
    const projectSelect = screen.getByRole("combobox", {
      name: /project/i,
    });
    await user.selectOptions(projectSelect, "Engineering");

    await waitFor(() => {
      expect(screen.queryByText("Kickoff call")).not.toBeInTheDocument();
    });
    expect(screen.getByText("retro.mov")).toBeInTheDocument();

    // Reset filter and archive job_a via its card.
    await user.selectOptions(projectSelect, "__all__");
    await screen.findByText("Kickoff call");
    const kickoff = screen
      .getByText("Kickoff call")
      .closest("article");
    if (!kickoff) throw new Error("Kickoff card not found");
    await user.click(
      within(kickoff as HTMLElement).getByRole("button", {
        name: /^archive$/i,
      }),
    );

    await waitFor(() => {
      expect(posts).toHaveLength(1);
    });
    const headers = (posts[0].headers || {}) as Record<string, string>;
    expect(headers["X-Recap-Token"]).toBe("tok");
    const body = JSON.parse((posts[0].body as string) || "{}");
    expect(body).toEqual({ archived: true });

    // After the POST resolves the active view should drop job_a.
    await waitFor(() => {
      expect(screen.queryByText("Kickoff call")).not.toBeInTheDocument();
    });
  });

  it("switches to archived view when the Archived tab is clicked", async () => {
    const active = [
      makeJob({
        job_id: "job_a",
        display_title: "Active one",
        original_filename: "active.mov",
      }),
    ];
    const archived = [
      makeJob({
        job_id: "job_b",
        display_title: "Archived one",
        original_filename: "archived.mov",
        archived: true,
      }),
    ];
    const library = makeLibrary({
      counts: { total: 2, active: 1, archived: 1 },
    });
    installFetch((url) => {
      if (url.endsWith("/api/library")) return jsonResponse(library);
      if (
        url.includes("/api/jobs") &&
        !url.includes("/api/jobs/") &&
        url.includes("include_archived=1")
      ) {
        return jsonResponse({
          jobs: [...active, ...archived],
          include_archived: true,
        });
      }
      if (
        url.includes("/api/jobs") &&
        !url.includes("/api/jobs/")
      ) {
        return jsonResponse({
          jobs: active,
          include_archived: false,
        });
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <JobsIndexPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Active one")).toBeInTheDocument();
    expect(
      screen.queryByText("Archived one"),
    ).not.toBeInTheDocument();

    const archivedTab = screen.getByRole("tab", {
      name: /archived \(1\)/i,
    });
    await user.click(archivedTab);

    expect(
      await screen.findByText("Archived one"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Active one")).not.toBeInTheDocument();
  });
});
