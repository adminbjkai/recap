import { useEffect, useState } from "react";
import type {
  FrameChapterContext,
  FrameItem,
  FrameReviewEntry,
} from "../lib/api";
import { formatTimestamp } from "../lib/format";

export type FrameCardProps = {
  frame: FrameItem;
  chapter: FrameChapterContext | null;
  pending: FrameReviewEntry | null;
  onChange: (entry: FrameReviewEntry | null) => void;
  disabled?: boolean;
};

type PipeDecision = "keep" | "reject" | "unset";

function decisionTier(entry: FrameItem): {
  label: string;
  tone: "hero" | "supporting" | "rejected" | "unscored";
} {
  const d = entry.decision;
  if (d === "selected_hero") return { label: "hero", tone: "hero" };
  if (d === "selected_supporting")
    return { label: "supporting", tone: "supporting" };
  if (d === "vlm_rejected")
    return { label: "VLM rejected", tone: "rejected" };
  if (d === "duplicate") return { label: "duplicate", tone: "rejected" };
  if (d) return { label: d, tone: "unscored" };
  return { label: "unscored", tone: "unscored" };
}

function renderConfidence(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return `${(value * 100).toFixed(0)}%`;
}

export default function FrameCard({
  frame,
  chapter,
  pending,
  onChange,
  disabled,
}: FrameCardProps) {
  const storedDecision: PipeDecision =
    frame.review?.decision === "keep"
      ? "keep"
      : frame.review?.decision === "reject"
        ? "reject"
        : "unset";
  const storedNote = frame.review?.note || "";

  // Local editable state — starts from pending (if the parent already
  // has an unsaved change) or the stored overlay.
  const initialDecision: PipeDecision = (pending?.decision as PipeDecision) ?? storedDecision;
  const initialNote = pending?.note ?? storedNote;

  const [decision, setDecision] = useState<PipeDecision>(initialDecision);
  const [note, setNote] = useState<string>(initialNote);

  useEffect(() => {
    setDecision((pending?.decision as PipeDecision) ?? storedDecision);
    setNote(pending?.note ?? storedNote);
  }, [pending, storedDecision, storedNote]);

  function propagate(
    nextDecision: PipeDecision,
    nextNote: string,
  ): void {
    if (nextDecision === storedDecision && nextNote === storedNote) {
      onChange(null);
      return;
    }
    onChange({ decision: nextDecision, note: nextNote });
  }

  const tier = decisionTier(frame);
  const overlayActive = storedDecision !== "unset";
  const dirty =
    decision !== storedDecision || note.trim() !== storedNote.trim();
  const ts = frame.timestamp_seconds;

  return (
    <article
      className={`frame-card frame-card--${tier.tone}${
        overlayActive ? " frame-card--overlay" : ""
      }${dirty ? " frame-card--dirty" : ""}`}
      aria-label={`Frame ${frame.frame_file}`}
    >
      <header className="frame-card-head">
        <div className="frame-card-title">
          <span className="frame-card-ts" title="Midpoint timestamp">
            {typeof ts === "number" ? formatTimestamp(ts) : "—"}
          </span>
          <span className="frame-card-name" title={frame.frame_file}>
            {frame.frame_file}
          </span>
        </div>
        <div className="frame-card-pills" aria-label="Algorithm output">
          <span className={`frame-pill frame-pill--${tier.tone}`}>
            {tier.label}
          </span>
          {frame.shortlist_decision ? (
            <span className="frame-pill frame-pill--muted">
              shortlist: {frame.shortlist_decision}
            </span>
          ) : null}
          {typeof frame.rank === "number" ? (
            <span className="frame-pill frame-pill--muted">
              rank {frame.rank}
            </span>
          ) : null}
          {overlayActive ? (
            <span
              className={`frame-pill frame-pill--review-${storedDecision}`}
              title="User review overlay"
            >
              overlay: {storedDecision}
            </span>
          ) : null}
        </div>
      </header>

      <div className="frame-card-body">
        {frame.image_url ? (
          <img
            className="frame-card-image"
            src={frame.image_url}
            alt={`Candidate frame ${frame.frame_file}`}
            loading="lazy"
          />
        ) : (
          <div
            className="frame-card-image frame-card-image--missing"
            role="img"
            aria-label={`Image missing for ${frame.frame_file}`}
          >
            image missing
          </div>
        )}

        <dl className="frame-card-meta">
          {chapter ? (
            <div>
              <dt>Chapter</dt>
              <dd>
                #{chapter.index} · {chapter.display_title}
              </dd>
            </div>
          ) : null}
          {typeof frame.composite_score === "number" ? (
            <div>
              <dt>Composite score</dt>
              <dd>{frame.composite_score.toFixed(3)}</dd>
            </div>
          ) : null}
          {typeof frame.clip_similarity === "number" ? (
            <div>
              <dt>CLIP similarity</dt>
              <dd>{frame.clip_similarity.toFixed(3)}</dd>
            </div>
          ) : null}
          {typeof frame.text_novelty === "number" ? (
            <div>
              <dt>Text novelty</dt>
              <dd>{frame.text_novelty.toFixed(3)}</dd>
            </div>
          ) : null}
          {frame.verification?.relevance ? (
            <div>
              <dt>VLM</dt>
              <dd>
                {frame.verification.relevance}
                {renderConfidence(frame.verification.confidence) ? (
                  <>
                    {" · "}
                    {renderConfidence(frame.verification.confidence)}
                  </>
                ) : null}
              </dd>
            </div>
          ) : null}
          {frame.duplicate_of ? (
            <div>
              <dt>Duplicate of</dt>
              <dd>
                <code>{frame.duplicate_of}</code>
              </dd>
            </div>
          ) : null}
        </dl>
      </div>

      {frame.verification?.caption ? (
        <blockquote className="frame-card-caption">
          {frame.verification.caption}
        </blockquote>
      ) : null}

      {frame.ocr_text && frame.ocr_text.length > 0 ? (
        <details className="frame-card-ocr">
          <summary>OCR text</summary>
          <pre>{frame.ocr_text}</pre>
        </details>
      ) : null}

      <fieldset
        className="frame-card-review"
        aria-label="Review decision"
        disabled={disabled}
      >
        <legend>Review</legend>
        <div className="frame-review-controls">
          <label
            className={`frame-review-radio${
              decision === "keep" ? " frame-review-radio--active" : ""
            }`}
          >
            <input
              type="radio"
              name={`review-${frame.frame_file}`}
              value="keep"
              checked={decision === "keep"}
              onChange={() => {
                setDecision("keep");
                propagate("keep", note);
              }}
            />
            <span>Keep</span>
          </label>
          <label
            className={`frame-review-radio${
              decision === "reject" ? " frame-review-radio--active" : ""
            }`}
          >
            <input
              type="radio"
              name={`review-${frame.frame_file}`}
              value="reject"
              checked={decision === "reject"}
              onChange={() => {
                setDecision("reject");
                propagate("reject", note);
              }}
            />
            <span>Reject</span>
          </label>
          <label
            className={`frame-review-radio${
              decision === "unset" ? " frame-review-radio--active" : ""
            }`}
          >
            <input
              type="radio"
              name={`review-${frame.frame_file}`}
              value="unset"
              checked={decision === "unset"}
              onChange={() => {
                setDecision("unset");
                propagate("unset", note);
              }}
            />
            <span>Unset</span>
          </label>
        </div>
        <label className="frame-review-note">
          <span>Note (optional, ≤ 300 chars)</span>
          <textarea
            rows={2}
            maxLength={300}
            value={note}
            onChange={(e) => {
              const nextNote = e.target.value;
              setNote(nextNote);
              propagate(decision, nextNote);
            }}
            placeholder="Why keep or reject?"
          />
        </label>
      </fieldset>
    </article>
  );
}
