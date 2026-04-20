# Tasks

> Product direction and ordered slices:
> [docs/product_roadmap.md](docs/product_roadmap.md). UX inspiration
> sources and the borrow-patterns-not-code rule:
> [docs/ux_inspiration.md](docs/ux_inspiration.md).

## Phase 1: Reliable Core

- [x] Create a job model and working-directory convention with `job.json`
- [x] Implement ingest to accept a source recording and persist `original.ext`
- [x] Add metadata extraction via `ffprobe` and persist `metadata.json`
- [x] Add FFmpeg normalization to produce `analysis.mp4`
- [x] Add FFmpeg audio extraction to produce `audio.wav` as 16kHz mono WAV
- [x] Integrate faster-whisper as the default transcription engine
- [ ] Support WhisperX as an optional precision path when word-level timing is needed
- [x] Persist transcript outputs to `transcript.json` and `transcript.srt`
- [x] Implement basic Markdown report generation as `report.md`
- [x] Make every Phase 1 step restartable from existing artifacts
- [x] Add basic job status updates to reflect stage progress and failures
- [x] Validate the Phase 1 flow on a sample recording end to end

## Phase 2: Smart Visuals v1

- [x] Integrate PySceneDetect and write `scenes.json` (opt-in via `recap scenes`)
- [x] Extract one representative frame per scene into `candidate_frames/` (with single-scene fallback when no cuts)
- [x] Add pHash-based duplicate marking (`frame_scores.json`, opt-in via `recap dedupe`)
- [x] Add SSIM checks for borderline duplicate frames (folded into `recap dedupe`; extends `frame_scores.json`)
- [x] Integrate Tesseract OCR for text extraction and novelty scoring (folded into `recap dedupe`; extends `frame_scores.json` with per-frame `ocr_text` and `text_novelty`)

## Phase 3: Semantic Alignment

- [ ] Implement full chapter proposal logic using transcript shifts, pauses, speaker changes, and scene boundaries
  - [x] Pause + speaker-change + scene-boundary fusion shipped (opt-in via `recap chapters`; reads `transcript.json` and, when present, `scenes.json`; writes `chapter_candidates.json` with `source_signal` in {"pauses","pauses+speakers","pauses+scenes","pauses+speakers+scenes"}, emits pre-merge `speaker_change_count` in speaker-aware mode and `scenes_source` plus pre-merge `scene_change_count` in scenes-aware mode). Topic-shift detection, speaker recognition/labeling, and chapter titling remain deferred.
- [x] Persist chapter proposals to `chapter_candidates.json` (pause-only when neither speakers nor a usable `scenes.json` are available; fuses speaker-change boundaries when Deepgram utterances are present and scene-cut boundaries when `scenes.json` is present and not a fallback; topic-shift detection, speaker recognition/labeling, and chapter titling remain deferred)
- [x] Add transcript windowing around frame timestamps using a fuzzy plus or minus 5 to 7 second range (opt-in via `recap window`; writes `frame_windows.json`)
- [x] Integrate OpenCLIP scoring between candidate frames and transcript chunks (opt-in via `recap similarity`)
- [x] Rank frames per chapter using deduplication, OCR novelty, and semantic similarity together (opt-in via `recap rank`; writes `frame_ranks.json`)
- [x] Apply deterministic screenshot keep/reject rules before shortlist finalization (opt-in via `recap shortlist`; writes `frame_shortlist.json`; `selected_frames.json` remains reserved for Phase 4 post-VLM finalists; blur/VLM-dependent visual-quality rules remain deferred).
- [x] Add optional Deepgram cloud transcription engine with diarized utterances (opt-in via `--engine deepgram` on `recap run` and `recap transcribe`; `DEEPGRAM_API_KEY` env required only on recompute; adds `utterances`, `speakers`, `words`, `provider_metadata` as additive optional fields on `transcript.json`; `faster-whisper` remains the default; Groq, WhisperX, pyannote, and speaker recognition/manual labels remain deferred).

## Phase 4: Precision Polish

