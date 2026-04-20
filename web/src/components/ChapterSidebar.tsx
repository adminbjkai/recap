import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from "react";
import type { ChapterEntry } from "../lib/api";
import { formatTimestamp } from "../lib/format";

export type ChapterSidebarProps = {
  chapters: ChapterEntry[];
  videoRef: RefObject<HTMLVideoElement | null>;
  activeIndex: number | null;
  onSeek: (chapter: ChapterEntry) => void;
  onSaveTitle: (index: number, title: string) => Promise<void>;
  saveError: string | null;
  onDismissError?: () => void;
  hasCandidateArtifact: boolean;
  hasInsightsArtifact: boolean;
};

function formatRange(
  start: number | null,
  end: number | null,
): string {
  if (typeof start !== "number") return "—";
  const startStr = formatTimestamp(start);
  if (typeof end !== "number") return `${startStr}`;
  return `${startStr} → ${formatTimestamp(end)}`;
}

export default function ChapterSidebar({
  chapters,
  videoRef,
  activeIndex,
  onSeek,
  onSaveTitle,
  saveError,
  onDismissError,
  hasCandidateArtifact,
  hasInsightsArtifact,
}: ChapterSidebarProps) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [savingIndex, setSavingIndex] = useState<number | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingIndex !== null) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editingIndex]);

  const startEdit = useCallback((chapter: ChapterEntry) => {
    setEditingIndex(chapter.index);
    setDraft(chapter.custom_title ?? chapter.fallback_title ?? "");
    setLocalError(null);
    onDismissError?.();
  }, [onDismissError]);

  const cancelEdit = useCallback(() => {
    setEditingIndex(null);
    setDraft("");
    setLocalError(null);
  }, []);

  const commitEdit = useCallback(async () => {
    if (editingIndex === null) return;
    const trimmed = draft.trim();
    if (trimmed.length > 120) {
      setLocalError("Title is too long (max 120 characters).");
      return;
    }
    setSavingIndex(editingIndex);
    setLocalError(null);
    try {
      await onSaveTitle(editingIndex, trimmed);
      setEditingIndex(null);
      setDraft("");
    } catch (err) {
      setLocalError(
        err instanceof Error ? err.message : "Could not save title.",
      );
    } finally {
      setSavingIndex(null);
    }
  }, [draft, editingIndex, onSaveTitle]);

  const handleInputKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        e.preventDefault();
        void commitEdit();
      } else if (e.key === "Escape") {
        e.preventDefault();
        cancelEdit();
      }
    },
    [cancelEdit, commitEdit],
  );

  const handleRowKeyDown = useCallback(
    (
      e: ReactKeyboardEvent<HTMLButtonElement>,
      chapter: ChapterEntry,
    ) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onSeek(chapter);
      }
    },
    [onSeek],
  );

  if (chapters.length === 0) {
    return (
      <section className="chapters-card" aria-label="Chapters">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Chapters</p>
            <h2>No chapters yet</h2>
          </div>
        </div>
        <p className="chapters-empty">
          Chapters appear when either <code>chapter_candidates.json</code>
          {" "}or <code>insights.json</code> is present. Generate them from
          the job dashboard via <strong>Generate insights</strong> or
          <strong>Generate rich report</strong>, or from the CLI:
        </p>
        <pre className="chapters-empty-cmd">
{`.venv/bin/python -m recap insights --job jobs/<id>
.venv/bin/python -m recap chapters --job jobs/<id>`}
        </pre>
      </section>
    );
  }

  // Some upstream artifacts may have been present but empty; surface
  // that so users can tell they came from insights vs. candidates.
  const provenance: string[] = [];
  if (hasCandidateArtifact) provenance.push("chapter_candidates.json");
  if (hasInsightsArtifact) provenance.push("insights.json");

  return (
    <section className="chapters-card" aria-label="Chapters">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Chapters</p>
          <h2>{chapters.length} chapters</h2>
        </div>
        {provenance.length > 0 ? (
          <span className="chapters-provenance" title="Source artifacts">
            from {provenance.join(" + ")}
          </span>
        ) : null}
      </div>

      {saveError ? (
        <p className="form-error" role="status">
          {saveError}
        </p>
      ) : null}

      <ol className="chapter-list">
        {chapters.map((chapter) => {
          const isActive = activeIndex === chapter.index;
          const isEditing = editingIndex === chapter.index;
          const isSaving = savingIndex === chapter.index;
          const titleIsCustom = typeof chapter.custom_title === "string";
          return (
            <li
              key={chapter.index}
              className={`chapter-row ${
                isActive ? "chapter-row--active" : ""
              }`}
              aria-current={isActive ? "true" : undefined}
            >
              <div className="chapter-row-head">
                <button
                  type="button"
                  className="chapter-seek"
                  onClick={() => onSeek(chapter)}
                  onKeyDown={(e) => handleRowKeyDown(e, chapter)}
                  aria-label={`Seek to chapter ${chapter.index}: ${chapter.display_title}`}
                  disabled={typeof chapter.start_seconds !== "number"}
                >
                  <span className="chapter-index">
                    {isActive ? "▶" : ""}
                    {String(chapter.index).padStart(2, "0")}
                  </span>
                  {isEditing ? (
                    <span className="chapter-title-edit">
                      <input
                        ref={inputRef}
                        type="text"
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={handleInputKeyDown}
                        onClick={(e) => e.stopPropagation()}
                        maxLength={120}
                        aria-label={`Edit title for chapter ${chapter.index}`}
                      />
                    </span>
                  ) : (
                    <span className="chapter-title">
                      {chapter.display_title}
                      {titleIsCustom ? (
                        <span className="chapter-title-badge" title="Custom title saved in chapter_titles.json">
                          custom
                        </span>
                      ) : null}
                    </span>
                  )}
                </button>
                <span className="chapter-range">
                  {formatRange(chapter.start_seconds, chapter.end_seconds)}
                </span>
              </div>

              {isEditing ? (
                <div className="chapter-edit-actions">
                  <button
                    type="button"
                    className="primary-button primary-button--sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      void commitEdit();
                    }}
                    disabled={isSaving}
                  >
                    {isSaving ? "Saving…" : "Save"}
                  </button>
                  <button
                    type="button"
                    className="ghost-button ghost-button--sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      cancelEdit();
                    }}
                    disabled={isSaving}
                  >
                    Cancel
                  </button>
                  {titleIsCustom ? (
                    <span className="chapter-edit-hint">
                      Clear the field and save to remove the custom
                      title.
                    </span>
                  ) : null}
                  {localError ? (
                    <span className="form-error" role="status">
                      {localError}
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="chapter-meta">
                  <button
                    type="button"
                    className="chapter-rename"
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(chapter);
                    }}
                    aria-label={`Rename chapter ${chapter.index}`}
                  >
                    Rename
                  </button>
                  {chapter.summary ? (
                    <p className="chapter-summary">{chapter.summary}</p>
                  ) : null}
                  {chapter.bullets && chapter.bullets.length > 0 ? (
                    <ul className="chapter-bullets">
                      {chapter.bullets.map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  ) : null}
                  {chapter.action_items &&
                  chapter.action_items.length > 0 ? (
                    <ul className="chapter-actions">
                      {chapter.action_items.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {!videoRef.current ? (
        <p className="chapters-hint">
          Seek buttons jump the video when it loads. Video not yet
          initialized.
        </p>
      ) : null}
    </section>
  );
}
