import type { TranscriptPayload, TranscriptSegment } from "./api";

export type SpeakerInfo = {
  key: string;
  raw: unknown;
  fallbackLabel: string;
  className: string;
  firstSeen: number;
  duration: number;
};

export type TranscriptRow = {
  id: string;
  start: number;
  end?: number;
  text: string;
  speaker?: unknown;
  speakerKey?: string;
  speakerClassName?: string;
};

const _FILE_SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function formatFileSize(bytes: unknown): string {
  if (
    typeof bytes !== "number" ||
    !Number.isFinite(bytes) ||
    bytes < 0
  ) {
    return "—";
  }
  if (bytes === 0) return "0 B";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < _FILE_SIZE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value < 10 && unit > 0 ? 1 : 0;
  return `${value.toFixed(digits)} ${_FILE_SIZE_UNITS[unit]}`;
}

export function formatJobDateTime(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  const yyyy = parsed.getFullYear();
  const mm = String(parsed.getMonth() + 1).padStart(2, "0");
  const dd = String(parsed.getDate()).padStart(2, "0");
  const hh = String(parsed.getHours()).padStart(2, "0");
  const min = String(parsed.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

export function formatElapsed(ms: number): string {
  const safe = Number.isFinite(ms) && ms > 0 ? ms : 0;
  const totalSeconds = Math.floor(safe / 1000);
  const hh = Math.floor(totalSeconds / 3600);
  const mm = Math.floor((totalSeconds % 3600) / 60);
  const ss = totalSeconds % 60;
  const mmStr = String(mm).padStart(2, "0");
  const ssStr = String(ss).padStart(2, "0");
  if (hh > 0) {
    return `${hh}:${mmStr}:${ssStr}`;
  }
  return `${mmStr}:${ssStr}`;
}

export function formatTimestamp(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const whole = Math.floor(safe);
  const hh = Math.floor(whole / 3600);
  const mm = Math.floor((whole % 3600) / 60);
  const ss = whole % 60;
  if (hh > 0) {
    return `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  }
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

export function normalizeSpeakerKey(speaker: unknown): string | undefined {
  if (typeof speaker === "number" && Number.isInteger(speaker) && speaker >= 0) {
    return String(speaker);
  }
  if (typeof speaker === "string" && speaker.trim()) {
    return speaker.trim();
  }
  return undefined;
}

export function fallbackSpeakerLabel(speaker: unknown): string {
  if (typeof speaker === "number" && Number.isInteger(speaker) && speaker >= 0) {
    return `Speaker ${speaker}`;
  }
  if (typeof speaker === "string" && speaker.trim()) {
    return /^\d+$/.test(speaker.trim())
      ? `Speaker ${speaker.trim()}`
      : speaker.trim();
  }
  return "Unknown";
}

export function resolveSpeakerLabel(
  speaker: unknown,
  labels: Record<string, string>,
): string {
  const key = normalizeSpeakerKey(speaker);
  if (key && labels[key]) {
    return labels[key];
  }
  return fallbackSpeakerLabel(speaker);
}

export function buildTranscriptRows(
  transcript: TranscriptPayload,
): TranscriptRow[] {
  const source = (
    Array.isArray(transcript.utterances) && transcript.utterances.length > 0
      ? transcript.utterances
      : transcript.segments
  ) || [];

  return source
    .filter((row): row is TranscriptSegment => {
      return (
        typeof row === "object" &&
        row !== null &&
        typeof row.start === "number" &&
        typeof row.text === "string"
      );
    })
    .map((row, index) => ({
      id: `${index}-${row.start}`,
      start: row.start,
      end: typeof row.end === "number" ? row.end : undefined,
      text: row.text,
      speaker: row.speaker,
    }));
}

export function attachSpeakers(rows: TranscriptRow[]): {
  rows: TranscriptRow[];
  speakers: SpeakerInfo[];
} {
  const speakers: SpeakerInfo[] = [];
  const byKey = new Map<string, SpeakerInfo>();

  for (const row of rows) {
    const key = normalizeSpeakerKey(row.speaker);
    if (!key) {
      continue;
    }
    const duration =
      typeof row.end === "number" && row.end > row.start
        ? row.end - row.start
        : 0;
    let info = byKey.get(key);
    if (!info) {
      info = {
        key,
        raw: row.speaker,
        fallbackLabel: fallbackSpeakerLabel(row.speaker),
        className: `speaker-${speakers.length % 8}`,
        firstSeen: row.start,
        duration,
      };
      byKey.set(key, info);
      speakers.push(info);
    } else {
      info.duration += duration;
    }
  }

  return {
    speakers,
    rows: rows.map((row) => {
      const key = normalizeSpeakerKey(row.speaker);
      const info = key ? byKey.get(key) : undefined;
      return {
        ...row,
        speakerKey: key,
        speakerClassName: info?.className,
      };
    }),
  };
}