- [x] Add optional VLM verification for only the top 1 to 3 frames per chapter (opt-in via `recap verify`; reads `frame_shortlist.json` and only verifies frames with `decision in {"hero","supporting"}`; mock + Gemini providers via stdlib only; `recap run` remains Phase-1-only)
- [x] Pass exact transcript context into finalist verification (per-frame `window_text` from `frame_windows.json` and per-chapter `text` from `chapter_candidates.json`, truncated to `WINDOW_CONTEXT_CHARS = 1500` / `CHAPTER_CONTEXT_CHARS = 1500`)
- [x] Support tie-breaking and caption generation during VLM verification (hero promotion of the highest-ranked surviving supporting when the original hero is VLM-rejected, tagged `vlm_tie_broken_by_rank`; captions returned by Gemini are stored on `verification.caption` truncated to `VLM_MAX_CAPTION_CHARS = 240`; mock provider never captions and keeps `caption_mode = "off"`)
- [x] Persist final frame selections to `selected_frames.json`
- [x] Improve Markdown assembly to embed finalized screenshots and captions (opt-in via presence of `selected_frames.json`; `recap assemble` reads `selected_frames.json` and `chapter_candidates.json` and inserts a `## Chapters` section between `## Media` and `## Transcript` with hero/supporting images and VLM-provided captions, atomic write via `report.md.tmp`; absent `selected_frames.json` → report is byte-identical to the Phase-1 basic output; no VLM calls; no chapter titling; no new CLI flag; `recap run` remains Phase-1-only)
- [x] Add optional HTML export to `report.html` (opt-in via `recap export-html --job <path> [--force]`; reads the same artifacts as `recap assemble` and writes a standalone `report.html` with inline CSS; when `selected_frames.json` is present embeds hero/supporting images and captions via relative `candidate_frames/<frame_file>` paths; no new dependencies, no Markdown parsing, no network, no VLM/LLM calls; `recap run` remains Phase-1-only)
- [x] Add optional DOCX export to `report.docx` (opt-in via `recap export-docx --job <path> [--force]`; uses `python-docx>=1.1`; reads the same artifacts as `recap export-html` and embeds hero/supporting screenshots via `Document.add_picture` at a fixed 6.0-inch width; captions rendered as italic runs only when `verification.caption` is a non-empty string; when `selected_frames.json` is absent the document still renders header/media/transcript with no Chapters section; determinism caveat: DOCX package metadata is timestamped, so reruns are not byte-identical; `recap run` remains Phase-1-only; PDF and Notion export remain deferred)

## UI

