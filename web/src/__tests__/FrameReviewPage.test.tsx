import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import FrameReviewPage from "../pages/FrameReviewPage";
import type {
  FrameItem,
  FrameListPayload,
  JobSummary,
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

function makeJob(): JobSummary {
  return {
    job_id: "job_a",
    original_filename: "meeting.mov",
    created_at: "2026-04-20T00:00:00",
    updated_at: "2026-04-20T00:10:00",
    status: "completed",
    error: null,
    stages: {},
    artifacts: {
      transcript_json: true,
      analysis_mp4: true,
      report_md: false,
      report_html: false,
      report_docx: false,
      selected_frames_json: true,
      chapter_candidates_json: true,
      speaker_names_json: false,
      insights_json: false,
    } as unknown as JobSummary["artifacts"],
    urls: {
      analysis_mp4: "/job/job_a/analysis.mp4",
      transcript: "/api/jobs/job_a/transcript",
      speaker_names: "/api/jobs/job_a/speaker-names",
    } as unknown as JobSummary["urls"],
  };
}

function makeFrame(overrides: Partial<FrameItem>): FrameItem {
  return {
    frame_file: "scene-001.jpg",
    image_url: "/job/job_a/candidate_frames/scene-001.jpg",
    on_disk: true,
    scene_index: 1,
    timestamp_seconds: 12.5,
    chapter_index: 1,
    decision: "selected_hero",
    shortlist_decision: "hero",
    rank: 1,
    composite_score: 0.82,
    clip_similarity: 0.35,
    text_novelty: 0.99,
    phash: "abcd1234",
    ocr_text: null,
    duplicate_of: null,
    reasons: ["kept_as_hero"],
    verification: {
      provider: "mock",
      relevance: "relevant",
      confidence: 0.82,
      model: null,
      caption: null,
    },
    window_text: null,
    review: { decision: null, note: "" },
    ...overrides,
  };
}

function makeFrames(frames: FrameItem[]): FrameListPayload {
  return {
    frames,
    chapters: [
      {
        index: 1,
        start_seconds: 0,
        end_seconds: 60,
        display_title: "Intro",
      },
    ],
    sources: {
      selected_frames: true,
      frame_scores: true,
      scenes: true,
      candidate_frames_dir: true,
      frame_review_overlay: false,
    },
    overlay: { version: 1, updated_at: null, frames: {} },
  };
}

function renderWithRoute() {
  return render(
    <MemoryRouter initialEntries={["/job/job_a/frames"]}>
      <Routes>
        <Route path="/job/:id/frames" element={<FrameReviewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FrameReviewPage", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders an empty state when no visual artifacts exist", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/jobs/job_a")) return jsonResponse(makeJob());
      if (url.endsWith("/api/jobs/job_a/frames")) {
        return jsonResponse({
          frames: [],
          chapters: [],
          sources: {
            selected_frames: false,
            frame_scores: false,
            scenes: false,
            candidate_frames_dir: false,
            frame_review_overlay: false,
          },
          overlay: { version: 1, updated_at: null, frames: {} },
        });
      }
      return new Response("{}", { status: 404 });
    });

    renderWithRoute();
    expect(
      await screen.findByText(/nothing to review/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/generate rich report/i),
    ).toBeInTheDocument();
  });

  it("renders a frame grid with image, timestamp, and pills", async () => {
    installFetch((url) => {
      if (url.endsWith("/api/jobs/job_a")) return jsonResponse(makeJob());
      if (url.endsWith("/api/jobs/job_a/frames")) {
        return jsonResponse(
          makeFrames([
            makeFrame({ frame_file: "scene-001.jpg" }),
            makeFrame({
              frame_file: "scene-002.jpg",
              image_url: "/job/job_a/candidate_frames/scene-002.jpg",
              decision: "vlm_rejected",
              shortlist_decision: "supporting",
              rank: 2,
              timestamp_seconds: 45.2,
              review: { decision: null, note: "" },
            }),
          ]),
        );
      }
      return new Response("{}", { status: 404 });
    });

    renderWithRoute();
    expect(await screen.findByText("scene-001.jpg")).toBeInTheDocument();
    expect(screen.getByText("scene-002.jpg")).toBeInTheDocument();
    // Hero label appears once (first frame).
    expect(screen.getByText(/^hero$/i)).toBeInTheDocument();
    // Images render with src URLs.
    const imgs = screen.getAllByRole("img");
    expect(imgs.length).toBeGreaterThanOrEqual(2);
    expect(imgs[0]).toHaveAttribute(
      "src",
      "/job/job_a/candidate_frames/scene-001.jpg",
    );
  });

  it("enables Save after a decision change and POSTs to /frame-review with CSRF", async () => {
    const posts: RequestInit[] = [];
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "tok" });
      }
      if (url.endsWith("/api/jobs/job_a")) return jsonResponse(makeJob());
      if (url.endsWith("/api/jobs/job_a/frames") && (!init || init.method !== "POST")) {
        return jsonResponse(
          makeFrames([makeFrame({ frame_file: "scene-001.jpg" })]),
        );
      }
      if (
        url.endsWith("/api/jobs/job_a/frame-review") &&
        init &&
        init.method === "POST"
      ) {
        posts.push(init);
        return jsonResponse(
          {
            version: 1,
            updated_at: "now",
            frames: {
              "scene-001.jpg": { decision: "reject", note: "blurry" },
            },
          },
          200,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    renderWithRoute();
    await screen.findByText("scene-001.jpg");

    const saveButton = screen.getByRole("button", {
      name: /save review/i,
    });
    expect(saveButton).toBeDisabled();

    const card = screen.getByLabelText(/frame scene-001\.jpg/i);
    await user.click(within(card).getByLabelText("Reject"));

    await waitFor(() => {
      expect(saveButton).not.toBeDisabled();
    });
    // The save CTA reflects the dirty count.
    expect(
      screen.getByRole("button", { name: /save review \(1\)/i }),
    ).toBeInTheDocument();

    const noteInput = within(card).getByPlaceholderText(
      /why keep or reject/i,
    ) as HTMLTextAreaElement;
    await user.type(noteInput, "blurry");

    await user.click(
      screen.getByRole("button", { name: /save review/i }),
    );

    await waitFor(() => {
      expect(screen.getByText(/review saved/i)).toBeInTheDocument();
    });
    expect(posts).toHaveLength(1);
    const headers = (posts[0].headers || {}) as Record<string, string>;
    expect(headers["X-Recap-Token"]).toBe("tok");
    const body = JSON.parse((posts[0].body as string) || "{}");
    expect(body.frames["scene-001.jpg"]).toEqual({
      decision: "reject",
      note: "blurry",
    });
  });

  it("renders a bounded error when save fails", async () => {
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) return jsonResponse({ token: "tok" });
      if (url.endsWith("/api/jobs/job_a")) return jsonResponse(makeJob());
      if (url.endsWith("/api/jobs/job_a/frames") && (!init || init.method !== "POST")) {
        return jsonResponse(
          makeFrames([makeFrame({ frame_file: "scene-001.jpg" })]),
        );
      }
      if (url.endsWith("/api/jobs/job_a/frame-review")) {
        return jsonResponse(
          { error: "Note exceeds 300 characters.", reason: "too-long" },
          400,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    renderWithRoute();
    await screen.findByText("scene-001.jpg");
    const card = screen.getByLabelText(/frame scene-001\.jpg/i);
    await user.click(within(card).getByLabelText("Keep"));
    await user.click(screen.getByRole("button", { name: /save review/i }));
    expect(
      await screen.findByText(/note exceeds 300 characters/i),
    ).toBeInTheDocument();
  });

  it("filters frames by Reviewed filter when a review overlay is set", async () => {
    const reviewed = makeFrame({
      frame_file: "scene-001.jpg",
      review: { decision: "keep", note: "" },
    });
    const untouched = makeFrame({
      frame_file: "scene-002.jpg",
      decision: "selected_supporting",
      shortlist_decision: "supporting",
      rank: 2,
      image_url: "/job/job_a/candidate_frames/scene-002.jpg",
    });
    installFetch((url) => {
      if (url.endsWith("/api/jobs/job_a")) return jsonResponse(makeJob());
      if (url.endsWith("/api/jobs/job_a/frames")) {
        return jsonResponse({
          ...makeFrames([reviewed, untouched]),
          sources: {
            selected_frames: true,
            frame_scores: true,
            scenes: true,
            candidate_frames_dir: true,
            frame_review_overlay: true,
          },
        });
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    renderWithRoute();
    await screen.findByText("scene-001.jpg");

    // Default "All" shows both; switch to "Reviewed (1)" and only the
    // reviewed frame remains.
    const reviewedTab = screen.getByRole("tab", { name: /reviewed \(1\)/i });
    await user.click(reviewedTab);

    expect(screen.getByText("scene-001.jpg")).toBeInTheDocument();
    expect(screen.queryByText("scene-002.jpg")).not.toBeInTheDocument();
  });
});
