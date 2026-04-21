import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getChapters,
  getJob,
  getSpeakerNames,
  getTranscript,
  getTranscriptNotes,
  saveChapterTitles,
  saveSpeakerNames,
  saveTranscriptNotes,
  type ChapterEntry,
  type ChapterListPayload,
  type JobSummary,
  type SpeakerNamesDoc,
  type TranscriptNotesDoc,
  type TranscriptPayload,
} from "../lib/api";
import { attachSpeakers, buildTranscriptRows } from "../lib/format";
import { computeTranscriptMatches } from "../lib/search";
import ChapterSidebar from "../components/ChapterSidebar";
import SpeakerLegend from "../components/SpeakerLegend";
import TranscriptNotesEditor from "../components/TranscriptNotesEditor";
import TranscriptSearchBar from "../components/TranscriptSearchBar";
import TranscriptTable from "../components/TranscriptTable";
import VideoPlayer from "../components/VideoPlayer";

type LoadState =
  | { status: "loading" }
  | {
      status: "loaded";
      job: JobSummary;
      transcript: TranscriptPayload;
      names: SpeakerNamesDoc;
      chapters: ChapterListPayload;
      notes: TranscriptNotesDoc;
    }
  | { status: "error"; message: string };

function findActiveChapterIndex(
  chapters: ChapterEntry[],
  t: number,
): number | null {
  if (!Number.isFinite(t) || chapters.length === 0) return null;
  let active: number | null = null;
  for (const ch of chapters) {
    if (typeof ch.start_seconds !== "number") continue;
    if (t + 0.0001 < ch.start_seconds) break;
    active = ch.index;
    if (typeof ch.end_seconds === "number" && t < ch.end_seconds) {
      break;
    }
  }
  return active;
}

