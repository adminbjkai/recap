# Recap — Continuation Guide

This file exists so a future session can resume from the current repo
state without re-deriving context. It is not a roadmap. For what the
system does and produces, read `HANDOFF.md`.

## Current state

- Phase 1 of Recap is implemented, audited, hardened, and closed out.
- Inline video playback and transcript-row jump links are implemented
  on `/job/<id>/transcript`. `analysis.mp4` is now on
  `_JOB_ROOT_FILES` and `.mp4` maps to `video/mp4` in
  `_CONTENT_TYPES`. A new `_send_ranged_file` handler helper streams
  the file in 64 KiB chunks and implements single-range HTTP Range
  (`bytes=a-b`, `bytes=a-`, `bytes=-n`); it returns `206` with a
  correct `Content-Range`, `416` with `bytes */<size>` on
  unsatisfiable ranges, and `200` with the full body when the Range
  header is absent, malformed, multi-range, or not `bytes=`.
  `Accept-Ranges: bytes` and `Cache-Control: no-store` are set on
  every video response. Non-video whitelisted artifacts continue
  to use the existing `_send_bytes` full-body path unchanged. The
  transcript page renders a `<video id="player" controls
  preload="metadata" src="/job/<id>/analysis.mp4">` above the table
  only when `analysis.mp4` exists; each Time cell becomes
  `<button type="button" class="ts" data-start="{float}">` wrapped
  around the existing `<code>HH:MM:SS</code>`, and a ~10-line
  inline `<script>` wires button clicks to set
  `player.currentTime` and auto-play if paused. When the MP4 is
  absent the player, buttons, and script are omitted and the table
  renders exactly as before. Only `analysis.mp4` is served as
  video — `original.*` source uploads remain out of scope.
  `scripts/verify_ui.py` grew to 53 checks covering the
  no-player-when-no-video baseline plus seven Range-related cases.
  Non-goals for this slice: multi-range responses, active-row
  highlighting, auto-scroll during playback, speaker-colored rows,
  speaker-isolated audio, transcript editing.
- A read-only browser transcript viewer is implemented at
  `GET /job/<id>/transcript`. It reads `transcript.json` from the
  job directory and prefers the Deepgram-style `utterances[]` data
  source when it contains at least one entry with a valid speaker
  id (integer not `bool`, or non-empty string) and non-empty text;
  otherwise it falls back to `segments[]` without a Speaker column.
  Integer speaker ids render as `Speaker {id}`; string ids render
  escaped; null/missing speakers render as `—`. A metadata line
  above the table surfaces engine, model, language, row count, and
  (utterances only) the distinct-speaker count. Missing
  `transcript.json` → 200 with `No transcript available yet.`;
  malformed JSON or non-dict top level → 200 with an inline error
  banner plus a single `[recap-ui] transcript skipped: <error>` log
  line. All transcript text flows through `html.escape`; a
  dedicated verifier case injects `<script>` into a segment and
  asserts it renders escaped. The detail page appends a
  `View transcript` link only when `transcript.json` is present; the
  raw `/job/<id>/transcript.json` artifact route is unchanged.
  `scripts/verify_ui.py` grew to 45 checks covering the link,
  segments rendering, utterances rendering, HTML escaping, missing
  and malformed states. The viewer is strictly read-only — no
  `<video>` element, no JS, no row-click handlers, no editing,
  no diarization controls. Local WhisperX/pyannote and an inline
  `<video>` player with transcript-row jump links both remain
  deferred.
