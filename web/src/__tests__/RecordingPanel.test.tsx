import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RecordingPanel from "../components/RecordingPanel";
import type { RecordingUploadResponse } from "../lib/api";

type DataHandler = ((event: { data: Blob }) => void) | null;

class FakeMediaStream {
  private _tracks: FakeTrack[];
  constructor(tracks: FakeTrack[] = []) {
    this._tracks = tracks;
  }
  getTracks() {
    return this._tracks;
  }
  getVideoTracks() {
    return this._tracks.filter((t) => t.kind === "video");
  }
  getAudioTracks() {
    return this._tracks.filter((t) => t.kind === "audio");
  }
  addTrack(track: FakeTrack) {
    this._tracks.push(track);
  }
}

class FakeTrack {
  kind: "video" | "audio";
  private handlers = new Map<string, Array<() => void>>();
  constructor(kind: "video" | "audio") {
    this.kind = kind;
  }
  stop() {
    /* noop */
  }
  addEventListener(name: string, fn: () => void) {
    const list = this.handlers.get(name) || [];
    list.push(fn);
    this.handlers.set(name, list);
  }
  removeEventListener() {
    /* noop */
  }
}

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  state: "inactive" | "recording" | "paused" = "inactive";
  ondataavailable: DataHandler = null;
  onstop: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  private _stream: FakeMediaStream;
  constructor(stream: FakeMediaStream, _options?: { mimeType?: string }) {
    this._stream = stream;
    void this._stream;
  }
  start(_ms?: number) {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    if (this.ondataavailable) {
      this.ondataavailable({
        data: new Blob(["fake-webm-bytes"], { type: "video/webm" }),
      });
    }
    if (this.onstop) {
      this.onstop();
    }
  }
}

function installBrowserApis(overrides: {
  getDisplayMediaReject?: Error;
} = {}) {
  const displayTracks = [new FakeTrack("video"), new FakeTrack("audio")];
  const displayStream = new FakeMediaStream(displayTracks);
  const micStream = new FakeMediaStream([new FakeTrack("audio")]);

  const getDisplayMedia = vi.fn(async () => {
    if (overrides.getDisplayMediaReject) {
      throw overrides.getDisplayMediaReject;
    }
    return displayStream as unknown as MediaStream;
  });
  const getUserMedia = vi.fn(
    async () => micStream as unknown as MediaStream,
  );

  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getDisplayMedia, getUserMedia },
  });

  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder =
    FakeMediaRecorder as unknown;
  (globalThis as unknown as { MediaStream: unknown }).MediaStream =
    FakeMediaStream as unknown;

  const createObjectURL = vi.fn(() => "blob:mock-url");
  const revokeObjectURL = vi.fn(() => undefined);
  URL.createObjectURL = createObjectURL as typeof URL.createObjectURL;
  URL.revokeObjectURL = revokeObjectURL as typeof URL.revokeObjectURL;

  return { getDisplayMedia, getUserMedia, createObjectURL };
}

function uninstallBrowserApis() {
  const globals = globalThis as unknown as {
    MediaRecorder?: unknown;
    MediaStream?: unknown;
  };
  delete globals.MediaRecorder;
  delete globals.MediaStream;
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: undefined,
  });
}

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

