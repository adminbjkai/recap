# Product Requirements Document

Recap's current product target and user-facing goals. For architecture
and invariants, see [ARCHITECTURE.md](ARCHITECTURE.md); for the ordered
list of slices, see [docs/product_roadmap.md](docs/product_roadmap.md);
for long-term pipeline philosophy, see
[MASTER_BRIEF.md](MASTER_BRIEF.md).

## 1. Product goal

Recap is a **local-first, self-hosted video-to-documentation tool**.
A user drops in a screen recording (or records one directly in the
browser) and gets back three things:

1. A **polished transcript workspace** — video + diarized, speaker-
   colored transcript, inline playback sync, transcript search,
   editable speaker names, and a stable URL to share inside a
   trusted network.
2. **Structured insights** — overview, per-chapter summary / bullets /
   action items, and a flat action-items list, derived from the
   transcript and available chapter signals.
3. **Useful exports** — `report.md`, `report.html`, and `report.docx`
   that carry the overview, chapter enrichments, transcript
   segments, and selected hero/supporting screenshots when available.

Recap is aimed at people who already record their screens (engineers,
PMs, educators, researchers, operators) and want to turn those
recordings into real documentation without uploading the raw video to
a third-party SaaS.

## 2. Primary user flows

### 2.1 Start a recap from an existing file

1. Drop a video into `sample_videos/` (or another `--sources-root`).
2. Open `/app/new` in the browser.
3. Pick the file from the **Sources root** tab, optionally switch the
   engine to Deepgram (visible only when `DEEPGRAM_API_KEY` is set),
   click **Start job**.
4. The React page redirects to `/app/job/<id>` where the stage
   timeline updates as the pipeline progresses.
5. When the run finishes, open the transcript workspace at
   `/app/job/<id>/transcript`.

### 2.2 Record in the browser

1. Open `/app/new` → **Record screen** tab.
2. Toggle "Include microphone audio" if desired.
3. Click **Start screen recording**, pick a screen/window/tab in the
   browser's native picker, stop when done.
4. Preview the clip locally. Click **Save to sources** — the clip is
   uploaded to `POST /api/recordings`, stored under `--sources-root`
   with a server-picked name, and auto-selected in the Sources
   picker.
5. Click **Start job** to dispatch the recap. Recording and
   transcription are **separate, explicit** steps — transcription
   never starts automatically on stop.

### 2.3 Work the transcript

1. On `/app/job/<id>/transcript`, scrub the video. The active row
   auto-scrolls into view (with a 3 s "user is scrolling" suspend).
2. Click any `timestamp` button to jump the player.
3. Use the search bar to find a phrase — match highlights, count,
   prev/next cycling, Enter/Shift+Enter to cycle.
4. Click a speaker pill to **hide** that speaker's rows. Click again
   to show. "Show all" resets.
5. Click **Rename** on a speaker pill to set a friendly label. The
   overlay is saved to `speaker_names.json` and re-rendered
   immediately in the workspace.

### 2.4 Enrich the report

1. From the CLI or the legacy dashboard, run `recap insights --job
   <path> --provider mock|groq`. Groq requires `GROQ_API_KEY`.
2. Re-run `recap assemble`, `recap export-html`, `recap export-docx`.
   The exports now include an `## Overview` section, per-chapter
   titles/summaries/bullets, action items, and finalized screenshots
   when `selected_frames.json` exists.

## 3. Product surface

- **CLI** — `python -m recap <stage>` is the canonical interface for
  power users and for scripting. Every opt-in stage is its own verb.
- **Local HTTP server** — `recap ui --host 127.0.0.1 --port 8765
  --jobs-root jobs --sources-root sample_videos` hosts both the
  legacy HTML dashboard and the built React SPA plus the JSON API.
- **React SPA** — primary end-user surface under `/app/`. See the
  Primary user flows above.
- **Legacy HTML routes** — retained as a fallback at `/`, `/new`,
  `/job/<id>/`. Users without JavaScript (or when a React slice is
  down for maintenance) can still start a run, inspect artifacts,
  and read the transcript.

## 4. In scope (current slice set)

- File-per-job workspace under `jobs/<job_id>/`.
- Phase-1 core pipeline (`recap run` = ingest → normalize →
  transcribe → assemble).
- Optional semantic visual stages (`scenes`, `dedupe`, `window`,
  `similarity`, `chapters`, `rank`, `shortlist`, `verify`) as
  CLI-invokable opt-ins.
- Diarized transcription via Deepgram when the user opts in.
- Structured insights via Groq (or `mock` offline) when the user
  opts in.
