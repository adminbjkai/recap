import { FormEvent } from "react";
import type { SpeakerInfo } from "../lib/format";

type SpeakerRenameFormProps = {
  speakers: SpeakerInfo[];
  labels: Record<string, string>;
  saving?: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (labels: Record<string, string>) => void | Promise<void>;
};

export default function SpeakerRenameForm({
  speakers,
  labels,
  saving = false,
  error = null,
  onCancel,
  onSave,
}: SpeakerRenameFormProps) {
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const next: Record<string, string> = {};
    for (const speaker of speakers) {
      const value = data.get(`speaker-${speaker.key}`);
      next[speaker.key] = typeof value === "string" ? value.trim() : "";
    }
    void onSave(next);
  };

  return (
    <form className="rename-form" onSubmit={handleSubmit}>
      <div className="rename-grid">
        {speakers.map((speaker) => (
          <label key={speaker.key} className="rename-field">
            <span>{speaker.fallbackLabel}</span>
            <input
              name={`speaker-${speaker.key}`}
              defaultValue={labels[speaker.key] ?? ""}
              placeholder={speaker.fallbackLabel}
              maxLength={80}
              autoComplete="off"
            />
          </label>
        ))}
      </div>
      <p className="rename-note">
        Names are saved as an overlay. They do not rewrite transcript.json or
        exported reports yet.
      </p>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="rename-actions">
        <button className="primary-button" type="submit" disabled={saving}>
          {saving ? "Saving..." : "Save names"}
        </button>
        <button type="button" className="ghost-button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
