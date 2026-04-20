import { describe, expect, it } from "vitest";
import {
  computeTranscriptMatches,
  splitTextWithMatches,
} from "../lib/search";
import type { TranscriptRow } from "../lib/format";

function row(id: string, text: string): TranscriptRow {
  return { id, start: 0, end: 0, text };
}

describe("computeTranscriptMatches", () => {
  it("returns empty for blank query", () => {
    const rows = [row("a", "hello world")];
    const result = computeTranscriptMatches(rows, "");
    expect(result.matches).toEqual([]);
    expect(result.byRow.size).toBe(0);
  });

  it("finds case-insensitive matches and indexes them globally", () => {
    const rows = [
      row("a", "Hello World"),
      row("b", "world of wonder"),
    ];
    const result = computeTranscriptMatches(rows, "world");
    expect(result.matches).toHaveLength(2);
    expect(result.matches[0]).toMatchObject({
      globalIndex: 0,
      rowId: "a",
      rowIndex: 0,
      start: 6,
      end: 11,
    });
    expect(result.matches[1]).toMatchObject({
      globalIndex: 1,
      rowId: "b",
      rowIndex: 1,
      start: 0,
      end: 5,
    });
    expect(result.byRow.get("a")).toHaveLength(1);
    expect(result.byRow.get("b")).toHaveLength(1);
  });

  it("finds multiple matches per row", () => {
    const rows = [row("a", "ab ab ab")];
    const result = computeTranscriptMatches(rows, "ab");
    expect(result.matches).toHaveLength(3);
    expect(result.matches.map((m) => m.start)).toEqual([0, 3, 6]);
  });

  it("skips blank rows and trims whitespace-only queries", () => {
    const rows = [row("a", ""), row("b", "text")];
    expect(computeTranscriptMatches(rows, "   ").matches).toEqual([]);
    expect(computeTranscriptMatches(rows, "text").matches).toHaveLength(1);
  });
});

describe("splitTextWithMatches", () => {
  it("returns a single text segment when no matches", () => {
    expect(splitTextWithMatches("hello", undefined)).toEqual([
      { kind: "text", text: "hello" },
    ]);
  });

  it("splits text into text/match segments around each match", () => {
    const rows = [row("a", "Foo bar foo")];
    const { byRow } = computeTranscriptMatches(rows, "foo");
    const segments = splitTextWithMatches("Foo bar foo", byRow.get("a"));
    expect(segments).toEqual([
      { kind: "match", text: "Foo", globalIndex: 0 },
      { kind: "text", text: " bar " },
      { kind: "match", text: "foo", globalIndex: 1 },
    ]);
  });
});
