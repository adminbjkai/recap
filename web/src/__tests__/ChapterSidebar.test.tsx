import { createRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChapterSidebar from "../components/ChapterSidebar";
import type { ChapterEntry } from "../lib/api";

function makeChapters(): ChapterEntry[] {
  return [
    {
      index: 1,
      start_seconds: 0.0,
      end_seconds: 60.0,
      fallback_title: "Intro and agenda",
      custom_title: null,
      display_title: "Intro and agenda",
      summary: "Opening overview of the call.",
      bullets: ["Who is here", "What we will cover"],
    },
    {
      index: 2,
      start_seconds: 60.0,
      end_seconds: 180.0,
      fallback_title: "Onboarding deep-dive",
      custom_title: "Onboarding walkthrough",
      display_title: "Onboarding walkthrough",
      summary: "Hands-on walkthrough.",
      action_items: ["Share doc"],
    },
  ];
}

describe("ChapterSidebar", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the empty state when no chapters exist", () => {
    const videoRef = createRef<HTMLVideoElement>();
    render(
      <ChapterSidebar
        chapters={[]}
        videoRef={videoRef}
        activeIndex={null}
        onSeek={() => undefined}
        onSaveTitle={async () => undefined}
        saveError={null}
        hasCandidateArtifact={false}
        hasInsightsArtifact={false}
      />,
    );
    expect(screen.getByText(/no chapters yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/recap insights --job jobs\/<id>/i),
    ).toBeInTheDocument();
  });

  it("renders a chapter list with active-state highlight and custom badge", () => {
    const videoRef = createRef<HTMLVideoElement>();
    render(
      <ChapterSidebar
        chapters={makeChapters()}
        videoRef={videoRef}
        activeIndex={2}
        onSeek={() => undefined}
        onSaveTitle={async () => undefined}
        saveError={null}
        hasCandidateArtifact={true}
        hasInsightsArtifact={true}
      />,
    );
    // Both chapters render.
    expect(screen.getByText("Intro and agenda")).toBeInTheDocument();
    expect(
      screen.getByText("Onboarding walkthrough"),
    ).toBeInTheDocument();
    // "custom" badge only on the chapter whose custom_title is set.
    expect(screen.getByText(/custom/i)).toBeInTheDocument();
    // Active chapter row carries aria-current, not color-only state.
    const activeRow = screen
      .getByText("Onboarding walkthrough")
      .closest("li");
    expect(activeRow).toHaveAttribute("aria-current", "true");
    // Provenance chip surfaces artifact sources.
    expect(
      screen.getByText(/chapter_candidates\.json \+ insights\.json/i),
    ).toBeInTheDocument();
  });

  it("calls onSeek with the chapter when the seek button is clicked", async () => {
    const videoRef = createRef<HTMLVideoElement>();
    const onSeek = vi.fn();
    const user = userEvent.setup();
    render(
      <ChapterSidebar
        chapters={makeChapters()}
        videoRef={videoRef}
        activeIndex={null}
        onSeek={onSeek}
        onSaveTitle={async () => undefined}
        saveError={null}
        hasCandidateArtifact={true}
        hasInsightsArtifact={false}
      />,
    );
    const seekButton = screen.getByRole("button", {
      name: /seek to chapter 1: intro and agenda/i,
    });
    await user.click(seekButton);
    expect(onSeek).toHaveBeenCalledTimes(1);
    expect(onSeek.mock.calls[0][0].index).toBe(1);
  });

  it("edits a chapter title and calls onSaveTitle with the trimmed value", async () => {
    const videoRef = createRef<HTMLVideoElement>();
    const onSaveTitle = vi.fn(async () => undefined);
    const user = userEvent.setup();
    render(
      <ChapterSidebar
        chapters={makeChapters()}
        videoRef={videoRef}
        activeIndex={null}
        onSeek={() => undefined}
        onSaveTitle={onSaveTitle}
        saveError={null}
        hasCandidateArtifact={true}
        hasInsightsArtifact={false}
      />,
    );
    // Click the Rename button on chapter 1.
    const renameButtons = screen.getAllByRole("button", {
      name: /rename chapter 1/i,
    });
    await user.click(renameButtons[0]);

    const input = await screen.findByRole("textbox", {
      name: /edit title for chapter 1/i,
    });
    // Pre-populated with the fallback title; clear and type fresh.
    await user.clear(input);
    await user.type(input, "  Kickoff  ");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(onSaveTitle).toHaveBeenCalledTimes(1);
    });
    expect(onSaveTitle.mock.calls[0]).toEqual([1, "Kickoff"]);
  });

  it("shows an inline error when the save callback rejects", async () => {
    const videoRef = createRef<HTMLVideoElement>();
    const onSaveTitle = vi.fn(async () => {
      throw new Error("Chapter title exceeds 120 characters.");
    });
    const user = userEvent.setup();
    render(
      <ChapterSidebar
        chapters={makeChapters()}
        videoRef={videoRef}
        activeIndex={null}
        onSeek={() => undefined}
        onSaveTitle={onSaveTitle}
        saveError={null}
        hasCandidateArtifact={false}
        hasInsightsArtifact={true}
      />,
    );
    const renameButtons = screen.getAllByRole("button", {
      name: /rename chapter 1/i,
    });
    await user.click(renameButtons[0]);
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(
      await screen.findByText(/chapter title exceeds 120 characters/i),
    ).toBeInTheDocument();
    expect(onSaveTitle).toHaveBeenCalledTimes(1);
  });

  it("Escape cancels the edit without calling onSaveTitle", async () => {
    const videoRef = createRef<HTMLVideoElement>();
    const onSaveTitle = vi.fn(async () => undefined);
    const user = userEvent.setup();
    render(
      <ChapterSidebar
        chapters={makeChapters()}
        videoRef={videoRef}
        activeIndex={null}
        onSeek={() => undefined}
        onSaveTitle={onSaveTitle}
        saveError={null}
        hasCandidateArtifact={true}
        hasInsightsArtifact={false}
      />,
    );
    await user.click(
      screen.getAllByRole("button", { name: /rename chapter 1/i })[0],
    );
    const input = await screen.findByRole("textbox", {
      name: /edit title for chapter 1/i,
    });
    await user.type(input, "{Escape}");
    expect(onSaveTitle).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("textbox", {
        name: /edit title for chapter 1/i,
      }),
    ).not.toBeInTheDocument();
  });
});

describe("TranscriptWorkspacePage chapter wiring", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // no timers
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("saveChapterTitles posts to /api/jobs/:id/chapter-titles with CSRF", async () => {
    const calls: RequestInit[] = [];
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/csrf")) {
          return new Response(JSON.stringify({ token: "tok" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/chapter-titles")) {
          calls.push(init || {});
          return new Response(
            JSON.stringify({
              version: 1,
              updated_at: "now",
              titles: { "1": "Kickoff" },
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }
        return new Response("{}", { status: 404 });
      },
    ) as typeof fetch;

    const { saveChapterTitles } = await import("../lib/api");
    const doc = await saveChapterTitles("job_a", { "1": "Kickoff" });
    expect(doc.titles).toEqual({ "1": "Kickoff" });
    expect(calls).toHaveLength(1);
    const headers = (calls[0].headers || {}) as Record<string, string>;
    expect(headers["X-Recap-Token"]).toBe("tok");
  });
});
