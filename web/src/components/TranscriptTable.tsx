import { Fragment, ReactNode, RefObject, useEffect, useRef } from "react";
import type { TranscriptNoteEntry } from "../lib/api";
import { useActiveRow } from "../hooks/useActiveRow";
import {
  formatTimestamp,
  resolveSpeakerLabel,
  type TranscriptRow,
} from "../lib/format";
import { splitTextWithMatches, type TranscriptMatches } from "../lib/search";

type TranscriptTableProps = {
  rows: TranscriptRow[];
  speakerLabels: Record<string, string>;
  videoRef: RefObject<HTMLVideoElement>;
  matches: TranscriptMatches;
  activeMatchIndex: number | null;
  hiddenSpeakers: Set<string>;
  totalRowCount: number;
  toolbar?: ReactNode;
  notes?: Record<string, TranscriptNoteEntry>;
  editingRowId?: string | null;
  onOpenNoteEditor?: (rowId: string) => void;
  showCorrections?: boolean;
  onToggleCorrections?: () => void;
  renderRowEditor?: (rowId: string) => ReactNode;
};

export default function TranscriptTable({
  rows,
  speakerLabels,
  videoRef,
  matches,
  activeMatchIndex,
  hiddenSpeakers,
  totalRowCount,
  toolbar,
  notes,
  editingRowId,
  onOpenNoteEditor,
  showCorrections = true,
  onToggleCorrections,
  renderRowEditor,
}: TranscriptTableProps) {
  const activeIndex = useActiveRow(videoRef, rows);
  const showSpeakers = rows.some((row) => row.speakerKey);
  const scrollRef = useRef<HTMLDivElement>(null);
  const noteMap = notes || {};
  const noteCount = Object.keys(noteMap).length;

  const jumpTo = (start: number) => {
    const video = videoRef.current;
    if (!video) {
      return;
    }
    video.currentTime = start;
    void video.play().catch(() => {
      // Browsers may block autoplay. Seeking still succeeds.
    });
  };

  // Scroll the active match into view when it changes.
  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || activeMatchIndex == null) return;
    const selector = `[data-match-index="${activeMatchIndex}"]`;
    const el = scroller.querySelector<HTMLElement>(selector);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeMatchIndex]);

  if (totalRowCount === 0) {
    return (
      <section className="transcript-card" aria-label="Transcript">
        <div className="transcript-card-header">
          <div className="transcript-card-heading">
            <div>
              <p className="eyebrow">Transcript</p>
              <h2>No transcript available</h2>
            </div>
          </div>
        </div>
        <div className="transcript-empty-rows">
          No transcript rows are available for this job yet.
        </div>
      </section>
    );
  }

  if (rows.length === 0) {
    return (
      <section className="transcript-card" aria-label="Transcript">
        <div className="transcript-card-header">
          <div className="transcript-card-heading">
            <div>
              <p className="eyebrow">Transcript</p>
              <h2>No rows to show</h2>
            </div>
            <span className="transcript-card-stat">
              {totalRowCount.toLocaleString()} total rows
            </span>
          </div>
        </div>
        <div className="transcript-empty-rows">
          Every speaker is currently hidden. Re-enable a voice in the Speakers
          panel to see rows again.
        </div>
      </section>
    );
  }

  const colSpan = showSpeakers ? 3 : 2;

  return (
    <section className="transcript-card" aria-label="Transcript">
      <div className="transcript-card-header">
        <div className="transcript-card-heading">
          <div>
            <p className="eyebrow">Transcript</p>
            <h2>
              {rows.length.toLocaleString()} row
              {rows.length === 1 ? "" : "s"}
            </h2>
          </div>
          <span className="transcript-card-stat">
            {hiddenSpeakers.size > 0
              ? `${rows.length.toLocaleString()} of ${totalRowCount.toLocaleString()} shown`
              : `${totalRowCount.toLocaleString()} total`}
            {noteCount > 0 ? (
              <>
                {" · "}
                <span
                  className="transcript-card-notes-chip"
                  aria-label={`${noteCount} rows have corrections or notes`}
                >
                  {noteCount} note{noteCount === 1 ? "" : "s"}
                </span>
              </>
            ) : null}
          </span>
        </div>
        {toolbar}
        {noteCount > 0 && onToggleCorrections ? (
          <div className="transcript-card-toggles">
            <label className="transcript-card-toggle">
              <input
                type="checkbox"
                checked={showCorrections}
                onChange={onToggleCorrections}
              />
              <span>Show corrections</span>
            </label>
          </div>
        ) : null}
      </div>
      <div className="table-scroll" ref={scrollRef}>
        <table className="transcript-table">
          <thead>
            <tr>
              <th scope="col">Time</th>
              {showSpeakers ? <th scope="col">Speaker</th> : null}
              <th scope="col">Text</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const active = index === activeIndex;
              const editing = editingRowId === row.id;
              const entry = noteMap[row.id];
              const hasNote =
                !!(entry && (entry.correction || entry.note));
              const className = [
                row.speakerClassName,
                active ? "active" : null,
                hasNote ? "has-note" : null,
                editing ? "is-editing" : null,
              ]
                .filter(Boolean)
                .join(" ");
              const rowMatches = matches.byRow.get(row.id);
              const showCorrection =
                showCorrections &&
                entry?.correction &&
                entry.correction.length > 0;
              const displayText = showCorrection
                ? entry!.correction!
                : row.text;
              const segments = splitTextWithMatches(displayText, rowMatches);
              return (
                <Fragment key={row.id}>
                  <tr
                    className={className}
                    data-row-id={row.id}
                    aria-current={active ? "true" : undefined}
                  >
                    <td>
                      <button
                        type="button"
                        className="timestamp-button"
                        onClick={() => jumpTo(row.start)}
                        aria-label={`Jump to ${formatTimestamp(row.start)}`}
                      >
                        {formatTimestamp(row.start)}
                      </button>
                    </td>
                    {showSpeakers ? (
                      <td className={`speaker-cell ${row.speakerClassName ?? ""}`}>
                        {row.speakerKey ? (
                          <>
                            <span className="speaker-swatch" aria-hidden />
                            {resolveSpeakerLabel(row.speaker, speakerLabels)}
                          </>
                        ) : (
                          "-"
                        )}
                      </td>
                    ) : null}
                    <td className="transcript-text">
                      <div className="transcript-row-body">
                        <span className="transcript-row-text">
                          {segments.map((seg, segIdx) => {
                            if (seg.kind === "text") {
                              return <span key={segIdx}>{seg.text}</span>;
                            }
                            const isActive =
                              seg.globalIndex === activeMatchIndex;
                            return (
                              <mark
                                key={segIdx}
                                className={`transcript-highlight ${
                                  isActive ? "active" : ""
                                }`}
                                data-match-index={seg.globalIndex}
                              >
                                {seg.text}
                              </mark>
                            );
                          })}
                        </span>
                        <span className="transcript-row-flags">
                          {hasNote ? (
                            <span
                              className="transcript-row-badge"
                              title={
                                entry?.correction
                                  ? "This row has a correction and may have a note"
                                  : "This row has a reviewer note"
                              }
                            >
                              {entry?.correction ? "edited" : "note"}
                            </span>
                          ) : null}
                          {onOpenNoteEditor ? (
                            <button
                              type="button"
                              className="transcript-row-note-button"
                              onClick={() => onOpenNoteEditor(row.id)}
                              aria-expanded={editing}
                              aria-label={
                                hasNote
                                  ? `Edit note for row ${row.id}`
                                  : `Add note to row ${row.id}`
                              }
                            >
                              {hasNote ? "Edit" : "Note"}
                            </button>
                          ) : null}
                        </span>
                      </div>
                      {hasNote && entry?.note && showCorrections ? (
                        <p className="transcript-row-note-preview">
                          {entry.note}
                        </p>
                      ) : null}
                    </td>
                  </tr>
                  {editing && renderRowEditor ? (
                    <tr className="transcript-row-editor-row">
                      <td colSpan={colSpan}>{renderRowEditor(row.id)}</td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
