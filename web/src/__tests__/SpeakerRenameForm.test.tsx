import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import SpeakerRenameForm from "../components/SpeakerRenameForm";
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

describe("SpeakerRenameForm", () => {
  it("renders one input per speaker with the current label", () => {
    render(
      <SpeakerRenameForm
        speakers={speakers}
        labels={{ "0": "Host" }}
        onCancel={() => {}}
        onSave={() => {}}
      />,
    );

    expect(screen.getByLabelText("Speaker 0")).toHaveValue("Host");
    expect(screen.getByLabelText("Speaker 1")).toHaveValue("");
  });

  it("submits trimmed labels to onSave", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <SpeakerRenameForm
        speakers={speakers}
        labels={{}}
        onCancel={() => {}}
        onSave={onSave}
      />,
    );

    await user.type(screen.getByLabelText("Speaker 0"), "  Ada  ");
    await user.type(screen.getByLabelText("Speaker 1"), " Lin ");
    await user.click(screen.getByRole("button", { name: "Save names" }));

    expect(onSave).toHaveBeenCalledWith({ "0": "Ada", "1": "Lin" });
  });

  it("allows empty labels so the server can delete mappings", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <SpeakerRenameForm
        speakers={speakers}
        labels={{ "0": "Host" }}
        onCancel={() => {}}
        onSave={onSave}
      />,
    );

    await user.clear(screen.getByLabelText("Speaker 0"));
    await user.click(screen.getByRole("button", { name: "Save names" }));

    expect(onSave).toHaveBeenCalledWith({ "0": "", "1": "" });
  });
});