- Browser-started video processing is implemented. `recap ui` takes
  a new `--sources-root` flag (default `sample_videos`) and serves
  `GET /new` that lists the directory's video files (extension
  whitelist `.mp4 .mov .mkv .webm .m4v`) plus a free-text path
  fallback. `POST /run` validates Host → Content-Length (≤ 4096 B) →
  CSRF → acquires a module-level `threading.Semaphore(1)` so only
  one `recap run` is active across the whole server at a time →
  resolves the source path under the resolved sources root →
  `is_file()` → whitelisted extension → runs `recap ingest`
  synchronously with a 120 s timeout → parses the new job directory
  from `cmd_ingest`'s stdout → spawns a daemon thread that runs
  `recap run` via `subprocess.Popen` with a 1-hour
  `communicate(timeout=3600)` → 303 redirects to `/job/<new_id>/`.
  The background thread truncates stdout/stderr to 8 KiB UTF-8, caches
  the result in `_last_run[(job_id, "run")]`, and releases the slot
  in a `finally`. The last-result page lives at
  `/job/<id>/run/run/last` — `run` is added to a read-only
  `_LAST_RESULT_STAGES` set but NOT to `_RUNNABLE_STAGES`, so there
  is no POST surface for `recap run` beyond `/run`. The detail page
  shows a "Run in progress" banner plus a 10-s meta refresh when
  `status == "running"` or any stage is `running`. The result cache
  is in-memory only; a UI server restart loses it. The on-disk
  `job.json` per-stage state survives. `recap run` composition and
  `job.STAGES` are unchanged; the UI still imports no stage `run()`
  function. `scripts/verify_ui.py` grew to 39 checks covering the
  `/new` form, the `/new` link on the index, every validation
  rejection path before ingest, and a mutate-and-restore test that
  proves the running banner + meta refresh render when any stage
  carries `status == "running"`. Browser file upload, cancel, and
  persistent run history remain deferred.
- The dashboard now has its first write-capable surface:
  `recap ui` renders a three-button Actions block on each job detail
  page that POSTs to `/job/<id>/run/{assemble,export-html,export-docx}`.
  Each accepted POST invokes `python -m recap <stage> --job <job_dir>
  --force` via `subprocess.run`. No other stage is runnable — `recap
  run` and every opt-in pipeline stage remain CLI-only. Safety: Host
  header pinned to the bound `host:port`, `Content-Length` capped at
  4 KiB (returns 411/413 on violation), per-form CSRF token generated
  via `secrets.token_urlsafe(32)` at server startup and validated with
  `secrets.compare_digest` (returns 403 on mismatch), per-job
  `threading.Lock` with a 2 s acquire timeout returning 429 +
  `Retry-After: 2`. Subprocess runs under a 60 s timeout; captured
  stdout/stderr are truncated to 8 KiB UTF-8 with a trailing
  `…truncated (N bytes omitted)` marker and cached in-memory at
  `_last_run[(job_id, stage)]`. On success the handler responds
  `303 See Other` with `Location: /job/<id>/run/<stage>/last`, where
  a dedicated results page renders captured output, exit code, and
  status; `in-progress` status triggers a 5 s meta-refresh. Rejected
  POSTs log only a short reason (`host | content-length-missing |
  body-too-large | body-parse | csrf | lock`) — never the token or
  subprocess output. `scripts/verify_ui.py` grew to 31 checks covering
  the happy path, "no runs yet" empty state, token/host failures,
  oversize body, unknown-stage allowlist, GET-on-POST-route, and raw
  path traversal. `recap run` composition and `job.STAGES` are
  unchanged.
- A read-only local web dashboard is implemented: `recap ui
  --host 127.0.0.1 --port 8765 --jobs-root jobs` starts a stdlib
  `http.server.ThreadingHTTPServer` at `recap/ui.py`. No new
  dependency. Served routes are `GET /` (jobs index), `GET
  /job/<id>/` (detail page with metadata + canonical stage table
  + whitelisted artifacts list), `GET /job/<id>/<filename>` (fixed
  whitelist including `report.md`/`report.html`/`report.docx`,
  `job.json`, `metadata.json`, transcript files, and each of the
  Phase 2/3/4 JSON artifacts), and `GET
  /job/<id>/candidate_frames/<name>` (restricted to `.jpg`/`.jpeg`/
  `.png`). Anything else returns 404. URLs containing any `..`
  segment, targets that resolve outside the jobs root, or
  filenames outside the whitelist all return 404 without leaking
  file bytes. The dashboard is strictly read-only: no POST routes,
  no forms, no subprocess calls, no stage execution, no
  `job.STAGES` mutation. Clicking `report.html` opens the rendered
  report in the same tab and its relative `candidate_frames/<file>`
  references resolve against the same path prefix. `recap run`
  composition is unchanged. Remaining UI items (start/rerun/delete
  jobs, live status updates, auth, remote access) are deferred.
