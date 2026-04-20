import type { TranscriptRow } from "./format";

export type TranscriptMatch = {
  globalIndex: number;
  rowId: string;
  rowIndex: number;
  start: number;
  end: number;
};

export type TranscriptMatches = {
  matches: TranscriptMatch[];
  byRow: Map<string, TranscriptMatch[]>;
};

export function computeTranscriptMatches(
  rows: TranscriptRow[],
  query: string,
): TranscriptMatches {
  const needle = query.trim().toLowerCase();
  const empty: TranscriptMatches = { matches: [], byRow: new Map() };
  if (!needle) {
    return empty;
  }
  const matches: TranscriptMatch[] = [];
  const byRow = new Map<string, TranscriptMatch[]>();

  rows.forEach((row, rowIndex) => {
    const text = row.text;
    if (!text) return;
    const haystack = text.toLowerCase();
    const perRow: TranscriptMatch[] = [];
    let cursor = 0;
    while (cursor <= haystack.length - needle.length) {
      const hit = haystack.indexOf(needle, cursor);
      if (hit < 0) break;
      const match: TranscriptMatch = {
        globalIndex: matches.length,
        rowId: row.id,
        rowIndex,
        start: hit,
        end: hit + needle.length,
      };
      matches.push(match);
      perRow.push(match);
      cursor = hit + needle.length;
    }
    if (perRow.length > 0) {
      byRow.set(row.id, perRow);
    }
  });

  return { matches, byRow };
}

type HighlightSegment =
  | { kind: "text"; text: string }
  | { kind: "match"; text: string; globalIndex: number };

export function splitTextWithMatches(
  text: string,
  rowMatches: TranscriptMatch[] | undefined,
): HighlightSegment[] {
  if (!rowMatches || rowMatches.length === 0) {
    return [{ kind: "text", text }];
  }
  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const match of rowMatches) {
    if (match.start > cursor) {
      segments.push({
        kind: "text",
        text: text.slice(cursor, match.start),
      });
    }
    segments.push({
      kind: "match",
      text: text.slice(match.start, match.end),
      globalIndex: match.globalIndex,
    });
    cursor = match.end;
  }
  if (cursor < text.length) {
    segments.push({ kind: "text", text: text.slice(cursor) });
  }
  return segments;
}
