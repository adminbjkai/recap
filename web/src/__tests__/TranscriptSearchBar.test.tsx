import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import TranscriptSearchBar from "../components/TranscriptSearchBar";

describe("TranscriptSearchBar", () => {
  it("shows the position of the active match and enables nav", async () => {
    const user = userEvent.setup();
    const onNext = vi.fn();
    const onPrev = vi.fn();
    render(
      <TranscriptSearchBar
        query="hello"
        onQueryChange={() => {}}
        matchCount={3}
        activeMatchIndex={1}
        onNext={onNext}
        onPrev={onPrev}
      />,
    );

    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next match" }));
    expect(onNext).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "Previous match" }));
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("disables nav buttons and announces zero matches when none", () => {
    render(
      <TranscriptSearchBar
        query="xyz"
        onQueryChange={() => {}}
        matchCount={0}
        activeMatchIndex={null}
        onNext={() => {}}
        onPrev={() => {}}
      />,
    );
    expect(screen.getByText("0 matches")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next match" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Previous match" }),
    ).toBeDisabled();
  });

  it("clears the query via the clear button", async () => {
    const user = userEvent.setup();
    const onQueryChange = vi.fn();
    render(
      <TranscriptSearchBar
        query="hello"
        onQueryChange={onQueryChange}
        matchCount={1}
        activeMatchIndex={0}
        onNext={() => {}}
        onPrev={() => {}}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onQueryChange).toHaveBeenCalledWith("");
  });
});