- The fourth Phase 4 slice is implemented: optional DOCX export via
  `recap export-docx --job <path> [--force]` → `report.docx`. Uses
  `python-docx >= 1.1` (newly added to both `requirements.txt` and
  `pyproject.toml`). Reads the same artifacts as `recap export-html`
  and `recap assemble` (`job.json`, `metadata.json`,
  `transcript.json`, and — when present — `selected_frames.json` +
  `chapter_candidates.json`) and writes a standard OOXML document
  with `Heading 1 / 2 / 3` blocks, metadata paragraphs, an optional
  `Chapters` block (only when `selected_frames.json` is present),
  inline images embedded via `Document.add_picture(path,
  width=Inches(6.0))`, italic caption paragraphs only when
  `verification.caption` is a non-empty string after whitespace
  collapse, and a `Transcript` / `Segments` tail with `List Bullet`
  paragraphs. Images on disk are never copied, renamed, or
  re-encoded. Validation mirrors the `recap export-html` contract
  (structural/numeric checks, hero and supporting coherence,
  chapter-index lookup, plain-filename safety check on
  `frame_file`, image existence). Skip contract: `report.docx` is
  written atomically via `report.docx.tmp`; reruns without
  `--force` skip. DOCX output is **not** byte-identical across
  reruns because python-docx writes package-level timestamps into
  `core.xml`; structural parity is what this slice guarantees.
  `recap run` composition is unchanged. `export_docx` is opt-in
  and not part of `job.STAGES`. PDF and Notion export,
  topic-shift chaptering, chapter titling, WhisperX, pyannote,
  Groq, and UI all remain deferred.
- The third Phase 4 slice is implemented: optional HTML export via
  `recap export-html --job <path> [--force]` → `report.html`. It
  reads the same artifacts `recap assemble` reads (`job.json`,
  `metadata.json`, `transcript.json`, and — when present —
  `selected_frames.json` + `chapter_candidates.json`) and emits a
  standalone HTML document via direct string construction with an
  inline `<style>` block, `<!doctype html>`, `<meta charset="utf-8">`,
  and a viewport meta. No Markdown parser is used. No network call
  is made. All content-bearing strings are escaped with stdlib
  `html.escape(..., quote=True)`. When `selected_frames.json` is
  present, an `<h2>Chapters</h2>` section is rendered between Media
  and Transcript with hero/supporting `<img>` tags whose `src`
  values are relative POSIX paths `candidate_frames/<frame_file>`;
  captions render as `<p><em>...</em></p>` only when
  `verification.caption` is a non-empty string. Validation follows
  the same selected-path contract enforced by `recap assemble`
  (type/numeric checks, hero/supporting coherence, chapter index
  lookup, image existence). Skip contract: `report.html` is
  written atomically via `report.html.tmp`; reruns without
  `--force` skip. `recap run` composition is unchanged. No new
  dependencies. The `export_html` stage is opt-in and not part of
  `job.STAGES`. DOCX export (`report.docx`) has since also been
  implemented in a later slice (see the `recap export-docx` entry
  above). PDF and Notion export, topic-shift chaptering, chapter
  titling, WhisperX, pyannote, Groq, speaker recognition /
  manual labels, and UI all remain deferred. `recap run` remains
  Phase-1-only.
- The second Phase 4 slice is implemented: `recap assemble` now
  embeds finalized screenshots and captions into `report.md` when
  `selected_frames.json` is present. A new `## Chapters` section is
  inserted between `## Media` and `## Transcript`, with each chapter
  rendering its selected hero image first, then the selected
  supporting images in `supporting_scene_indices` order, followed by
  the chapter body text from `chapter_candidates.json`. Image paths
  are relative POSIX paths `candidate_frames/<frame_file>`; images
  are never copied or renamed. Captions render in italics directly
  below the image only when `verification.caption` is a non-empty
  string — otherwise no caption and no fallback text. `report.md` is
  written atomically via `report.md.tmp`. When `selected_frames.json`
  is absent, the emitted `report.md` is byte-identical to the
  Phase-1 basic report and `recap run` composition is unchanged
  (ingest → normalize → transcribe → assemble). The existing simple
  skip contract is preserved; after `recap verify`, rerun with
  `recap assemble --force` to refresh the embedded report. Chapter
  titling, DOCX / HTML / Notion / PDF export, UI, and topic-shift
  detection all remain deferred.