- [x] Add read-only local dashboard for existing jobs and artifacts (`recap ui --host 127.0.0.1 --port 8765 --jobs-root jobs`; stdlib `http.server.ThreadingHTTPServer` only, no new dependencies; reads `jobs/<id>/job.json` and serves a jobs index, a per-job detail page, and a small whitelist of artifacts including `report.md`/`report.html`/`report.docx` and `candidate_frames/*.{jpg,jpeg,png}`; path-traversal hardened; 127.0.0.1-only by default; no POST routes, no subprocess calls, no stage execution)
- [x] Expand job detail page with Errors surface and Chapters & selected-frames thumbnail summary (read-only)
- [x] Add POST surface to rerun assemble/export-html/export-docx from the dashboard (CSRF token generated at server startup; Host header pinned; 4 KiB body cap; 60 s subprocess timeout; stdout/stderr truncated to 8 KiB UTF-8; per-job threading lock with 2 s acquire timeout returning 429; results cached in-memory and shown at `/job/<id>/run/<stage>/last`; `recap run` and every other stage remain CLI-only)
- [x] Start a new `recap run` from the browser via `/new` + `POST /run` (new `--sources-root` flag on `recap ui`, default `sample_videos`; extension whitelist `.mp4/.mov/.mkv/.webm/.m4v`; synchronous `recap ingest` inside the handler; background daemon thread runs the full `recap run` via `subprocess.Popen` with a 1-hour timeout; global `threading.Semaphore(1)` caps concurrent runs; in-memory result cache keyed `(job_id, "run")` visible at `/job/<id>/run/run/last`; `run` stage is read-only via the last-result route and is NOT in `_RUNNABLE_STAGES`; detail page shows a "Run in progress" banner plus a 10-second meta refresh when any stage is running)
- [x] Let the `/new` form pick a transcription engine (faster-whisper default; deepgram opt-in when `DEEPGRAM_API_KEY` is in the server environment. No key-entry UI; key is read only from the shell that launched `recap ui`; server-side allowlist `{faster-whisper, deepgram}`; 400 with inline error on invalid engine; 400 with inline error on `engine=deepgram` without the env var; `--engine <value>` forwarded into background `recap run`; subprocess inherits the server environment so the key reaches the child without UI involvement)
- [x] Add "Generate rich report" dashboard button that runs the 11-stage chain (scenes→dedupe→window→similarity→chapters→rank→shortlist→verify mock→assemble →export-html→export-docx) in a background thread (mock VLM only; shares the `_run_slot` semaphore with `recap run`; per-job lock ownership is explicitly transferred to the background worker; 1-hour chain budget; captured stdout/stderr truncated to 8 KiB per stage; skip-aware stages short-circuit on reruns; `recap run` composition unchanged)
- [ ] Accept a browser file upload for the source video
- [x] Render a timestamped transcript viewer with optional speaker rows (`GET /job/<id>/transcript`; prefers `utterances[]` with integer or non-empty string speaker ids, renders `Speaker {n}` in a dedicated column; falls back to `segments[]` with no Speaker column; filters rows with empty text; missing or malformed `transcript.json` renders a 200 empty/error state with a single `[recap-ui] transcript skipped: ...` log line; detail page links to the viewer only when `transcript.json` exists; no JavaScript, no video player, no backend changes)
- [x] Inline video player with transcript-row jump links (whitelists `analysis.mp4` + `video/mp4`; adds a Range-aware static handler that streams in 64 KiB chunks, supports `bytes=a-b`, `bytes=a-`, `bytes=-n` single-range forms, returns 416 on unsatisfiable and 200 full body on malformed Range; `/job/<id>/transcript` renders a `<video id="player" controls preload="metadata">` only when `analysis.mp4` exists and rewrites Time cells into `<button class="ts" data-start="{float}">` + a ~10-line inline script that sets `player.currentTime`; no multi-range support, no active-row highlighting, no speaker-isolated tracks; localhost-only)
- [x] Active-row highlighting and auto-scroll as the video plays (inline JS extends the existing transcript-page script; builds an ascending-sorted row index from per-row `data-start` attributes, toggles a `tr.active` class on `timeupdate` / `seeking` / `play`, and calls `scrollIntoView({block:'nearest',behavior:'smooth'})`; `wheel`/`touchmove`/`scroll`/arrow-key listeners set a `lastUserScroll` timestamp and suspend auto-scroll for 3 s so the page doesn't fight the user; active row styled with a soft background + 3 px left accent so the cue isn't color-only; no-video fallback unchanged — no `<tr data-start>`, no buttons, no sync script)
- [x] Speaker-colored transcript rows (pure CSS + server-side classnames; only active when the transcript data source is `utterances[]` with at least one valid speaker id; stable first-seen `speaker-0`..`speaker-7` classes cycle modulo `_SPEAKER_PALETTE_SIZE = 8`; small `<p class="speakers-legend">` above the table lists each distinct speaker with its color swatch; speaker-tint rules placed before `tr.active` so active-row yellow still overrides during playback; segments-only transcripts render unchanged)
- [ ] Speaker-isolated audio / per-speaker navigation
- [ ] Cancel a running job from the browser
- [ ] Persist `/job/<id>/run/<stage>/last` history across server restarts
- [ ] Start or rerun pipeline stages from the UI
- [ ] Delete or archive jobs from the UI
- [ ] Live status updates (SSE / WebSocket / polling)
- [ ] Auth / API key management surface
- [ ] Remote access (non-localhost binding with TLS and auth)

## Modern web app