export default function TranscriptWorkspacePage() {
  const { id } = useParams();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [savedPulse, setSavedPulse] = useState(false);
  const [query, setQuery] = useState("");
  const [activeMatchIndex, setActiveMatchIndex] = useState<number | null>(
    null,
  );
  const [hiddenSpeakers, setHiddenSpeakers] = useState<Set<string>>(
    () => new Set(),
  );
  const [activeChapterIndex, setActiveChapterIndex] = useState<
    number | null
  >(null);
  const [chapterSaveError, setChapterSaveError] = useState<string | null>(
    null,
  );
  const [editingRowId, setEditingRowId] = useState<string | null>(null);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteSaveError, setNoteSaveError] = useState<string | null>(null);
  const [notesSavedPulse, setNotesSavedPulse] = useState(false);
  const [showCorrections, setShowCorrections] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!id) {
      setState({ status: "error", message: "Missing job id." });
      return;
    }

    setState({ status: "loading" });
    Promise.all([
      getJob(id),
      getTranscript(id),
      getSpeakerNames(id),
      getChapters(id),
      getTranscriptNotes(id),
    ])
      .then(([job, transcript, names, chapters, notes]) => {
        if (!cancelled) {
          setState({
            status: "loaded",
            job,
            transcript,
            names,
            chapters,
            notes,
          });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setState({
            status: "error",
            message:
              err instanceof Error ? err.message : "Could not load job.",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  const built = useMemo(() => {
    if (state.status !== "loaded") {
      return {
        speakers: [] as ReturnType<typeof attachSpeakers>["speakers"],
        rows: [] as ReturnType<typeof attachSpeakers>["rows"],
      };
    }
    return attachSpeakers(buildTranscriptRows(state.transcript));
  }, [state]);

  const visibleRows = useMemo(() => {
    if (hiddenSpeakers.size === 0) return built.rows;
    return built.rows.filter(
      (row) => !row.speakerKey || !hiddenSpeakers.has(row.speakerKey),
    );
  }, [built.rows, hiddenSpeakers]);

  const matches = useMemo(
    () => computeTranscriptMatches(visibleRows, query),
    [visibleRows, query],
  );

  // When the match set changes, reset the cursor so it stays valid.
  useEffect(() => {
    if (matches.matches.length === 0) {
      setActiveMatchIndex(null);
      return;
    }
    setActiveMatchIndex((prev) => {
      if (prev == null) return 0;
      if (prev >= matches.matches.length) return 0;
      return prev;
    });
  }, [matches]);

  const handleSaveNames = async (labels: Record<string, string>) => {
    if (!id || state.status !== "loaded") {
      return;
    }
    const saved = await saveSpeakerNames(id, labels);
    setState({ ...state, names: saved });
    setSavedPulse(true);
    window.setTimeout(() => setSavedPulse(false), 2200);
  };

  const handleSeekChapter = useCallback((chapter: ChapterEntry) => {
    const v = videoRef.current;
    if (!v || typeof chapter.start_seconds !== "number") return;
    try {
      v.currentTime = chapter.start_seconds;
      const playPromise = v.play();
      if (playPromise && typeof playPromise.then === "function") {
        playPromise.catch(() => {
          // Autoplay may be blocked until the user interacts with the
          // page. Seeking still worked — leave the player paused.
        });
      }
    } catch (_err) {
      /* ignore — some browsers throw when not loaded yet */
    }
    setActiveChapterIndex(chapter.index);
  }, []);

  const openNoteEditor = useCallback((rowId: string) => {
    setEditingRowId((prev) => (prev === rowId ? null : rowId));
    setNoteSaveError(null);
  }, []);

  const closeNoteEditor = useCallback(() => {
    setEditingRowId(null);
    setNoteSaveError(null);
  }, []);

  const handleSaveNote = useCallback(
    async (
      rowId: string,
      payload: { correction: string; note: string },
    ) => {
      if (!id) return;
      if (state.status !== "loaded") return;
      setNoteSaving(true);
      setNoteSaveError(null);
      try {
        // Send just this row. The server merges with the existing
        // overlay and empty fields clear the field / mapping.
        const saved = await saveTranscriptNotes(id, {
          [rowId]: {
            correction: payload.correction,
            note: payload.note,
          },
        });
        setState((curr) =>
          curr.status === "loaded"
            ? { ...curr, notes: saved }
            : curr,
        );
        setEditingRowId(null);
        setNotesSavedPulse(true);
        window.setTimeout(() => setNotesSavedPulse(false), 2200);
      } catch (err) {
        setNoteSaveError(
          err instanceof Error
            ? err.message
            : "Could not save transcript note.",
        );
      } finally {
        setNoteSaving(false);
      }
    },
    [id, state],
  );

  const handleSaveChapterTitle = useCallback(
    async (index: number, title: string) => {
      if (!id) return;
      if (state.status !== "loaded") return;
      const next: Record<string, string> = {
        ...state.chapters.overlay.titles,
      };
      if (title.trim()) {
        next[String(index)] = title.trim();
      } else {
        delete next[String(index)];
      }
      try {
        setChapterSaveError(null);
        await saveChapterTitles(id, next);
        // Refresh the chapter list so custom_title/display_title
        // reflect the new overlay without a page reload.
        const fresh = await getChapters(id);
        setState((curr) =>
          curr.status === "loaded" ? { ...curr, chapters: fresh } : curr,
        );
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : "Could not save chapter title.";
        setChapterSaveError(msg);
        throw err;
      }
    },
    [id, state],
  );

  // Track active chapter based on video playback so the sidebar can
  // mirror the legacy transcript active-row highlight pattern.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (state.status !== "loaded") return;
    const chapters = state.chapters.chapters;
    if (chapters.length === 0) return;
    const update = () => {
      const t = v.currentTime;
      setActiveChapterIndex((prev) => {
        const next = findActiveChapterIndex(chapters, t);
        return next === prev ? prev : next;
      });
    };
    update();
    v.addEventListener("timeupdate", update);
    v.addEventListener("seeking", update);
    v.addEventListener("play", update);
    return () => {
      v.removeEventListener("timeupdate", update);
      v.removeEventListener("seeking", update);
      v.removeEventListener("play", update);
    };
  }, [state]);

  const toggleSpeaker = useCallback((key: string) => {
    setHiddenSpeakers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const showAllSpeakers = useCallback(() => {
    setHiddenSpeakers(new Set());
  }, []);

  const gotoNext = useCallback(() => {
    if (matches.matches.length === 0) return;
    setActiveMatchIndex((prev) => {
      const base = prev == null ? -1 : prev;
      return (base + 1) % matches.matches.length;
    });
  }, [matches.matches.length]);

  const gotoPrev = useCallback(() => {
    if (matches.matches.length === 0) return;
    setActiveMatchIndex((prev) => {
      const base = prev == null ? matches.matches.length : prev;
      return (base - 1 + matches.matches.length) % matches.matches.length;
    });
  }, [matches.matches.length]);

  if (state.status === "loading") {
    return (
      <main className="workspace">
        <section className="hero-card skeleton-card" aria-busy="true">
          <p className="eyebrow">Recap transcript workspace</p>
          <h1>Loading transcript…</h1>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
          <div className="skeleton-line" />
        </section>
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="workspace">
        <section className="hero-card error-card">
          <p className="eyebrow">Recap transcript workspace</p>
          <h1>Unable to load transcript</h1>
          <p>{state.message}</p>
          <div className="job-card-actions">
            <Link className="primary-button" to="/">
              Back to jobs
            </Link>
            <a className="ghost-button" href="/">
              Legacy dashboard
            </a>
          </div>
        </section>
      </main>
    );
  }

  const { job, transcript, names, chapters, notes } = state;
  const noteItems = notes.items || {};
  const title = job.original_filename || job.job_id;
  const hasVideo = Boolean(job.artifacts.analysis_mp4);
  const status = job.status || "unknown";
  const transcriptMetaParts = [
    transcript.engine ? transcript.engine : null,
    transcript.model ? transcript.model : null,
    transcript.language ? transcript.language : null,
    typeof transcript.duration === "number"
      ? formatDuration(transcript.duration)
      : null,
  ].filter(Boolean);

  return (
    <main className="workspace">
      <header className="workspace-header">
        <div className="workspace-title-group">
          <p className="eyebrow">Transcript workspace</p>
          <h1>{title}</h1>
          <p className="workspace-meta">
            <span
              className={`status-badge status-${status}`}
              aria-label={`Status: ${status}`}
            >
              {status}
            </span>
            {transcriptMetaParts.length > 0 ? (
              <>
                <span className="sep" aria-hidden>
                  ·
                </span>
                <span>{transcriptMetaParts.join(" · ")}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="workspace-actions">
          <Link
            className="ghost-button"
            to={`/job/${encodeURIComponent(job.job_id)}`}
          >
            ← Dashboard
          </Link>
        </div>
      </header>

      <section className="workspace-grid">
        <aside className="left-rail">
          {hasVideo ? (
            <VideoPlayer
              ref={videoRef}
              src={job.urls.analysis_mp4}
              title={title}
            />
          ) : (
            <section
              className="video-card missing-video"
              aria-label="Video unavailable"
            >
              <p className="eyebrow">Video unavailable</p>
              <p>
                <code>analysis.mp4</code> is not present for this job. The
                transcript is still fully navigable.
              </p>
            </section>
          )}
          <SpeakerLegend
            speakers={built.speakers}
            labels={names.speakers}
            hiddenSpeakers={hiddenSpeakers}
            onToggleSpeaker={toggleSpeaker}
            onShowAllSpeakers={showAllSpeakers}
            onSave={handleSaveNames}
          />
          {savedPulse ? (
            <p className="save-toast" role="status">
              Speaker names saved.
            </p>
          ) : null}
          <ChapterSidebar
            chapters={chapters.chapters}
            videoRef={videoRef}
            activeIndex={activeChapterIndex}
            onSeek={handleSeekChapter}
            onSaveTitle={handleSaveChapterTitle}
            saveError={chapterSaveError}
            onDismissError={() => setChapterSaveError(null)}
            hasCandidateArtifact={chapters.sources.chapter_candidates}
            hasInsightsArtifact={chapters.sources.insights}
          />
        </aside>

        <TranscriptTable
          rows={visibleRows}
          speakerLabels={names.speakers}
          videoRef={videoRef}
          matches={matches}
          activeMatchIndex={activeMatchIndex}
          hiddenSpeakers={hiddenSpeakers}
          totalRowCount={built.rows.length}
          notes={noteItems}
          editingRowId={editingRowId}
          onOpenNoteEditor={openNoteEditor}
          showCorrections={showCorrections}
          onToggleCorrections={() =>
            setShowCorrections((v) => !v)
          }
          renderRowEditor={(rowId) => {
            const row = built.rows.find((r) => r.id === rowId);
            if (!row) return null;
            return (
              <TranscriptNotesEditor
                rowId={rowId}
                canonicalText={row.text}
                timestamp={row.start}
                initial={noteItems[rowId] ?? null}
                onSave={(payload) => handleSaveNote(rowId, payload)}
                onCancel={closeNoteEditor}
                saving={noteSaving}
                error={noteSaveError}
              />
            );
          }}
          toolbar={
            <TranscriptSearchBar
              query={query}
              onQueryChange={setQuery}
              matchCount={matches.matches.length}
              activeMatchIndex={activeMatchIndex}
              onPrev={gotoPrev}
              onNext={gotoNext}
            />
          }
        />
        {notesSavedPulse ? (
          <p className="save-toast transcript-notes-toast" role="status">
            Transcript note saved.
          </p>
        ) : null}
      </section>
      <footer className="workspace-footer">
        <Link className="text-link" to="/">
          Open another workspace
        </Link>
      </footer>
    </main>
  );
}

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }
  if (m > 0) {
    return `${m}m ${String(s).padStart(2, "0")}s`;
  }
  return `${s}s`;
}