describe("RecordingPanel", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    uninstallBrowserApis();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders an unsupported state when MediaRecorder is missing", () => {
    uninstallBrowserApis();
    render(<RecordingPanel onSaved={() => undefined} />);
    expect(
      screen.getByText(/your browser can't record screens here/i),
    ).toBeInTheDocument();
  });

  it("shows the Start button when the APIs are available", () => {
    installBrowserApis();
    render(<RecordingPanel onSaved={() => undefined} />);
    expect(
      screen.getByRole("button", { name: /start screen recording/i }),
    ).toBeInTheDocument();
  });

  it("transitions through recording → stopped → preview", async () => {
    installBrowserApis();
    const user = userEvent.setup();
    render(<RecordingPanel onSaved={() => undefined} />);

    await user.click(
      screen.getByRole("button", { name: /start screen recording/i }),
    );

    const stop = await screen.findByRole("button", {
      name: /stop recording/i,
    });
    expect(stop).toBeInTheDocument();
    expect(screen.getByText(/recording ·/i)).toBeInTheDocument();

    await user.click(stop);
    expect(
      await screen.findByRole("button", { name: /save to sources/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /discard/i }),
    ).toBeInTheDocument();
  });

  it("uploads the recording and exposes the saved state", async () => {
    installBrowserApis();
    const uploads: RequestInit[] = [];
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "test-token" });
      }
      if (url.endsWith("/api/recordings")) {
        uploads.push(init || {});
        return jsonResponse(
          {
            name: "recording-20260420T000001Z-abcd1234.webm",
            size_bytes: 128,
            modified_at: "2026-04-20T00:00:01Z",
            content_type: "video/webm",
            source: {
              kind: "sources-root",
              name: "recording-20260420T000001Z-abcd1234.webm",
            },
          },
          201,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const saved = vi.fn((_response: RecordingUploadResponse) => undefined);
    const user = userEvent.setup();
    render(<RecordingPanel onSaved={saved} />);

    await user.click(
      screen.getByRole("button", { name: /start screen recording/i }),
    );
    const stop = await screen.findByRole("button", {
      name: /stop recording/i,
    });
    await user.click(stop);
    const save = await screen.findByRole("button", {
      name: /save to sources/i,
    });
    await user.click(save);

    await waitFor(() => {
      expect(
        screen.getByText(/recording saved as/i),
      ).toBeInTheDocument();
    });
    expect(uploads).toHaveLength(1);
    const headers = (uploads[0].headers || {}) as Record<string, string>;
    expect(headers["X-Recap-Token"]).toBe("test-token");
    expect(headers["Content-Type"]).toBe("video/webm");
    expect(saved).toHaveBeenCalledTimes(1);
    expect(saved.mock.calls[0][0].name).toMatch(/^recording-/);
  });

  it("renders the server-provided error when upload fails", async () => {
    installBrowserApis();
    installFetch((url) => {
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "test-token" });
      }
      if (url.endsWith("/api/recordings")) {
        return jsonResponse(
          { error: "Recording body is empty.", reason: "empty" },
          400,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const user = userEvent.setup();
    render(<RecordingPanel onSaved={() => undefined} />);
    await user.click(
      screen.getByRole("button", { name: /start screen recording/i }),
    );
    await user.click(
      await screen.findByRole("button", { name: /stop recording/i }),
    );
    await user.click(
      await screen.findByRole("button", { name: /save to sources/i }),
    );

    expect(
      await screen.findByText(/recording body is empty/i),
    ).toBeInTheDocument();
  });

  it("surfaces a permission-denied error from getDisplayMedia", async () => {
    installBrowserApis({
      getDisplayMediaReject: new Error("Permission denied by user."),
    });
    const user = userEvent.setup();
    render(<RecordingPanel onSaved={() => undefined} />);

    await user.click(
      screen.getByRole("button", { name: /start screen recording/i }),
    );

    expect(
      await screen.findByText(/permission denied by user/i),
    ).toBeInTheDocument();
    // The primary CTA remains available so the user can retry.
    expect(
      screen.getByRole("button", { name: /start screen recording/i }),
    ).toBeInTheDocument();
  });
});

describe("uploadRecording (unit)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("normalizes codec-tagged Content-Type to video/webm", async () => {
    const calls: RequestInit[] = [];
    installFetch((url, init) => {
      if (url.endsWith("/api/csrf")) {
        return jsonResponse({ token: "tok" });
      }
      if (url.endsWith("/api/recordings")) {
        calls.push(init || {});
        return jsonResponse(
          {
            name: "recording-x.webm",
            size_bytes: 1,
            modified_at: "2026-04-20T00:00:00Z",
            content_type: "video/webm",
            source: { kind: "sources-root", name: "recording-x.webm" },
          },
          201,
        );
      }
      return new Response("{}", { status: 404 });
    });

    const { uploadRecording } = await import("../lib/api");
    const blob = new Blob(["x"], {
      type: "video/webm;codecs=vp9,opus",
    });
    const result = await uploadRecording(blob);
    expect(result.kind).toBe("saved");
    const headers = (calls[0].headers || {}) as Record<string, string>;
    expect(headers["Content-Type"]).toBe("video/webm");
  });
});