- [x] Add JSON API scaffold and Vite/React transcript workspace at `/app/job/<id>/transcript` (React 18 + Vite + TypeScript + Vitest; Python serves `web/dist` under `/app/*`; API endpoints cover CSRF, job summary, transcript JSON, and speaker-name overlays; speaker names persist in `speaker_names.json`; `transcript.json` and exporters unchanged; old HTML routes remain live)
- [x] React jobs index page (`/app/`) backed by `/api/jobs` (malformed `job.json` entries skipped server-side; `AppShell` sticky top bar links to legacy dashboard and `/new`; `JobCard` shows status badge + artifact chips + formatted created/updated times + actions; client-side search by filename/job_id and status pill filter; `verify_api.py` extended to 14 checks covering the listing and malformed-entry skip; Vitest specs for `JobCard` and `JobsIndexPage` raise total to 7; HTML jobs index at `/` remains live)
- [x] Polish React UI and transcript interactions (visual-system rewrite in `web/src/index.css` with CSS custom-property tokens, typography scale, elevation, radii, focus ring, and `prefers-reduced-motion` guard; jobs index hero + stats row; `JobCard` status stripe + artifact chips + action hierarchy; sticky left rail in transcript workspace; client-side transcript search with match count + prev/next + highlight rendering + Enter/Shift+Enter cycling + scroll active match into view, backed by `lib/search.ts`; speaker-filter chips on the speaker legend with `aria-pressed` toggling and "Show all" reset; cleaner empty/loading/error states; Vitest suite grows to 22 specs across six files)
- [x] Structured insights + report integration (new `recap insights --job <path> --provider mock|groq` stage writes `insights.json` with overview / quick bullets / per-chapter summaries / action items; mock provider is deterministic and offline, Groq provider uses stdlib HTTP with `GROQ_API_KEY`/`GROQ_MODEL` and fails cleanly on a missing key; `recap assemble`, `recap export-html`, and `recap export-docx` render `## Overview` and enrich chapter headings when `insights.json` is present and stay byte-compatible when it is absent; UI whitelists `insights.json`, API surfaces the `insights_json` artifact flag and URL, React `JobCard` shows an "Insights" chip; `scripts/verify_reports.py` grows to 23 checks (4 new insights cases), `scripts/verify_api.py` grows to 15 checks; `job.STAGES` and `recap run` composition unchanged; no new Python deps; [docs/product_roadmap.md](docs/product_roadmap.md) slice 3)
- [ ] React job detail page and rich-report progress page backed by JSON APIs
- [ ] React new-job page with engine selector and browser upload
- [ ] Exporter integration: assemble / export-html / export-docx read `speaker_names.json`
- [ ] Chapter-title overlays and editable chapter sidebar
- [ ] Selected-speaker playback ranges (play only ranges where a chosen voice speaks)
- [ ] Transcript text editing / correction overlay
- [ ] Playwright browser coverage for the React workspace
- [ ] Linux deployment docs and systemd unit sample

## Reliability

- [x] Mark `recap scenes` as `failed` (not `running`) when Ctrl-C interrupts PySceneDetect/cv2 frame processing; clean up partial `candidate_frames/` for the interrupted attempt; re-raise `KeyboardInterrupt` so the CLI still exits like an interrupted command

## Hardening

- [x] Add local offline golden-path validation script for Markdown/HTML/DOCX report generation (`scripts/verify_reports.py` + committed fixture under `scripts/fixtures/minimal_job/`; runs `recap assemble`, `recap export-html`, `recap export-docx` against both the selected and absent-selected paths plus negative cases for malformed `selected_frames.json`, traversal `frame_file`, and missing candidate images; stdlib + `python-docx` only; no network, no model downloads; ~1 second wall-clock)
- [x] Add local offline UI smoke validation script (`scripts/verify_ui.py`; spawns `recap ui` against a temp copy of `scripts/fixtures/minimal_job`, checks `/`, `/job/<id>/`, whitelisted JSON artifacts, candidate-frame JPEG, unnormalized traversal path via `http.client` for raw-path delivery, and non-whitelisted/unknown routes; then runs `recap assemble`/`export-html`/`export-docx` and re-checks that `report.html`, `report.docx`, and the referenced `candidate_frames/<file>.jpg` all serve correctly; stdlib only; ~0.5 second wall-clock)
- [x] Deduplicate shared selected-frame / report helpers across the three report stages into `recap/stages/report_helpers.py` (no-behavior-change refactor; `recap/stages/assemble.py`, `recap/stages/export_html.py`, and `recap/stages/export_docx.py` now import `format_ts`, `summarize_metadata`, `collapse_whitespace`, `is_int`/`is_number`/`is_safe_frame_file`, `validate_selected_frames`, `validate_chapter_candidates`, `caption_for`, `check_hero_coherence`, and `check_supporting_coherence` from the shared module; error-message prefixes preserved; `scripts/verify_reports.py` + `scripts/verify_ui.py` both green; no-selected Markdown and selected Markdown+HTML outputs are byte-identical pre-refactor vs post-refactor)

## Guardrails

- [ ] Do not add fixed-interval screenshot capture anywhere in the pipeline
- [ ] Do not send full raw videos to a VLM
- [ ] Do not make VLM usage mandatory for successful processing
- [ ] Do not expand Phase 1 beyond the reliable core
