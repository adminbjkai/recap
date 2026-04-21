import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { TranscriptNoteEntry } from "../lib/api";
import { formatTimestamp } from "../lib/format";

export type TranscriptNotesEditorProps = {
  rowId: string;
  canonicalText: string;
  timestamp: number;
  initial: TranscriptNoteEntry | null;
  onSave: (entry: { correction: string; note: string }) => Promise<void>;
  onCancel: () => void;
  saving?: boolean;
  error?: string | null;
};

const CORRECTION_MAX = 2000;
const NOTE_MAX = 1000;

export default function TranscriptNotesEditor({
  rowId,
  canonicalText,
  timestamp,
  initial,
  onSave,
  onCancel,
  saving,
  error,
}: TranscriptNotesEditorProps) {
  const [correction, setCorrection] = useState<string>(
    initial?.correction ?? "",
  );
  const [note, setNote] = useState<string>(initial?.note ?? "");
  const correctionRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    correctionRef.current?.focus();
  }, []);

  useEffect(() => {
    setCorrection(initial?.correction ?? "");
    setNote(initial?.note ?? "");
  }, [initial, rowId]);

  const canSave =
    !saving &&
    (correction.trim().length <= CORRECTION_MAX) &&
    (note.trim().length <= NOTE_MAX);

  const handleSave = useCallback(async () => {
    if (!canSave) return;
    await onSave({ correction, note });
  }, [canSave, correction, note, onSave]);

  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void handleSave();
      } else if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    },
    [handleSave, onCancel],
  );

  const handleClear = useCallback(() => {
    setCorrection("");
    setNote("");
  }, []);

  const hasStored =
    !!(initial?.correction || initial?.note);

  return (
    <div
      className="transcript-notes-editor"
      role="region"
      aria-label={`Edit note for row ${rowId}`}
    >
      <header className="transcript-notes-editor-head">
        <p className="eyebrow">Row · {rowId}</p>
        <p className="transcript-notes-editor-ts">
          {formatTimestamp(timestamp)}
        </p>
      </header>

      <div className="transcript-notes-canonical">
        <p className="transcript-notes-canonical-label">
          Canonical transcript (unchanged)
        </p>
        <p className="transcript-notes-canonical-text">
          {canonicalText}
        </p>
      </div>

      <label className="transcript-notes-field">
        <span>Correction (overlay, ≤ {CORRECTION_MAX} chars)</span>
        <textarea
          ref={correctionRef}
          value={correction}
          onChange={(e) => setCorrection(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={CORRECTION_MAX}
          rows={3}
          placeholder="Rewrite this line (leave blank to keep the canonical text)"
        />
        <span className="transcript-notes-field-hint">
          {correction.trim().length} / {CORRECTION_MAX}
        </span>
      </label>

      <label className="transcript-notes-field">
        <span>Private note (≤ {NOTE_MAX} chars)</span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={handleKeyDown}
          maxLength={NOTE_MAX}
          rows={2}
          placeholder="Reviewer note — not shown in exports yet."
        />
        <span className="transcript-notes-field-hint">
          {note.trim().length} / {NOTE_MAX}
        </span>
      </label>

      {error ? (
        <p className="form-error" role="status">
          {error}
        </p>
      ) : null}

      <p className="transcript-notes-privacy">
        Your canonical <code>transcript.json</code> stays untouched.
        Edits land in a separate <code>transcript_notes.json</code>
        {" "}overlay next to the other review overlays. Exporter
        integration is tracked as a follow-up — this overlay only
        drives the React workspace today.
      </p>

      <div className="transcript-notes-actions">
        <button
          type="button"
          className="primary-button"
          onClick={handleSave}
          disabled={!canSave}
          aria-busy={saving || undefined}
        >
          {saving ? "Saving…" : "Save review"}
        </button>
        <button
          type="button"
          className="ghost-button"
          onClick={onCancel}
          disabled={saving}
        >
          Cancel
        </button>
        {hasStored ? (
          <button
            type="button"
            className="text-link transcript-notes-clear"
            onClick={handleClear}
            disabled={saving}
          >
            Clear fields
          </button>
        ) : null}
        <span className="transcript-notes-kbd" aria-hidden>
          <kbd>⌘</kbd>/<kbd>Ctrl</kbd>+<kbd>Enter</kbd> save ·{" "}
          <kbd>Esc</kbd> cancel
        </span>
      </div>
    </div>
  );
}
