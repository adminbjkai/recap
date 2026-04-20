import { useState } from "react";
import SpeakerRenameForm from "./SpeakerRenameForm";
import type { SpeakerInfo } from "../lib/format";
import { resolveSpeakerLabel } from "../lib/format";

type SpeakerLegendProps = {
  speakers: SpeakerInfo[];
  labels: Record<string, string>;
  hiddenSpeakers: Set<string>;
  onToggleSpeaker: (key: string) => void;
  onShowAllSpeakers: () => void;
  onSave: (labels: Record<string, string>) => Promise<void>;
};

export default function SpeakerLegend({
  speakers,
  labels,
  hiddenSpeakers,
  onToggleSpeaker,
  onShowAllSpeakers,
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

  const anyHidden = speakers.some((s) => hiddenSpeakers.has(s.key));

  return (
    <section className="speaker-panel" aria-label="Speakers">
      <div className="speaker-panel-header">
        <div>
          <p className="eyebrow">Speakers</p>
          <h2>
            {speakers.length} voice{speakers.length === 1 ? "" : "s"}
          </h2>
        </div>
        <button
          type="button"
          className="ghost-button"
          onClick={() => setEditing((value) => !value)}
          aria-expanded={editing}
        >
          {editing ? "Close" : "Rename"}
        </button>
      </div>

      <p className="speaker-panel-hint">
        Click a voice to hide or show its rows.
      </p>

      <ul className="speaker-filter-list" role="list">
        {speakers.map((speaker) => {
          const visible = !hiddenSpeakers.has(speaker.key);
          return (
            <li key={speaker.key}>
              <button
                type="button"
                className={`speaker-filter-pill ${speaker.className}`}
                aria-pressed={visible}
                onClick={() => onToggleSpeaker(speaker.key)}
                title={
                  visible
                    ? "Hide this speaker's rows"
                    : "Show this speaker's rows"
                }
              >
                <span className="dot" aria-hidden />
                {resolveSpeakerLabel(speaker.raw, labels)}
              </button>
            </li>
          );
        })}
        {anyHidden ? (
          <li>
            <button
              type="button"
              className="speaker-filter-reset"
              onClick={onShowAllSpeakers}
            >
              Show all
            </button>
          </li>
        ) : null}
      </ul>

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
