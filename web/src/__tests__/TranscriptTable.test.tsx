import { createRef } from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TranscriptTable from "../components/TranscriptTable";
import type { TranscriptRow } from "../lib/format";
import { computeTranscriptMatches } from "../lib/search";

function row(
  id: string,
  start: number,
  text: string,
  speaker?: number,
): TranscriptRow {
  return {
    id,
    start,
    end: start + 2,
    text,
    speaker,
    speakerKey: speaker != null ? String(speaker) : undefined,
    speakerClassName:
      speaker != null ? `speaker-${speaker % 8}` : undefined,
  };
}

const allRows: TranscriptRow[] = [
  row("r0", 0, "Hello world", 0),
  row("r1", 4, "Welcome back to the show", 1),
  row("r2", 10, "Hello again, world", 0),
];

describe("TranscriptTable search highlighting", () => {
  it("wraps matches in <mark> and flags the active one", () => {
    const videoRef = createRef<HTMLVideoElement>();
    const matches = computeTranscriptMatches(allRows, "hello");
    expect(matches.matches.length).toBe(2);

    render(
      <TranscriptTable
        rows={allRows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={1}
        hiddenSpeakers={new Set()}
        totalRowCount={allRows.length}
      />,
    );

    const marks = document.querySelectorAll("mark.transcript-highlight");
    expect(marks.length).toBe(2);

    const active = document.querySelector(
      "mark.transcript-highlight.active",
    );
    expect(active).not.toBeNull();
    expect(active?.textContent).toBe("Hello");
    expect(active?.getAttribute("data-match-index")).toBe("1");
  });

  it("shows a friendly state when every speaker is hidden", () => {
    const videoRef = createRef<HTMLVideoElement>();
    render(
      <TranscriptTable
        rows={[]}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={{ matches: [], byRow: new Map() }}
        activeMatchIndex={null}
        hiddenSpeakers={new Set(["0", "1"])}
        totalRowCount={allRows.length}
      />,
    );

    expect(
      screen.getByText(/Every speaker is currently hidden/i),
    ).toBeInTheDocument();
  });

  it("renders the supplied toolbar inside the card header", () => {
    const videoRef = createRef<HTMLVideoElement>();
    const matches = computeTranscriptMatches(allRows, "");

    render(
      <TranscriptTable
        rows={allRows}
        speakerLabels={{}}
        videoRef={videoRef}
        matches={matches}
        activeMatchIndex={null}
        hiddenSpeakers={new Set()}
        totalRowCount={allRows.length}
        toolbar={<div data-testid="transcript-toolbar">Search</div>}
      />,
    );

    const toolbar = screen.getByTestId("transcript-toolbar");
    expect(toolbar).toBeInTheDocument();
    // Toolbar must live inside the card header.
    const header = toolbar.closest(".transcript-card-header");
    expect(header).not.toBeNull();
    expect(within(header as HTMLElement).getByText("Search")).toBeInTheDocument();
  });
});
