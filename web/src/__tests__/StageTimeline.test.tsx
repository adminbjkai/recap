import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StageTimeline from "../components/StageTimeline";

describe("StageTimeline", () => {
  it("renders core stages in a fixed order with their statuses", () => {
    render(
      <StageTimeline
        stages={{
          assemble: { status: "completed" },
          transcribe: { status: "running" },
          normalize: { status: "completed" },
          ingest: { status: "completed" },
        }}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(
      within(items[0]).getByRole("heading", { name: "Ingest" }),
    ).toBeInTheDocument();
    expect(
      within(items[1]).getByRole("heading", { name: "Normalize" }),
    ).toBeInTheDocument();
    expect(
      within(items[2]).getByRole("heading", { name: "Transcribe" }),
    ).toBeInTheDocument();
    expect(
      within(items[3]).getByRole("heading", { name: "Assemble" }),
    ).toBeInTheDocument();
  });

  it("surfaces failed-stage error text prominently", () => {
    render(
      <StageTimeline
        stages={{
          ingest: { status: "completed" },
          normalize: { status: "completed" },
          transcribe: {
            status: "failed",
            error: "Deepgram returned 402 Payment Required",
          },
          assemble: { status: "pending" },
        }}
      />,
    );
    expect(
      screen.getByText(/Deepgram returned 402 Payment Required/),
    ).toBeInTheDocument();
    // The failed stage should carry a dedicated status modifier on the
    // outer <li>, so CSS can style the whole item if it wants.
    const failedHeading = screen.getByRole("heading", { name: "Transcribe" });
    const failedItem = failedHeading.closest("li");
    expect(failedItem).not.toBeNull();
    expect(failedItem?.className).toMatch(/status-failed/);
  });

  it("appends optional stages after the core four, alphabetically", () => {
    render(
      <StageTimeline
        stages={{
          ingest: { status: "completed" },
          normalize: { status: "completed" },
          transcribe: { status: "completed" },
          assemble: { status: "completed" },
          insights: { status: "completed" },
          export_docx: { status: "completed" },
          export_html: { status: "completed" },
        }}
      />,
    );
    const headings = screen
      .getAllByRole("heading")
      .filter((h) => h.tagName === "H3")
      .map((h) => h.textContent);
    expect(headings).toEqual([
      "Ingest",
      "Normalize",
      "Transcribe",
      "Assemble",
      "Export DOCX",
      "Export HTML",
      "Insights",
    ]);
  });

  it("renders an empty state when no stages are recorded", () => {
    render(<StageTimeline stages={{}} />);
    expect(
      screen.getByText("No stages recorded yet."),
    ).toBeInTheDocument();
  });
});
