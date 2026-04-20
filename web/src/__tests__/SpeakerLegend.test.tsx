import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import SpeakerLegend from "../components/SpeakerLegend";
import type { SpeakerInfo } from "../lib/format";

const speakers: SpeakerInfo[] = [
  {
    key: "0",
    raw: 0,
    fallbackLabel: "Speaker 0",
    className: "speaker-0",
    firstSeen: 0,
    duration: 10,
  },
  {
    key: "1",
    raw: 1,
    fallbackLabel: "Speaker 1",
    className: "speaker-1",
    firstSeen: 5,
    duration: 8,
  },
];

describe("SpeakerLegend filter chips", () => {
  it("renders one toggle button per speaker, all pressed by default", () => {
    render(
      <SpeakerLegend
        speakers={speakers}
        labels={{}}
        hiddenSpeakers={new Set()}
        onToggleSpeaker={() => {}}
        onShowAllSpeakers={() => {}}
        onSave={async () => {}}
      />,
    );
    const s0 = screen.getByRole("button", { name: /Speaker 0/ });
    const s1 = screen.getByRole("button", { name: /Speaker 1/ });
    expect(s0).toHaveAttribute("aria-pressed", "true");
    expect(s1).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: "Show all" }),
    ).not.toBeInTheDocument();
  });

  it("calls onToggleSpeaker when a pill is clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    render(
      <SpeakerLegend
        speakers={speakers}
        labels={{}}
        hiddenSpeakers={new Set()}
        onToggleSpeaker={onToggle}
        onShowAllSpeakers={() => {}}
        onSave={async () => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Speaker 0/ }));
    expect(onToggle).toHaveBeenCalledWith("0");
  });

  it("reflects hidden speakers via aria-pressed=false and shows a reset button", async () => {
    const user = userEvent.setup();
    const onShowAll = vi.fn();
    render(
      <SpeakerLegend
        speakers={speakers}
        labels={{}}
        hiddenSpeakers={new Set(["0"])}
        onToggleSpeaker={() => {}}
        onShowAllSpeakers={onShowAll}
        onSave={async () => {}}
      />,
    );
    expect(
      screen.getByRole("button", { name: /Speaker 0/ }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("button", { name: /Speaker 1/ }),
    ).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Show all" }));
    expect(onShowAll).toHaveBeenCalledTimes(1);
  });
});