- The first Phase 4 slice is implemented: optional VLM verification
  over the pre-VLM shortlist via `recap verify`
  (`frame_shortlist.json` + `chapter_candidates.json` +
  `frame_windows.json` + `candidate_frames/*.jpg` →
  `selected_frames.json`). The default provider is `mock`
  (deterministic, no network); `--provider gemini` opts in to a
  stdlib `urllib.request` POST per kept candidate frame to the
  Gemini `generateContent` endpoint. `recap run` remains
  Phase-1-only — the new stage is only invoked via
  `recap verify --job <path>`. The Gemini path reads
  `GEMINI_API_KEY`, `GEMINI_MODEL`, and `GEMINI_BASE_URL` from the
  environment only when a recompute is required; skip paths do
  NOT need the key. API keys are never written to artifacts,
  logs, docs, or prompts. Hero promotion on VLM-rejected heroes
  (`vlm_tie_broken_by_rank`) and caption capture from Gemini
  responses (truncated to `VLM_MAX_CAPTION_CHARS = 240`) are both
  wired up. Report screenshot embedding, caption rendering into
  `report.md`, and DOCX / HTML / Notion / PDF export remain
  deferred.
- Optional Deepgram cloud transcription engine is wired up via
  `--engine deepgram` on `recap run` and `recap transcribe`.
  `faster-whisper` remains the default for both. The Deepgram path
  adds additive optional fields (`utterances`, `speakers`, `words`,
  `provider_metadata`) to `transcript.json` without changing the
  existing `segments` / `duration` contract that every downstream
  stage reads. No new Python dependency is introduced — stdlib
  `urllib.request` only. Env vars: `DEEPGRAM_API_KEY` (required
  only on recompute; skip path does not require it),
  `DEEPGRAM_MODEL` (optional), `DEEPGRAM_BASE_URL` (optional).
  The target Linux + RTX 3070 Ti local WhisperX/pyannote path is
  still **not** wired up.
- Two Phase 2 opt-in entry points are implemented: Stage 5 candidate
  frame extraction (`recap scenes`) and the combined pHash + SSIM
  duplicate marking with Tesseract OCR novelty scoring
  (`recap dedupe`). Every item in the `TASKS.md` Phase 2 checklist is
  ticked.