- Editable speaker names overlaid on top of `transcript.json`.
- Markdown, HTML, and DOCX exports that consume the insights overlay.
- React jobs index, new-job page, job dashboard, and transcript
  workspace.
- Browser screen recording via `getDisplayMedia` + `MediaRecorder`
  with a local upload into the sources root.
- CSRF + Host-pinned JSON API for all state-changing operations.

## 5. Out of scope (for now)

These are deferred by design — not forbidden, just not in the current
slice queue. See [docs/product_roadmap.md](docs/product_roadmap.md)
for the ordered queue and
[DECISIONS.md](DECISIONS.md) for why.

- Postgres / MinIO / message queues / worker pools / Docker compose.
- Authentication, account management, or multi-tenancy. Recap is
  "localhost only" today; remote deployments rely on a reverse proxy
  the operator provides.
- Drag-and-drop or file-picker upload of pre-existing local videos
  (a follow-up to the live recording slice).
- Streaming progress (SSE / WebSocket) during `recap run`.
- Mandatory VLM verification or full-video multimodal processing.
- Fixed-interval screenshot capture.
- A transcript-only pipeline that ignores visual stages, or a
  vision-only pipeline that ignores transcript context.
- Adding a Tailwind/Bootstrap/Tabler/TW Elements/icon-kit runtime
  dependency. Those repos inform visual patterns only.

## 6. Functional requirements

- **Per-job inspectability.** Every stage writes a named artifact via
  `<file>.tmp` → `os.replace`. Readers validate shape before use.
  Malformed overlays degrade gracefully (empty overlay) except where
  the stage must consume the artifact to produce its output (then it
  fails cleanly with `<artifact> malformed: <reason>`).
- **Restartability.** A stage that already produced its artifact on
  disk is a no-op on rerun unless `--force` is passed.
- **Staged cascade.** Expensive analysis runs on the smallest viable
  set — cheap deterministic filters first, semantic alignment on the
  reduced set, optional VLM only on a shortlist.
- **Chaptering by signal fusion.** Chapter boundaries fuse transcript
  pauses with speaker-change boundaries (Deepgram utterances) and
  scene-cut boundaries (usable `scenes.json`). Fixed-interval slicing
  is a rejected anti-pattern.
- **Screenshot policy.** 1 hero per chapter by default, up to 3
  supporting if they add new visual information. Reject on near-
  duplicate, low OCR novelty, weak transcript relevance, or low
  information content.
- **Exports carry everything the pipeline knows.** `report.md` is the
  primary target; `report.html` and `report.docx` mirror its content
  structure. When `insights.json` and `selected_frames.json` exist,
  exports render overview + per-chapter enrichments + hero/supporting
  screenshots + captions (VLM-provided, bounded to 240 chars).
- **Browser recording is local-first.** No third-party upload
  endpoint, no auth, no remote sync. The browser filename is never
  trusted; the server picks the name.
- **Safety for mutating endpoints.** Host pinning, CSRF via
  `X-Recap-Token`, body caps, and a single global `_run_slot`
  semaphore guard every dispatching POST.

## 7. Success criteria

- A recording started from `/app/new` (either an existing file or a
  browser recording) lands on a job dashboard URL within one request.
- The transcript workspace renders speaker-colored rows for Deepgram
  transcripts and plain rows for offline transcripts.
- Rename/hide/search interactions on the workspace complete without
  hitting the backend beyond the overlay POST.
- Exports generated from a job with `insights.json` +
  `selected_frames.json` contain overview, chapters with summaries +
  bullets + action items, and inline screenshots.
- Offline mode (no `DEEPGRAM_API_KEY`, no `GROQ_API_KEY`) produces a
  complete transcript + report using faster-whisper + `mock`
  insights. No cloud provider is required for a useful report.
- Every validator (`scripts/verify_reports.py`, `verify_ui.py`,
  `verify_api.py`) passes twice in a row. Every Vitest spec passes.
  `npm audit --audit-level=moderate` reports 0 vulnerabilities.

## 8. Non-goals (strict)

- **No fixed-interval screenshot capture** anywhere in the pipeline.
- **No whole-video VLM submission.** VLM access is finalists-only,
  capped at 1–3 frames per chapter.
- **No mandatory cloud dependency.** Deepgram and Groq are
  *priority* cloud providers when the user opts in — they are never
  required for Recap to produce a report.
- **No bundled third-party UI kit** (Tailwind, Tabler, Bootstrap, TW
  Elements, icon libraries). References only.
- **No vendored external code.** Product patterns from Cap5,
  CapSoftware/Cap, steipete/summarize are re-implemented; their
  source is not copied.
