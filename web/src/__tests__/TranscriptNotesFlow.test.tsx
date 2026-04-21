import { createRef } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import TranscriptTable from "../components/TranscriptTable";
import type { TranscriptRow } from "../lib/format";
import { computeTranscriptMatches } from "../lib/search";

function row(id: string, start: number, text: string): TranscriptRow {
  return { id, start, end: start + 2, text };
}

describe("TranscriptTable notes affordance", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows an 'edited' badge when a correction exists and renders the overlay text", () => {
    const videoRef = createRef<HTMLVideoElement>();
    const rows = [row("utt-0", 0, "Canonical line")];
    const matches = computeTranscriptMatches(rows, "");
    render(
      <TranscriptTable
        rows={rows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={null}
        hiddenSpeakers={new Set()}
        totalRowCount={rows.length}
        notes={{
          "utt-0": { correction: "Revised line", note: "Review later" },
        }}
        showCorrections={true}
      />,
    );
    expect(screen.getByText("Revised line")).toBeInTheDocument();
    expect(screen.queryByText("Canonical line")).not.toBeInTheDocument();
    expect(screen.getByText(/edited/i)).toBeInTheDocument();
    expect(screen.getByText(/1 note/i)).toBeInTheDocument();
    expect(screen.getByText("Review later")).toBeInTheDocument();
  });

  it("shows canonical text when showCorrections is toggled off", async () => {
    const videoRef = createRef<HTMLVideoElement>();
    const rows = [row("utt-0", 0, "Canonical line")];
    const matches = computeTranscriptMatches(rows, "");
    const onToggle = vi.fn();
    const { rerender } = render(
      <TranscriptTable
        rows={rows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={null}
        hiddenSpeakers={new Set()}
        totalRowCount={rows.length}
        notes={{ "utt-0": { correction: "Revised line" } }}
        showCorrections={true}
        onToggleCorrections={onToggle}
      />,
    );
    // Toggle exists.
    const toggle = screen.getByLabelText(/show corrections/i);
    await userEvent.setup().click(toggle);
    expect(onToggle).toHaveBeenCalled();

    // Re-render with false; canonical text should be shown.
    rerender(
      <TranscriptTable
        rows={rows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={null}
        hiddenSpeakers={new Set()}
        totalRowCount={rows.length}
        notes={{ "utt-0": { correction: "Revised line" } }}
        showCorrections={false}
        onToggleCorrections={onToggle}
      />,
    );
    expect(screen.getByText("Canonical line")).toBeInTheDocument();
  });

  it("invokes onOpenNoteEditor and renders the row editor slot", async () => {
    const videoRef = createRef<HTMLVideoElement>();
    const rows = [row("utt-0", 0, "First row"), row("utt-1", 3, "Second row")];
    const matches = computeTranscriptMatches(rows, "");
    const onOpen = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <TranscriptTable
        rows={rows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={null}
        hiddenSpeakers={new Set()}
        totalRowCount={rows.length}
        notes={{}}
        onOpenNoteEditor={onOpen}
        renderRowEditor={(rowId) => (
          <div data-testid={`editor-${rowId}`}>editor for {rowId}</div>
        )}
      />,
    );
    const noteButtons = screen.getAllByRole("button", {
      name: /add note to row/i,
    });
    await user.click(noteButtons[0]);
    expect(onOpen).toHaveBeenCalledWith("utt-0");

    rerender(
      <TranscriptTable
        rows={rows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={null}
        hiddenSpeakers={new Set()}
        totalRowCount={rows.length}
        notes={{}}
        onOpenNoteEditor={onOpen}
        editingRowId={"utt-0"}
        renderRowEditor={(rowId) => (
          <div data-testid={`editor-${rowId}`}>editor for {rowId}</div>
        )}
      />,
    );
    expect(screen.getByTestId("editor-utt-0")).toBeInTheDocument();
    expect(screen.getByText("editor for utt-0")).toBeInTheDocument();
  });

  it("search highlighting still runs on canonical text when no overlay is set", () => {
    const videoRef = createRef<HTMLVideoElement>();
    const rows = [row("utt-0", 0, "Hello world"), row("utt-1", 2, "hello again")];
    const matches = computeTranscriptMatches(rows, "hello");
    render(
      <TranscriptTable
        rows={rows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={0}
        hiddenSpeakers={new Set()}
        totalRowCount={rows.length}
      />,
    );
    const marks = document.querySelectorAll("mark.transcript-highlight");
    expect(marks.length).toBe(2);
    // Both original rows still render text.
    expect(within(marks[0] as HTMLElement).getByText(/hello/i)).toBeInTheDocument();
  });
});