- Five Phase 3 slices are implemented: transcript-window alignment
  per candidate frame (`recap window` → `frame_windows.json`, ±6 s
  fixed window around each scene midpoint); OpenCLIP frame/text
  cosine similarity (`recap similarity` →
  `frame_similarities.json`, pinned `ViT-B-32 / openai` on CPU with
  the model's shipped preprocessing); a chaptering slice
  (`recap chapters` → `chapter_candidates.json`) that fuses
  transcript pause gaps (`PAUSE_SECONDS = 2.0`) with speaker-change
  boundaries when the transcript carries Deepgram utterances, and
  with scene-cut boundaries when `scenes.json` is present,
  `fallback != true`, and at least one scene cut maps to a
  transcript segment boundary (falls back to pause-only when
  neither speakers nor scenes are available; emits
  `source_signal ∈ {"pauses","pauses+speakers","pauses+scenes",
  "pauses+speakers+scenes"}`, in speaker-aware mode a pre-merge
  `speaker_change_count`, and in scenes-aware mode top-level
  `scenes_source` plus a pre-merge `scene_change_count`);
  chapters shorter than `MIN_CHAPTER_SECONDS = 30.0` are
  iteratively merged to avoid over-fragmentation, with speaker-only
  or scene-only groups as legitimate merge candidates; per-chapter
  deterministic ranking fusion (`recap rank` →
  `frame_ranks.json`) that scores and ranks candidate frames
  within each chapter using OpenCLIP similarity, OCR text novelty,
  and a duplicate penalty with fixed code-level weights; and a
  deterministic pre-VLM keep/reject shortlist
  (`recap shortlist` → `frame_shortlist.json`) that labels each
  frame with hero / supporting / rejected_duplicate /
  rejected_weak_signal / dropped_over_budget under fixed
  thresholds (`CLIP_KEEP_THRESHOLD = 0.30`,
  `OCR_NOVELTY_THRESHOLD = 0.25`) and a `1 + 2` per-chapter budget
  matched to the Stage 7 "top 1 to 3" VLM input. The chapters
  slice is explicitly **not** full Stage 4 chaptering —
  topic-shift detection, speaker recognition / manual labels, and
  chapter titling remain deferred. The ranking
  slice is marking-only — it does not apply keep/reject thresholds,
  enforce a screenshot budget, write `selected_frames.json`, or
  modify `report.md`. The shortlist slice is marking-only and
  pre-VLM — it does not write `selected_frames.json` (reserved
  for Phase 4 post-VLM finalists), invoke any VLM, generate
  captions, embed screenshots, export documents, add UI, or do
  any speaker diarization / recognition / separation work; blur /
  low-information detection and the VLM-dependent "shows code /
  diagrams / settings / dashboards" keep rule remain deferred.
  The remaining Phase 3 bullet (full-fusion chaptering) and all of
  Phase 4 remain out of scope.
- `recap run` itself remains Phase 1 only.
- No other Phase 3+ scaffolding, stubs, abstractions, or configuration
  exist.
- `HANDOFF.md` is the definitive closeout document. It reflects the code
  on disk today.

## What is implemented

Phase 1:

- Stage 1 — Ingest (`original.<ext>`, `job.json`)
- Stage 2 — Normalize (`metadata.json`, `analysis.mp4`, `audio.wav`)
- Stage 3 — Transcribe (`transcript.json`, `transcript.srt`, faster-whisper
  only, with the narrow function-level swap seam documented in
  `recap/stages/transcribe.py`)
- Stage 8 — Basic Markdown assembly (`report.md`)

Phase 2 (checklist complete):

- Stage 5 — Candidate frame extraction (`scenes.json`,
  `candidate_frames/`, opt-in via `recap scenes --job <path>`, with a
  single-scene full-video fallback when `ContentDetector` finds no cuts)
- pHash + SSIM duplicate marking with Tesseract OCR novelty scoring
  (`frame_scores.json`, opt-in via `recap dedupe --job <path>`;
  compares each frame to its immediate predecessor using Hamming
  distance on ImageHash pHashes, resolves borderline pairs with
  `skimage.metrics.structural_similarity` on grayscale frames, and
  stores per-frame `ocr_text` plus a `difflib`-based `text_novelty`
  score against the predecessor's text; all thresholds and the SSIM
  distance band are fixed code-level constants; OCR does not
  influence `duplicate_of`)

Phase 3 (first five slices):

- Transcript-window alignment (`frame_windows.json`, opt-in via
  `recap window --job <path>`; for each candidate frame, collects the
  transcript segments that overlap a fixed ±`WINDOW_SECONDS = 6.0`
  window around `midpoint_seconds` with strict inequalities, clamps
  the upper bound to `transcript.duration` when present, records the
  overlapping segment ids in transcript order, and stores the
  whitespace-normalized concatenation of their text as `window_text`;
  pure stdlib, no new dependencies).
- OpenCLIP frame/text similarity (`frame_similarities.json`, opt-in
  via `recap similarity --job <path>`; for each candidate frame whose
  `window_text` is non-empty, computes the L2-normalized cosine
  similarity between the OpenCLIP image embedding of the JPEG and the
  OpenCLIP text embedding of `window_text` under `torch.no_grad()` +
  `model.eval()`. `MODEL = "ViT-B-32"`, `PRETRAINED = "openai"`,
  `DEVICE = "cpu"`, and `IMAGE_PREPROCESS = "open_clip.default"` are
  fixed code-level constants; `force_quick_gelu=True` is pinned
  internally to match the OpenAI checkpoint's activation. Adds
  Python-only dependencies `open_clip_torch>=2.24` and `torch>=2.1`;
  first run downloads the OpenCLIP `ViT-B-32` OpenAI weights
  (~350 MB) into the local cache. The stage is marking-only: it does
  not threshold, rank, select, keep, reject, or mutate any frame).
- Chapter proposal with pause + speaker-change + scene-boundary
  fusion (`chapter_candidates.json`, opt-in via
  `recap chapters --job <path>`; reads `transcript.json` and,
  when present, `scenes.json`. A boundary is placed between
  adjacent segments whenever any of the three signals fires on
  that pair: pause (gap `≥ PAUSE_SECONDS = 2.0`), speaker (the
  transcript carries a non-empty `utterances` list with at least
  one non-null `speaker` id — Deepgram output — and the adjacent
  segments' speaker ids differ), or scene (`scenes.json` is
  present, `fallback != true`, and a scene cut with
  `start_seconds > 0` maps to the next segment — the smallest
  transcript segment index `i ≥ 1` whose
  `start >= scene.start_seconds`; multiple scene cuts mapping to
  the same segment id collapse to one boundary and count once).
  The trigger label is built in the fixed order pause, speaker,
  scene, so non-first triggers are drawn from `{"pause",
  "speaker", "scene", "pause+speaker", "pause+scene",
  "speaker+scene", "pause+speaker+scene"}`. Chapters shorter than
  `MIN_CHAPTER_SECONDS = 30.0` are iteratively merged (chapter 1
  into its successor; any other short chapter into its
  predecessor) until every chapter meets the minimum or only one
  chapter remains; speaker-only or scene-only groups are
  legitimate merge candidates. `source_signal` is one of
  `"pauses"`, `"pauses+speakers"`, `"pauses+scenes"`, or
  `"pauses+speakers+scenes"`, driven purely by signal
  availability. In speaker-aware mode the artifact also carries
  a top-level `speaker_change_count` (pre-merge); in scenes-aware
  mode it additionally carries top-level `scenes_source` and a
  pre-merge `scene_change_count` (counts adjacent segment pairs on
  which the scene signal fired, not raw scene rows). The first
  chapter starts at `0.0` with `trigger="start"`. The last
  chapter ends at `transcript.duration` (falling back to the max
  segment end when absent). Missing `scenes.json` is a fallback,
  not an error; `scenes.json` with `fallback == true` likewise
  disables scenes-aware mode. A malformed `scenes.json` exits 2.
  Pure stdlib, no new dependencies. This is explicitly **not**
  full Stage 4 chaptering — topic-shift detection, speaker
  recognition / manual labels, and chapter titling are deferred
  to later slices).
- Per-chapter deterministic ranking fusion
  (`frame_ranks.json`, opt-in via `recap rank --job <path>`;
  reads `scenes.json`, `chapter_candidates.json`,
  `frame_scores.json`, `frame_windows.json`, and
  `frame_similarities.json`. Computes a composite score per frame
  from `clip_similarity` (`W_CLIP = 1.0`), `text_novelty`
  (`W_OCR = 0.5`), and a duplicate penalty (`W_DUP = 0.5`).
  Assigns frames to chapters by `midpoint_seconds` and ranks
  within each chapter by composite score descending. All weights
  are fixed code-level constants. The artifact includes
  `input_fingerprints` (SHA-256 over canonical JSON for each
  input), so drift in any of the five input artifacts triggers a
  recompute. Pure stdlib, no new dependencies. The stage is
  marking-only: it does not apply keep/reject thresholds, enforce
  a screenshot budget, write `selected_frames.json`, or modify
  `report.md`).
- Deterministic pre-VLM keep/reject shortlist
  (`frame_shortlist.json`, opt-in via
  `recap shortlist --job <path>`; reads `frame_ranks.json` only
  and labels every candidate frame with a closed-vocabulary
  `decision` of `hero`, `supporting`, `rejected_duplicate`,
  `rejected_weak_signal`, or `dropped_over_budget` under fixed
  code-level constants `CLIP_KEEP_THRESHOLD = 0.30`,
  `OCR_NOVELTY_THRESHOLD = 0.25`, `HERO_PER_CHAPTER = 1`,
  `SUPPORTING_PER_CHAPTER = 2`, `TOTAL_PER_CHAPTER = 3`, and
  `POLICY_VERSION = "keep_reject_v1"`. The 3-frame budget matches
  Stage 7's "top 1 to 3 candidate frames per chapter" VLM input;
  this is a pre-VLM shortlist, not the final report screenshot
  budget. The artifact includes `input_fingerprints` (SHA-256
  over canonical JSON of `frame_ranks.json`), so drift in any
  upstream artifact propagates through `recap rank` into this
  skip contract. Pure stdlib, no new dependencies. Marking-only
  and pre-VLM: does not write `selected_frames.json` (reserved
  for Phase 4 post-VLM finalists), invoke any VLM, generate
  captions, embed screenshots, export documents, add UI, or do
  any speaker diarization / recognition / separation work. Blur /
  low-information detection and the VLM-dependent "shows code /
  diagrams / settings / dashboards" keep rule remain deferred).

Stage 7 is deliberately absent. Stage 6 is complete for the
Phase 2 checklist (pHash, SSIM, and OCR all shipped) and now also
includes transcript-window alignment plus OpenCLIP similarity as the
first two Phase 3 slices. Stage 4 (chaptering) now fuses pauses
plus speaker-change boundaries on Deepgram transcripts and scene-cut
boundaries when a usable `scenes.json` is present, via
`recap chapters`, falling back to pause-only when neither signal is
available; topic-shift detection, speaker recognition / manual
labels, and chapter titling remain Phase 3 work. Per-chapter ranking
fusion is implemented via `recap rank`. The deterministic pre-VLM
keep/reject shortlist is implemented via `recap shortlist`; blur /
low-information detection and the VLM-dependent visual-quality keep
rules remain deferred.

## Binding sources of truth

In this order, these files govern any future work:

1. `MASTER_BRIEF.md` — product and pipeline source of truth
2. `AGENTS.md` — phase discipline, required artifacts, anti-patterns
3. `ARCHITECTURE.md` — stage layout and artifact contracts
4. `DECISIONS.md` — decisions already locked in
5. `TASKS.md` — per-phase task breakdown
6. `PRD.md` — product requirements
7. `README.md` — install and run instructions
8. `HANDOFF.md` — current implementation closeout

If any future work appears to conflict with `MASTER_BRIEF.md` or
`AGENTS.md`, the brief and agents file win.

## Roles

- **Codex — prompt guider / planning guide.** Used to review the current
  repo state, shape prompts, plan the next move, check scope against the
  binding docs, and guard against overreach. Codex does not execute
  implementation edits.
- **Claude — developer / builder.** Receives a scoped execution prompt
  produced with Codex and performs the implementation work (reads, edits,
  validation runs) inside the repo.

Neither role expands scope unilaterally. Phase boundaries are enforced by
the binding docs, not by either agent.

## Working pattern

1. **Start with Codex.** Re-read the binding docs, inspect the current
   repo state, decide the next scoped chunk, and write the execution
   prompt. Confirm the chunk fits inside the currently approved phase.
2. **Hand the prompt to Claude.** Claude executes that prompt: makes the
   edits, runs the validations the prompt specifies, reports what
   changed.
3. **Return to Codex before the next chunk.** Review what Claude did,
   update any docs if state drifted, and shape the next prompt. Do not
   let Claude chain into the next chunk on its own.

This loop is the only workflow in use. No automation, orchestrator, or
task runner is wired up.

## Phase discipline (the rule)

No session may jump ahead of the approved phase. Today the approved
work is Phase 1 (complete) plus the full Phase 2 checklist (complete)
plus the first five Phase 3 slices (transcript-window alignment via
`recap window`, OpenCLIP frame/text similarity via
`recap similarity`, the pause + speaker-change + scene-boundary
chapter proposal via `recap chapters` — pause-only fallback when
neither speakers nor a usable `scenes.json` are available —
per-chapter ranking fusion via `recap rank`, and the deterministic
pre-VLM keep/reject shortlist via `recap shortlist`), plus the
optional Deepgram transcription engine via `--engine deepgram`,
plus the first Phase 4 slice (optional VLM verification via
`recap verify --job <path> [--provider {mock,gemini}]` →
`selected_frames.json`). Any remaining Phase 3/4 work —
full-fusion chaptering (topic shifts, speaker recognition /
manual labels, chapter titling), blur / low-information
detection, captions rendered into `report.md`, report screenshot
embedding, DOCX/HTML/Notion/PDF export, WhisperX, pyannote, Groq,
UI, queues, workers, plugin systems — stays out until the next
chunk is explicitly approved.

If a proposed change requires scope not documented in `MASTER_BRIEF.md`,
stop and raise it for a product decision instead of inventing scope.

## Resuming safely in a future session

1. Re-read the binding docs listed above, in order. Treat them as
   authoritative.
2. Read `HANDOFF.md` to confirm what is actually on disk.
3. Verify the environment (`python3.12 -m venv .venv`, `pip install -r
   requirements.txt`, `ffmpeg`/`ffprobe` on PATH, `tesseract` on PATH
   when exercising `recap dedupe`; Python 3.14 is not supported).
   `recap similarity` adds no system binaries but requires
   `open_clip_torch` and `torch`, both installed by
   `requirements.txt`; first run downloads the OpenCLIP `ViT-B-32`
   OpenAI weights (~350 MB) into the local cache.
4. Run one sample through the Phase 1 pipeline to confirm the repo is
   still green before planning any change (see the next section).
5. With Codex, decide the next scoped chunk and confirm it fits the
   currently approved phase. Only then hand a prompt to Claude.

## Using `sample_videos/` for local validation

`sample_videos/` contains local recordings used for development and
validation runs. The directory is not read by the pipeline; you pass a
file from it via `--source`. To confirm a clean baseline end-to-end:

```bash
.venv/bin/python -m recap run \
  --source "sample_videos/Cap Upload - 24 February 2026.mp4" \
  --model small
```

A new job directory is created under `jobs/<job_id>/` with the Phase 1
artifacts listed in `HANDOFF.md`. Re-running the same command with
`--job jobs/<job_id>` exercises restartability — completed stages should
short-circuit. To exercise the Phase 2 entry points on the same job,
run `recap scenes --job jobs/<job_id>` followed by
`recap dedupe --job jobs/<job_id>` (the latter requires `tesseract` on
PATH). To exercise the Phase 3 entry points, run
`recap window --job jobs/<job_id>` (pure stdlib), then
`recap similarity --job jobs/<job_id>` (requires `open_clip_torch`
and `torch`; first run downloads the OpenCLIP `ViT-B-32` OpenAI
weights), then `recap chapters --job jobs/<job_id>` (pure stdlib;
reads `transcript.json` only and writes
`chapter_candidates.json`), then `recap rank --job jobs/<job_id>`
(pure stdlib; reads `scenes.json`, `chapter_candidates.json`,
`frame_scores.json`, `frame_windows.json`, and
`frame_similarities.json` and writes `frame_ranks.json`), and
then `recap shortlist --job jobs/<job_id>` (pure stdlib; reads
`frame_ranks.json` only and writes `frame_shortlist.json`).
To exercise the first Phase 4 slice, run
`recap verify --job jobs/<job_id>` (pure stdlib; default
`--provider mock`, no network; reads `frame_shortlist.json`,
`chapter_candidates.json`, `frame_windows.json`, and the JPEGs in
`candidate_frames/` and writes `selected_frames.json`). Pass
`--provider gemini` with `GEMINI_API_KEY` set to opt in to the
Gemini path; the skip path does not require the key.
Re-run each to confirm the skip path, or pass `--force` to
confirm recompute.

## Next-session checklist

- [ ] Re-read `MASTER_BRIEF.md`, `AGENTS.md`, and `HANDOFF.md`.
- [ ] Confirm repo has no uncommitted experimental changes outside the
      Phase 1 surface described in `HANDOFF.md`.
- [ ] Install / refresh the virtualenv and confirm `ffmpeg`/`ffprobe`
      resolve.
- [ ] Run one sample from `sample_videos/` through `recap run` and
      verify the expected artifacts.
- [ ] With Codex, identify whether the next chunk is still inside the
      currently approved phase. If it is Phase 2 or later, stop and get
      explicit approval before proceeding.
- [ ] Hand a single, scoped execution prompt to Claude. Do not chain
      chunks.
- [ ] After execution, return to Codex for review before the next chunk.
