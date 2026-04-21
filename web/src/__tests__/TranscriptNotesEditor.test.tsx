import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import TranscriptNotesEditor from "../components/TranscriptNotesEditor";
import { saveTranscriptNotes } from "../lib/api";

describe("TranscriptNotesEditor", () => {
  it("renders the canonical row text and pre-fills initial values", () => {
    render(
      <TranscriptNotesEditor
        rowId="utt-0"
        canonicalText="This is the canonical line."
        timestamp={12.5}
        initial={{ correction: "Revised line", note: "Check later" }}
        onSave={async () => undefined}
        onCancel={() => undefined}
      />,
    );
    expect(
      screen.getByText("This is the canonical line."),
    ).toBeInTheDocument();
    expect(screen.getByRole("region").textContent).toContain("utt-0");
    const correctionField = screen.getByLabelText(
      /correction \(overlay/i,
    ) as HTMLTextAreaElement;
    expect(correctionField.value).toBe("Revised line");
    const noteField = screen.getByLabelText(
      /private note/i,
    ) as HTMLTextAreaElement;
    expect(noteField.value).toBe("Check later");
  });

  it("fires onSave with trimmed payload and calls onCancel", async () => {
    const onSave = vi.fn(
      async (_payload: { correction: string; note: string }) => undefined,
    );
    const onCancel = vi.fn();
    const user = userEvent.setup();
    render(
      <TranscriptNotesEditor
        rowId="seg-3"
        canonicalText="A"
        timestamp={0}
        initial={null}
        onSave={onSave}
        onCancel={onCancel}
      />,
    );
    const correctionField = screen.getByLabelText(
      /correction \(overlay/i,
    );
    await user.type(correctionField, "Hello");
    const noteField = screen.getByLabelText(/private note/i);
    await user.type(noteField, "Follow up");
    await user.click(screen.getByRole("button", { name: /save review/i }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toEqual({
      correction: "Hello",
      note: "Follow up",
    });

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("surfaces a provided error message", () => {
    render(
      <TranscriptNotesEditor
        rowId="utt-0"
        canonicalText="x"
        timestamp={0}
        initial={null}
        onSave={async () => undefined}
        onCancel={() => undefined}
        error="Note exceeds 1000 characters."
      />,
    );
    expect(
      screen.getByText(/note exceeds 1000 characters/i),
    ).toBeInTheDocument();
  });

  it("cancels on Escape without calling onSave", async () => {
    const onCancel = vi.fn();
    const onSave = vi.fn(async () => undefined);
    const user = userEvent.setup();
    render(
      <TranscriptNotesEditor
        rowId="utt-0"
        canonicalText="x"
        timestamp={0}
        initial={null}
        onSave={onSave}
        onCancel={onCancel}
      />,
    );
    const correctionField = screen.getByLabelText(
      /correction \(overlay/i,
    );
    await user.click(correctionField);
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("saveTranscriptNotes (unit)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("POSTs items with CSRF header and returns the server doc", async () => {
    const calls: RequestInit[] = [];
    globalThis.fetch = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/csrf")) {
          return new Response(JSON.stringify({ token: "tok" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/transcript-notes")) {
          calls.push(init || {});
          return new Response(
            JSON.stringify({
              version: 1,
              updated_at: "now",
              items: {
                "utt-0": { correction: "Hello", note: "" },
              },
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

    const doc = await saveTranscriptNotes("job_a", {
      "utt-0": { correction: "Hello" },
    });
    expect(doc.items["utt-0"]?.correction).toBe("Hello");
    expect(calls).toHaveLength(1);
    const headers = (calls[0].headers || {}) as Record<string, string>;
    expect(headers["X-Recap-Token"]).toBe("tok");
    const body = JSON.parse((calls[0].body as string) || "{}");
    expect(body).toEqual({
      items: { "utt-0": { correction: "Hello" } },
    });
  });
});

