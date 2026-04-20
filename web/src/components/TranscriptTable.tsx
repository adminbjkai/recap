import { ReactNode, RefObject, useEffect, useRef } from "react";
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
}: TranscriptTableProps) {
  const activeIndex = useActiveRow(videoRef, rows);
  const showSpeakers = rows.some((row) => row.speakerKey);
  const scrollRef = useRef<HTMLDivElement>(null);

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
          </span>
        </div>
        {toolbar}
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
              const className = [
                row.speakerClassName,
                active ? "active" : null,
              ]
                .filter(Boolean)
                .join(" ");
              const rowMatches = matches.byRow.get(row.id);
              const segments = splitTextWithMatches(row.text, rowMatches);
              return (
                <tr
                  key={row.id}
                  className={className}
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
                    {segments.map((seg, segIdx) => {
                      if (seg.kind === "text") {
                        return (
                          <span key={segIdx}>{seg.text}</span>
                        );
                      }
                      const isActive = seg.globalIndex === activeMatchIndex;
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
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
