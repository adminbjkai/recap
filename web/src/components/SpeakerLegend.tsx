import { useState } from "react";
import SpeakerRenameForm from "./SpeakerRenameForm";
import type { SpeakerInfo } from "../lib/format";
import { resolveSpeakerLabel } from "../lib/format";

type SpeakerLegendProps = {
  speakers: SpeakerInfo[];
  labels: Record<string, string>;
  onSave: (labels: Record<string, string>) => Promise<void>;
};

export default function SpeakerLegend({
  speakers,
  labels,
  onSave,
}: SpeakerLegendProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (speakers.length === 0) {
    return null;
  }

  const handleSave = async (nextLabels: Record<string, string>) => {
    setSaving(true);
    setError(null);
    try {
      await onSave(nextLabels);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save names.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="speaker-panel" aria-label="Speakers">
      <div className="speaker-panel-header">
        <div>
          <p className="eyebrow">Speakers</p>
          <h2>{speakers.length} voice{speakers.length === 1 ? "" : "s"}</h2>
        </div>
        <button
          type="button"
          className="ghost-button"
          onClick={() => setEditing((value) => !value)}
        >
          {editing ? "Close" : "Rename"}
        </button>
      </div>

      <div className="speaker-pills">
        {speakers.map((speaker) => (
          <span
            key={speaker.key}
            className={`speaker-pill ${speaker.className}`}
          >
            {resolveSpeakerLabel(speaker.raw, labels)}
          </span>
        ))}
      </div>

      {editing ? (
        <SpeakerRenameForm
          speakers={speakers}
          labels={labels}
          saving={saving}
          error={error}
          onSave={handleSave}
          onCancel={() => setEditing(false)}
        />
      ) : null}
    </section>
  );
}
