import { RefObject } from "react";
import { useActiveRow } from "../hooks/useActiveRow";
import {
  formatTimestamp,
  resolveSpeakerLabel,
  type TranscriptRow,
} from "../lib/format";

type TranscriptTableProps = {
  rows: TranscriptRow[];
  speakerLabels: Record<string, string>;
  videoRef: RefObject<HTMLVideoElement>;
};

export default function TranscriptTable({
  rows,
  speakerLabels,
  videoRef,
}: TranscriptTableProps) {
  const activeIndex = useActiveRow(videoRef, rows);
  const showSpeakers = rows.some((row) => row.speakerKey);

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

  if (rows.length === 0) {
    return (
      <section className="transcript-card empty-card">
        <h2>Transcript</h2>
        <p>No transcript rows are available for this job.</p>
      </section>
    );
  }

  return (
    <section className="transcript-card" aria-label="Transcript">
      <div className="section-heading">
        <p className="eyebrow">Transcript</p>
        <h2>{rows.length.toLocaleString()} rows</h2>
      </div>
      <div className="table-scroll">
        <table className="transcript-table">
          <thead>
            <tr>
              <th>Time</th>
              {showSpeakers ? <th>Speaker</th> : null}
              <th>Text</th>
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
                    >
                      {formatTimestamp(row.start)}
                    </button>
                  </td>
                  {showSpeakers ? (
                    <td className="speaker-cell">
                      {row.speakerKey
                        ? resolveSpeakerLabel(row.speaker, speakerLabels)
                        : "-"}
                    </td>
                  ) : null}
                  <td className="transcript-text">{row.text}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
