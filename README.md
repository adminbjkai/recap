# Recap

Recap is a local-first, privacy-respecting video-to-documentation tool.
You drop in a screen recording, Recap gives you back a polished
transcript workspace and a report that is actually useful as
documentation — not just a transcript dump.

The system is designed around a staged cascade: cheap deterministic
processing first, semantic alignment on a reduced candidate set, and
optional VLM checks only on the final shortlist of frames. An opt-in
`recap insights` stage generates structured summaries, quick bullets,
action items, and per-chapter titles/summaries that flow into the
Markdown / HTML / DOCX exports.

## Product direction

- **Target product** and ordered slices:
  [docs/product_roadmap.md](docs/product_roadmap.md).
- **UX inspiration sources** (Cap5, CapSoftware/Cap, steipete/summarize)
  and the "borrow patterns, not code" rule:
  [docs/ux_inspiration.md](docs/ux_inspiration.md).

## Pipeline

1. Ingest uploaded or completed recordings and create a per-job workspace.
2. Normalize media with FFmpeg into analysis-ready video and audio artifacts.
3. Transcribe speech with faster-whisper by default, or WhisperX when higher timestamp precision is required.
4. Propose chapters from transcript shifts, pauses, speaker changes, and scene boundaries.
5. Extract one representative frame per detected scene.
6. Deduplicate and score frames with pHash, SSIM, OCR novelty, and OpenCLIP transcript alignment.
7. Optionally verify the top 1 to 3 frames per chapter with a VLM.
8. Assemble Markdown-first output and compile to other formats if needed.

## Stack

- Capture and ingestion: OBS Studio, Screenpipe, or Cap
- Media processing: FFmpeg
- Transcription: faster-whisper, WhisperX
- Scene detection: PySceneDetect
- Deduplication: ImageHash, scikit-image
- OCR: Tesseract
- Semantic alignment: OpenCLIP
- Optional VLM verification: Qwen2.5-VL or Gemini 1.5 Flash
- Document assembly: Markdown, Pandoc, python-docx

## Outputs

Each job should produce inspectable intermediate artifacts, including:

- `metadata.json`
- `job.json`
- `analysis.mp4`
- `audio.wav`
- `transcript.json` and `transcript.srt`
- `chapter_candidates.json`
- `scenes.json`
- `candidate_frames/`
- `frame_scores.json`
- `frame_windows.json`
- `frame_similarities.json`
- `frame_ranks.json`
- `frame_shortlist.json`
- `selected_frames.json` (opt-in; produced by `recap verify`)
- `insights.json` (opt-in; produced by `recap insights`)
- `report.md`

Optional downstream outputs include `report.docx` and `report.html`.

## Phase 1

Phase 1 delivers the reliable core:

- ingest
- FFmpeg normalization
- transcription
- basic Markdown text output

## Phase 3 (in progress)

Phase 3 adds semantic alignment on top of Phase 2. Five slices are
implemented:

- Transcript-window alignment — for each candidate frame, the
  transcript segments that overlap a fixed ±6 second window around the
  scene's `midpoint_seconds` are collected and their text is
  concatenated. Results are written to `frame_windows.json`. Run via
  `recap window --job <path>` after `recap scenes`.
- OpenCLIP frame/text similarity — for each candidate frame whose
  `window_text` is non-empty, computes the cosine similarity between
  the OpenCLIP image embedding of the JPEG and the OpenCLIP text
  embedding of the window text. The model (`ViT-B-32` / `openai`),
  device (`cpu`), and shipped image preprocessing are fixed code-level
  constants. Results are written to `frame_similarities.json`. Run via
  `recap similarity --job <path>` after `recap window`. First run
  downloads the OpenCLIP `ViT-B-32` OpenAI weights (~350 MB) into the
  local cache; subsequent runs are offline. `recap run` does not
  invoke this stage.
- Chapter proposal — reads `transcript.json` and (when present)
  `scenes.json` and writes `chapter_candidates.json`. A boundary is
  placed between adjacent transcript segments whenever any of the
  three fusion signals fires on that pair: pause (the gap between
  segments is at least `PAUSE_SECONDS = 2.0`), speaker (the
  transcript carries a non-empty `utterances` list with at least one
  non-null `speaker` id (Deepgram path) and the adjacent segments'
  speaker ids differ), or scene (`scenes.json` is present,
  `fallback != true`, and a scene cut with `start_seconds > 0` maps
  to the next segment — the smallest segment index `i ≥ 1` whose
  `start >= scene.start_seconds`). Any single signal is enough; the
  trigger label is built in the fixed order pause, speaker, scene, so
  the non-first vocabulary is `{"pause", "speaker", "scene",
  "pause+speaker", "pause+scene", "speaker+scene",
  "pause+speaker+scene"}`. Chapters shorter than
  `MIN_CHAPTER_SECONDS = 30.0` are iteratively merged to avoid
  over-fragmentation — the merge is content-agnostic, and
  speaker-only or scene-only groups are legitimate merge candidates.
  The first chapter is always `trigger="start"`. `source_signal` is
  one of `"pauses"`, `"pauses+speakers"`, `"pauses+scenes"`, or
  `"pauses+speakers+scenes"` and is driven only by which signals are
  available (utterances and/or a non-fallback `scenes.json` with at
  least one scene cut that maps to a segment boundary). Top-level
  `speaker_change_count` appears only in speaker-aware mode and
  counts pre-merge speaker-change boundaries. Top-level
  `scenes_source` and `scene_change_count` appear only in
  scenes-aware mode; the count is pre-merge and counts adjacent
  segment pairs on which the scene signal fired (multiple scene cuts
  mapping to the same segment id count once). Missing `scenes.json`
  is a fallback, not an error; `scenes.json` with `fallback == true`
  likewise disables scenes-aware mode. A malformed `scenes.json`
  exits 2. All thresholds and source-signal tokens are fixed at the
  code level. Topic-shift detection, speaker recognition / manual
  labels, and LLM chapter titling remain deferred. Pure stdlib, no
  new dependencies. Run via `recap chapters --job <path>` after
  `recap transcribe` (and, when scene-boundary fusion is desired,
  after `recap scenes`). `recap run` does not invoke this stage.
- Per-chapter ranking fusion — for each candidate frame, computes a
  composite score from OpenCLIP similarity (`W_CLIP = 1.0`), OCR text
  novelty (`W_OCR = 0.5`), and a duplicate penalty (`W_DUP = 0.5`
  subtracted when `duplicate_of` is not null). Frames are assigned to
  chapters by `midpoint_seconds` and ranked within each chapter by
  composite score descending. Results are written to
  `frame_ranks.json`. This is marking-only: it does not apply
  keep/reject thresholds, enforce a screenshot budget, write
  `selected_frames.json`, or modify `report.md`. All weights are fixed
  code-level constants. Pure stdlib, no new dependencies. Run via
  `recap rank --job <path>` after `recap chapters`. `recap run` does
  not invoke this stage.
- Deterministic pre-VLM keep/reject shortlist — reads
  `frame_ranks.json` and writes `frame_shortlist.json`. Rejects
  frames already marked as `duplicate_of` and frames that miss both
  a CLIP similarity floor (`0.30`) and an OCR novelty floor (`0.25`);
  within each chapter the remaining frames are labeled hero (1) plus
  up to two supporting, with the rest marked
  `dropped_over_budget`. All thresholds, the 1+2 budget, and
  `POLICY_VERSION = "keep_reject_v1"` are fixed code-level
  constants. This is marking-only and pre-VLM: it does not write
  `selected_frames.json` (reserved for Phase 4 post-VLM finalists),
  invoke any VLM, generate captions, embed screenshots, export
  documents, add UI, or do any speaker work. Blur / low-information
  detection and VLM-dependent "shows code / diagrams / settings /
  dashboards" judgments are deferred. Pure stdlib, no new
  dependencies. Run via `recap shortlist --job <path>` after
  `recap rank`. `recap run` does not invoke this stage.

## Phase 4 (first slice)

- Optional VLM verification on the shortlist — reads
  `frame_shortlist.json`, `chapter_candidates.json`, and
  `frame_windows.json`, loads each kept candidate's JPEG from
  `candidate_frames/`, and writes `selected_frames.json`. Two
  providers are implemented as siblings with a single `if/elif`
  dispatch (no registry, no ABC, no plugin framework):
    - **`mock`** (default) — fully deterministic, no network. Sets
      `relevance = "relevant"` when the frame's composite score is
      at least `0.30`, else `"uncertain"`; `confidence` equals the
      clamped composite score; `caption` is always `null`. Used for
      CI-friendly validation and for Phase-1 users who do not want
      to enable a cloud call.
    - **`gemini`** — opt-in via `--provider gemini`. One stdlib
      `urllib.request` POST per kept candidate to
      `{base_url}/v1beta/models/{model}:generateContent?key=<key>`
      with inline `image/jpeg` data. The model is required to
      return a single strict JSON object shaped
      `{"relevance","confidence","caption"}`; out-of-vocabulary
      `relevance`, non-numeric `confidence`, or non-string
      `caption` exit 2 with a one-line `error: ...`. The request
      model, base URL, provider/policy versions, context truncation
      limits, and caption cap are fixed code-level constants
      (`GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"`,
      `VLM_PROVIDER_VERSION = "vlm_v1"`,
      `VLM_POLICY_VERSION = "vlm_select_v1"`,
      `VLM_CONFIDENCE_KEEP_THRESHOLD = 0.50`,
      `CHAPTER_CONTEXT_CHARS = WINDOW_CONTEXT_CHARS = 1500`,
      `VLM_MAX_CAPTION_CHARS = 240`). Environment overrides:
      `GEMINI_API_KEY` (required only on recompute; skip path does
      not need the key), `GEMINI_MODEL`, `GEMINI_BASE_URL`. Keys
      are never persisted to artifacts, logs, or prompts.

  Decision policy (closed vocabulary):
  `vlm_rejected` when the VLM labels the candidate
  `not_relevant` or `uncertain` with confidence below
  `VLM_CONFIDENCE_KEEP_THRESHOLD`; otherwise the candidate is
  kept at its shortlist rung (`selected_hero` or
  `selected_supporting`). If the original hero is rejected,
  the highest-ranked surviving supporting is promoted to
  `selected_hero` and tagged with `vlm_tie_broken_by_rank`.

  Skip contract: the stored `selected_frames.json` is reused when
  its `provider`, `model`, `provider_version`, `policy_version`,
  `caption_mode`, `context`, and `input_fingerprints` (SHA-256 over
  canonical JSON of `frame_shortlist.json`,
  `chapter_candidates.json`, and `frame_windows.json`) all match
  the current run. Any drift in any of the three input artifacts
  — including context-only drift in chapter text or window text
  — triggers a recompute. `recap verify --force` removes
  `selected_frames.json` before recomputing; atomic writes via a
  `.json.tmp` sibling ensure no partial artifact is left on
  failure.

  This slice does **not** modify `report.md`, embed screenshots,
  export documents, add UI, or add any non-stdlib dependency.
  Report screenshot embedding and caption rendering, DOCX / HTML
  / Notion / PDF export, topic-shift chapter detection, chapter
  titling, WhisperX, Groq, and pyannote remain deferred. Run via
  `recap verify --job <path>` after `recap shortlist`.
  `recap run` does not invoke this stage.

## Phase 2 (checklist complete)

Phase 2 adds smart visuals on top of Phase 1. The implemented slices
are:

- Stage 5 — PySceneDetect scene boundaries (`scenes.json`) and one
  representative frame per scene into `candidate_frames/`. If the
  detector finds no cuts, a single full-video fallback scene is written
  so there is always one candidate frame.
- pHash + SSIM duplicate marking with Tesseract OCR novelty — for each
  candidate frame, compute a perceptual hash with ImageHash and compare
  against the immediate predecessor's hash. Frames at or below a fixed
  Hamming-distance threshold are marked as duplicates of their
  predecessor. For adjacent pairs that fall in a borderline
  pHash-distance band, SSIM is computed on the grayscale frames and a
  pair is promoted to a duplicate when SSIM is at or above a fixed
  threshold. Every frame is also passed through Tesseract OCR; the
  whitespace-normalized text is stored per frame and a `text_novelty`
  score (1 minus a `difflib` similarity ratio against the predecessor's
  text) is recorded as an additional signal. OCR does not influence
  `duplicate_of`. Results are written to `frame_scores.json`.

Both slices are opt-in: `recap run` continues to execute the Phase 1
stages only. Run `recap scenes --job <path>` after `recap run` (or after
`recap normalize`) to produce the Stage 5 artifacts, then
`recap dedupe --job <path>` to produce `frame_scores.json`. All
checklist items in `TASKS.md` Phase 2 are now implemented; remaining
target-architecture work (transcript-window alignment, OpenCLIP
similarity, chaptering, VLM verification, export formats) belongs to
Phase 3 and Phase 4.

## Running Phase 1 locally

Requirements:

- Python 3.10, 3.11, 3.12, or 3.13
- `ffmpeg` and `ffprobe` on PATH
- `tesseract` on PATH (only required for `recap dedupe`)
- Internet access on first run (downloads a faster-whisper model)

> **Python version note.** `faster-whisper` depends on `ctranslate2`, which as of
> this writing does not ship prebuilt wheels for Python 3.14. On 3.14 the
> install will try to build `ctranslate2` from source and typically fails.
> Use Python 3.12 (recommended) or 3.13. Install `ffmpeg` with
> `brew install ffmpeg` on macOS or `apt-get install ffmpeg` on Debian/Ubuntu.

Install dependencies into a virtualenv:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run the full Phase 1 pipeline on a recording:

```bash
.venv/bin/python -m recap run --source path/to/recording.mp4 --model small
```

A new job directory is created under `jobs/<job_id>/` containing:

- `original.<ext>` — the source file
- `metadata.json` — `ffprobe` output
- `analysis.mp4` — H.264/AAC normalized video
- `audio.wav` — 16 kHz mono PCM
- `transcript.json`, `transcript.srt` — faster-whisper output
- `report.md` — basic Markdown report
- `job.json` — job identity and per-stage status

Per-stage commands (useful for re-running a single stage, or resuming):

```bash
.venv/bin/python -m recap ingest     --source recording.mp4
.venv/bin/python -m recap normalize  --job jobs/<job_id>
.venv/bin/python -m recap transcribe --job jobs/<job_id> --model small
.venv/bin/python -m recap scenes     --job jobs/<job_id>
.venv/bin/python -m recap dedupe     --job jobs/<job_id>
.venv/bin/python -m recap window     --job jobs/<job_id>
.venv/bin/python -m recap similarity --job jobs/<job_id>
.venv/bin/python -m recap chapters   --job jobs/<job_id>
.venv/bin/python -m recap rank       --job jobs/<job_id>
.venv/bin/python -m recap shortlist  --job jobs/<job_id>
.venv/bin/python -m recap verify     --job jobs/<job_id> [--provider {mock,gemini}]
.venv/bin/python -m recap assemble   --job jobs/<job_id>
.venv/bin/python -m recap export-html --job jobs/<job_id>
.venv/bin/python -m recap export-docx --job jobs/<job_id>
.venv/bin/python -m recap status     --job jobs/<job_id>
```

`recap scenes` is the Stage 5 (Phase 2) entry point and is not invoked
by `recap run`. It writes `scenes.json` and `candidate_frames/`. If
the command is interrupted with `Ctrl-C` during PySceneDetect's frame
loop, the stage records `stages.scenes.status = "failed"` with a
`KeyboardInterrupt` error, removes any partial `candidate_frames/`
from that attempt, and re-raises the interrupt so the shell exits as
usual. Re-run `recap scenes --job <path>` to retry; with `--force` it
also removes any previous `scenes.json` before starting.
`recap dedupe` is the pHash + SSIM duplicate-marking and Tesseract OCR
novelty-scoring slice and is also not invoked by `recap run`; it reads
`scenes.json` plus the JPEGs in `candidate_frames/` and writes
`frame_scores.json`. It requires the system `tesseract` binary
(`brew install tesseract` on macOS, `apt-get install tesseract-ocr` on
Debian/Ubuntu). `recap window` is the first Phase 3 slice and is also
not invoked by `recap run`; it reads `transcript.json` and
`scenes.json` and writes `frame_windows.json`, a per-candidate-frame
transcript window (±6 seconds around each scene midpoint) with the list
of overlapping transcript segment ids and their concatenated text. It
does not require any new system binaries or ML dependencies.
`recap similarity` is the second Phase 3 slice and is also not invoked
by `recap run`; it reads `scenes.json`, `frame_windows.json`, and the
JPEGs in `candidate_frames/` and writes `frame_similarities.json` with
per-frame OpenCLIP image/text cosine similarity (`clip_similarity` is
`null` for frames whose `window_text` is empty). It requires the
Python packages `open_clip_torch` and `torch`; first run downloads the
OpenCLIP `ViT-B-32` OpenAI weights (~350 MB) into the local cache and
subsequent runs are offline. No new system binaries are required.
`recap chapters` is the chaptering slice and is also not invoked by
`recap run`; it reads `transcript.json` and (when present)
`scenes.json` and writes `chapter_candidates.json` with one entry
per chapter (`index`, `start_seconds`, `end_seconds`,
`first_segment_id`, `last_segment_id`, `segment_ids`, `text`,
`trigger`) and a top-level `source_signal` ∈ {`"pauses"`,
`"pauses+speakers"`, `"pauses+scenes"`,
`"pauses+speakers+scenes"`}. On faster-whisper transcripts without a
usable `scenes.json` the slice is pause-only and the output is
byte-identical to the pre-scene-fusion version of the stage; on
Deepgram transcripts it additionally fuses speaker-change boundaries
and emits a top-level `speaker_change_count`; when a non-fallback
`scenes.json` with at least one scene cut mapping to a segment
boundary is present it additionally fuses scene-cut boundaries and
emits top-level `scenes_source` and `scene_change_count` (pre-merge).
Missing `scenes.json` is a fallback, not an error;
`scenes.json` with `fallback == true` likewise disables scenes-aware
mode. It does not consult embeddings, topic shifts, speaker
recognition, or LLM chapter titling. It is pure stdlib and requires
no new dependencies or system binaries.
`recap rank` is the per-chapter ranking fusion slice and is also not
invoked by `recap run`; it reads `scenes.json`,
`chapter_candidates.json`, `frame_scores.json`, `frame_windows.json`,
and `frame_similarities.json` and writes `frame_ranks.json` with
per-chapter ranked candidate frames. Each frame's composite score is
computed from OpenCLIP similarity, OCR text novelty, and a duplicate
penalty — all with fixed code-level weights. The artifact includes
`input_fingerprints` (SHA-256 over canonical JSON for each input),
so drift in any of the five input artifacts triggers a recompute
even if the drift does not change ranking results. It does not apply
keep/reject thresholds, enforce a screenshot budget, write
`selected_frames.json`, or modify `report.md`. It is pure stdlib and
requires no new dependencies or system binaries.
`recap shortlist` is the deterministic pre-VLM keep/reject slice
and is also not invoked by `recap run`; it reads `frame_ranks.json`
only and writes `frame_shortlist.json`. Within each chapter, frames
marked `duplicate_of` and frames whose CLIP similarity and OCR
novelty both fall below the code-level thresholds are rejected; the
remaining frames in rank order become a hero (1) plus up to two
supporting, with any extras marked `dropped_over_budget`. The
artifact includes `input_fingerprints` (SHA-256 over canonical JSON
of `frame_ranks.json`), so drift in any of the underlying inputs
propagates through `recap rank` into this skip contract. It is
explicitly pre-VLM: it does not write `selected_frames.json`
(that filename is produced by `recap verify`), invoke any VLM,
generate captions, embed screenshots in `report.md`, export DOCX /
HTML / Notion / PDF, add UI, or do any speaker diarization /
recognition / separation work. Blur / low-information detection and
VLM-dependent "shows code / diagrams / settings / dashboards"
judgments are deferred. It is pure stdlib and requires no new
dependencies or system binaries.
`recap verify` is the first Phase 4 slice and is also not invoked
by `recap run`; it reads `frame_shortlist.json`,
`chapter_candidates.json`, `frame_windows.json`, and the JPEGs in
`candidate_frames/` and writes `selected_frames.json`. The default
provider is `mock` (fully deterministic, no network); pass
`--provider gemini` to send each kept shortlist frame plus its
chapter text and per-frame transcript window to a Gemini
`generateContent` endpoint. `GEMINI_API_KEY` is required only on
recompute; a skip path that already matches the requested provider
and model does not require the key. `GEMINI_MODEL` and
`GEMINI_BASE_URL` optionally override the pinned
`gemini-2.5-flash` and `https://generativelanguage.googleapis.com`
defaults. The artifact records the provider, model, provider /
policy versions, context truncation limits, and a SHA-256
fingerprint of each of the three JSON inputs; drift in any one of
them — including context-only drift in chapter text or window
text — triggers a recompute. API keys are never written to
artifacts, logs, docs, or prompts. It is explicitly a verification
slice: it does not modify `report.md`, embed screenshots, export
documents, add UI, or add any non-stdlib dependency.

Stages skip work when their artifacts already exist. Pass `--force` to
recompute a stage.

### Report screenshot embedding

`recap assemble` is Phase-1-only in `recap run`: it writes a basic
`report.md` from `job.json`, `metadata.json`, and `transcript.json`,
with media and timestamped transcript segments. When `selected_frames.json`
is present on disk (produced by `recap verify`), the same stage
additionally reads `chapter_candidates.json` and inserts a `## Chapters`
section between `## Media` and `## Transcript`. Each chapter renders the
selected hero image first, then the selected supporting images in
`supporting_scene_indices` order, followed by the chapter body text from
`chapter_candidates.json`. Image paths are relative POSIX paths of the
form `candidate_frames/<frame_file>`; images are not copied, renamed, or
rewritten. When a frame's `verification.caption` is a non-empty string
(today, only produced by the Gemini VLM path), the caption is rendered
in italics directly below that image; otherwise no caption is rendered
(no fallback text). No chapter titles are generated (titling remains
deferred), and no VLM is ever invoked during assembly.

When `selected_frames.json` is absent, `report.md` is byte-identical to
the Phase-1 basic report. `recap run` continues to compose only
ingest → normalize → transcribe → assemble, so a fresh run on a new
recording still produces the basic report shape.

Assembly uses the existing simple skip contract: if `report.md` already
exists and `--force` is not passed, the stage is skipped. After running
`recap verify` to produce or refresh `selected_frames.json`, run
`recap assemble --force` to regenerate `report.md` with the embedded
screenshots and captions. `report.md` is written atomically via a
`report.md.tmp` sibling; on failure, the temp file is removed and any
existing `report.md` is left unchanged.

Validation errors during the embedded path exit `2` with a one-line
`error: ...`: malformed `selected_frames.json`, missing or malformed
`chapter_candidates.json`, a referenced candidate image missing from
`candidate_frames/`, or a `supporting_scene_indices` reference that does
not resolve to a `selected_supporting` frame.

Optional HTML and DOCX export are implemented as opt-in slices
(`recap export-html` and `recap export-docx`, documented below);
PDF and Notion export remain deferred.

### HTML export

`recap export-html --job <path> [--force]` is an opt-in Phase 4 slice
that writes `report.html` alongside `report.md`. It is not invoked by
`recap run`. It reads the same artifacts as `recap assemble`
(`job.json`, `metadata.json`, `transcript.json`, and — when present —
`selected_frames.json` plus `chapter_candidates.json`) and writes a
standalone HTML document with an inline `<style>` block, `<!doctype
html>`, `<meta charset="utf-8">`, and a viewport meta tag. No external
CSS or JavaScript is referenced; no network access is performed. All
content-bearing strings are escaped via stdlib `html.escape` so raw
transcript or caption content cannot inject markup.

When `selected_frames.json` is present, an `<h2>Chapters</h2>` section
is rendered between Media and Transcript with one `<section>` per
chapter: the selected hero image first (when present), then selected
supporting images in `supporting_scene_indices` order, with captions
rendered as `<p><em>...</em></p>` only when `verification.caption` is a
non-empty string. Image `src` values are relative POSIX paths exactly
`candidate_frames/<frame_file>`; no image is copied, renamed, or
base64-inlined. Chapter body text from `chapter_candidates.json` is
rendered as a single escaped `<p>` after the images, or omitted when
empty. When `selected_frames.json` is absent, no Chapters section is
rendered.

Skip behavior mirrors `recap assemble`: if `report.html` already
exists and `--force` is not passed, the stage is skipped. Writes are
atomic via `report.html.tmp`; on failure the temp file is removed and
any existing `report.html` is left unchanged.

Validation errors exit 2 with a one-line `error: ...` and match the
selected-path contract enforced by `recap assemble`: malformed
`selected_frames.json`, missing or malformed `chapter_candidates.json`,
a referenced candidate image missing from `candidate_frames/`, or a
`supporting_scene_indices` entry that does not resolve to a
`selected_supporting` frame in that chapter.

This slice introduces no new Python or system dependency. Notion and
PDF exports remain deferred.

### DOCX export

`recap export-docx --job <path> [--force]` is an opt-in Phase 4 slice
that writes `report.docx` alongside `report.md` and `report.html`. It
is not invoked by `recap run`. It reads the same artifacts the HTML
and Markdown reports read (`job.json`, `metadata.json`,
`transcript.json`, and — when present — `selected_frames.json` plus
`chapter_candidates.json`) and emits a standard OOXML `.docx` document
built with `python-docx` (>= 1.1). No Pandoc, no LibreOffice, no PDF
path. No network access.

Document structure mirrors the Markdown and HTML reports: an
`Heading 1` title, metadata paragraphs (Job ID, Source file, Created),
an `Heading 2: Media` block, an optional `Heading 2: Chapters` block
(only when `selected_frames.json` is present) with one `Heading 3` per
chapter embedding the selected hero image first and then the selected
supporting images in `supporting_scene_indices` order, each followed
by an italic caption paragraph when `verification.caption` is a
non-empty string and by the chapter body text from
`chapter_candidates.json`. Images are embedded into the DOCX package
via `Document.add_picture(path, width=Inches(6.0))`; no image file is
copied, renamed, re-encoded, or mutated on disk. The final section is
`Heading 2: Transcript` with engine / language / segment count
paragraphs and a `Heading 3: Segments` list of bullet paragraphs.

Skip behavior mirrors the other exports: if `report.docx` exists and
`--force` is not passed, the stage is skipped. Writes are atomic via
a `report.docx.tmp` sibling replaced on success; on failure the temp
file is removed and any existing `report.docx` is left unchanged.

Validation follows the same selected-path contract as
`recap export-html`: malformed `selected_frames.json`, missing or
malformed `chapter_candidates.json`, a chapter index absent from
`chapter_candidates.json`, a referenced candidate image missing from
`candidate_frames/`, or a `frame_file` that is not a plain filename
(no path separators, no traversal) each exit `2` with a one-line
`error: ...` and leave any existing `report.docx` unchanged.

Unlike the Markdown/HTML reports, DOCX output is **not** byte-identical
across reruns because python-docx writes package-level timestamps into
`core.xml`. Structural parity is what this slice guarantees. PDF and
Notion exports remain deferred.

### Local dashboard

`recap ui --host 127.0.0.1 --port 8765 --jobs-root jobs` starts a
local web dashboard for existing jobs. It is not invoked by
`recap run`. Defaults are `127.0.0.1:8765` with the repo-relative
`jobs/` directory as the jobs root.

```bash
.venv/bin/python -m recap ui
# then open http://127.0.0.1:8765/ in a browser
```

The dashboard:

- scans direct subdirectories of `--jobs-root` that contain a readable
  `job.json` and lists them sorted by `created_at` descending, with
  indicators for which of `report.md` / `report.html` / `report.docx`
  exist and a one-click link to `report.html` when present;
- renders a per-job detail page at `/job/<job_id>/` with the job's
  metadata, a stage status table (canonical order: ingest, normalize,
  transcribe, assemble, scenes, dedupe, window, similarity, chapters,
  rank, shortlist, verify, export_html, export_docx; unknown stages
  appended alphabetically), and a list of every whitelisted artifact
  present on disk;
- serves each whitelisted artifact from
  `/job/<job_id>/<filename>`, so clicking `report.html` opens the
  rendered HTML report in the same tab and its relative
  `candidate_frames/<file>` image references resolve correctly against
  the same path prefix.

The legacy dashboard now includes several guarded POST surfaces:
browser-started `recap run`, exporter reruns, the rich-report chain,
and API-backed speaker-name overlays. They are all Host-pinned,
CSRF-protected, body-size capped, and serialized with the existing
per-job locks / global run semaphore where appropriate. The server
binds to `127.0.0.1` by default. Only a fixed whitelist of filenames
under `jobs/<id>/` is served (reports, job/metadata/transcript JSONs,
`speaker_names.json`, and JPEG/PNG images under `candidate_frames/`),
and any URL containing a `..` segment or resolving outside
`jobs/<id>/` returns 404.

### Modern web app

The React/Vite surface lives beside the legacy dashboard. Current
routes:

```text
/app/                            (jobs index)
/app/new                         (start a new job)
/app/job/<job_id>                (job dashboard)
/app/job/<job_id>/transcript     (transcript workspace)
```

Both pages are wrapped in a polished `AppShell` with a sticky top bar
that links to the legacy HTML dashboard and to `/app/new`. The visual system
(see `web/src/index.css`) uses a small set of CSS custom properties
for colors, typography, radii, elevation, and focus states, plus
`prefers-reduced-motion` safeguards — no Tailwind and no component
library.

The jobs index calls `GET /api/jobs`. The hero surfaces totals broken
down by status (total / completed / running / failed / pending) and
one-line summary. Each `JobCard` shows a top status stripe, a status
badge, artifact chips with ready/missing state, created and updated
timestamps, and action buttons: a primary "Open transcript workspace"
route plus optional links to the legacy detail page and HTML report.
A search input filters by filename or job id, and a status pill row
filters by completed / running / failed / pending. Loading, error,
and empty states all render as full hero cards, and "No matches" adds
a one-click reset. Malformed `job.json` entries are skipped
server-side so the frontend never has to guard each card.

The transcript workspace is a modern video + transcript surface:
native video playback in a sticky left rail, active-row video sync,
speaker-colored rows, a speaker legend whose pills double as
show/hide filter chips (with a "Show all" reset when any are hidden),
a transcript search bar with match count + prev/next cycling +
highlight rendering (`Enter` / `Shift+Enter` also cycles), and inline
speaker-name renaming. The rename feature writes a small per-job
`speaker_names.json` overlay:

```json
{
  "version": 1,
  "updated_at": "2026-04-20T12:34:56Z",
  "speakers": {
    "0": "Host",
    "1": "Guest"
  }
}
```

The overlay never mutates `transcript.json`. The React page and API use
the custom labels immediately, while Markdown/HTML/DOCX exporters still
render `Speaker N` until the separate exporter-integration slice lands.

Development workflow:

```bash
# terminal 1
.venv/bin/python -m recap ui --jobs-root jobs --sources-root sample_videos

# terminal 2
cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5173/app/job/<job_id>/transcript`. Vite proxies
`/api/*` and `/job/*` to the Python server on `127.0.0.1:8765`.

Production/local-hosted workflow:

```bash
cd web
npm install
npm run build
cd ..
.venv/bin/python -m recap ui --jobs-root jobs --sources-root sample_videos
```

The Python server then serves `web/dist/` from `/app/*` with SPA
fallback routing. The React slices so far port the jobs index (`/`),
the transcript workspace (`/job/<id>/transcript`), and a dashboard
job detail page (`/job/<id>`) that renders the hero, stage timeline,
artifact grid, and an insights preview when `insights.json` is
present. A React "start a recap" page at `/app/new` drives
`POST /api/jobs/start` so users can launch a run without touching the
legacy HTML form. Rich-report progress still uses the legacy HTML
routes. No Tailwind, Zustand, Playwright, auth, remote binding,
browser screen recording, or exporter integration is included yet.

The JSON API surface is:

```text
GET  /api/csrf                       token for state-changing POSTs
GET  /api/sources                    video files under --sources-root
GET  /api/engines                    engine availability (no key value)
GET  /api/jobs                       jobs index listing
GET  /api/jobs/<id>                  single-job summary
GET  /api/jobs/<id>/transcript       raw transcript.json
GET  /api/jobs/<id>/insights         parsed insights.json (404 if absent)
GET  /api/jobs/<id>/speaker-names    current speaker-names overlay
POST /api/jobs/<id>/speaker-names    update overlay (CSRF, Host-pinned)
POST /api/jobs/start                 dispatch a new run (CSRF, Host-pinned)
POST /api/recordings                 browser-recorded clip upload (CSRF, Host-pinned)
POST /api/jobs/<id>/runs/insights    dispatch `recap insights` (CSRF, Host-pinned)
GET  /api/jobs/<id>/runs/insights/last      latest insights run status (JSON)
POST /api/jobs/<id>/runs/rich-report dispatch the 11-stage chain (CSRF, Host-pinned)
GET  /api/jobs/<id>/runs/rich-report/last   latest rich-report status (JSON)
GET  /api/jobs/<id>/chapters         merged chapters view (candidates + insights + overlay)
GET  /api/jobs/<id>/chapter-titles   chapter-titles overlay
POST /api/jobs/<id>/chapter-titles   update overlay (CSRF, Host-pinned)
GET  /api/jobs/<id>/frames           merged visual-artifact view (scenes + scores + selected + overlay)
GET  /api/jobs/<id>/frame-review     frame-review overlay
POST /api/jobs/<id>/frame-review     update overlay (CSRF, Host-pinned)
```

### Screenshot / frame review (slice 8)

The React dashboard links to a **frame review workspace** at
`/app/job/<id>/frames`. The page merges every available visual
artifact into a grid of frame cards — one per image in
`candidate_frames/` — with:

- The image itself (served from
  `/job/<id>/candidate_frames/<name>`), a timestamp derived from
  `selected_frames.midpoint_seconds` or the scene's `start_seconds`,
  and the candidate filename.
- Algorithm-output badges (hero / supporting / VLM-rejected / shortlist
  decision / rank) so users can see what the pipeline chose — the
  badges come from `selected_frames.json` and `frame_scores.json`;
  the review overlay never mutates those files.
- Scoring metadata (composite score, CLIP similarity, text novelty,
  VLM relevance + confidence) and any VLM caption.
- Collapsible OCR text pulled from `frame_scores.json`.
- A **Review** fieldset with `keep` / `reject` / `unset` radios and a
  300-char note. Changes batch locally; a toolbar shows the unsaved
  count and a single **Save review** button writes the whole batch
  via `POST /api/jobs/<id>/frame-review`. **Discard changes** reverts.
  Filter tabs (All / Shortlist / Selected / Reviewed) help focus the
  grid on a subset.

The `frame_review.json` overlay is keyed by the frame's basename
(`scene-001.jpg`) and stores `{decision: "keep"|"reject", note}`.
Empty / `unset` decisions remove the mapping. Keys must pass
`is_safe_frame_file` + carry a whitelisted image extension
(`.jpg` / `.jpeg` / `.png`); notes are trimmed and bounded at 300
chars, control chars rejected (tab allowed). The overlay file uses
the same atomic `<file>.tmp` → `os.replace` write and the same
per-job lock as the other overlays, and malformed overlays degrade
silently to the empty default on read. Exporters still render the
algorithm's output — honoring the review overlay in
`recap assemble` / `export-html` / `export-docx` is deferred to the
exporter-overlays slice.

### Chapter sidebar + editable chapter titles (slice 7)

The React transcript workspace at `/app/job/<id>/transcript` renders a
**chapter sidebar** in the left rail when chapter data is available.
Each row shows the chapter's index, display title, and timestamp
range, plus (when insights are present) a short summary, bullets, and
any chapter-scoped action items. Clicking a row seeks
`analysis.mp4` to the chapter's `start_seconds` and resumes playback.
The active chapter highlights as the video plays using the same
`timeupdate` / `seeking` / `play` listeners that drive active-row
sync, and the active state uses both a left accent border and an
`aria-current` attribute so nothing is color-only.

Users rename chapters inline: clicking **Rename** on a row opens a
text field pre-populated with the current title; pressing Enter (or
clicking Save) writes to a new `chapter_titles.json` overlay via
`POST /api/jobs/<id>/chapter-titles`. Clearing the field and saving
removes the custom mapping. Escape cancels. A **custom** pill appears
next to any chapter whose title comes from the overlay rather than
the fallback.

`GET /api/jobs/<id>/chapters` returns a merged view:

- Timing (`start_seconds` / `end_seconds`) and `index` come from
  `chapter_candidates.json` when it exists and validates, otherwise
  from `insights.json`.
- `fallback_title` prefers the insights-provided chapter title, then
  the first sentence of the transcript text, then `"Chapter N"`.
- `custom_title` is the value in `chapter_titles.json` for that
  `index` (empty / whitespace-only values are ignored).
- `display_title = custom_title || fallback_title`.
- `summary` / `bullets` / `action_items` / `speaker_focus` come from
  `insights.json` when available.

The overlay follows the `speaker_names.json` policy: atomic
`<file>.tmp` → `os.replace` write; keys are integer-string indices
(max 120-char values, no control chars); malformed / missing overlays
degrade silently to an empty set; and the overlay never mutates
`chapter_candidates.json` or `insights.json`. Exporter integration
(`recap assemble` / `export-html` / `export-docx`) is tracked as a
follow-up — today the overlay affects the React surface only. The
job dashboard (`/app/job/<id>`) also renders a compact chapters card
with the first few titles and a link to the transcript workspace.

### React run actions + progress (slice 4b)

The `/app/job/<id>` dashboard hosts a **Generate & enrich** panel that
drives two server-side runs through the API:

- **Insights** — `POST /api/jobs/<id>/runs/insights` with a JSON body
  of `{"provider": "mock"|"groq", "force": true|false}`. Defaults to
  `mock`. `groq` requires `GROQ_API_KEY` in the server environment;
  when it's missing, the endpoint returns `400 groq-unavailable`
  without echoing the key. The handler runs the stage as a subprocess
  (`python -m recap insights ...`) so the UI module never imports
  `recap.stages.insights` directly. Success returns `202 Accepted`
  with `{job_id, run_type, status_url, react_detail, started_at,
  provider, force}`.
- **Rich report** — `POST /api/jobs/<id>/runs/rich-report` kicks off
  the same 11-stage chain that the legacy form at
  `/job/<id>/run/rich-report` has been running. Both endpoints share
  the `_background_rich_report` worker and write the same
  `(job_id, "rich-report")` entry in `_last_run`, so the legacy
  status page and the React panel see the same progress.

The React panel polls the status endpoints every ~2.5s while a run is
in flight, renders pending/running/completed/failed state (dot color
*and* labelled text so nothing is color-only), shows the current
rich-report stage and an ordered stage list with failed-stage stderr
inlined as a bounded `<pre>` on failure, and refreshes the job
summary + insights preview on completion. The legacy HTML rich-report
status page at `/job/<id>/run/rich-report/last` stays live as a
fallback.

Both dispatch endpoints reuse the existing safety model: Host
pinning, `X-Recap-Token` CSRF, an 8 KiB body cap, the global
`_run_slot` semaphore, and a per-job lock transferred into the
worker thread. They do **not** add any stage to `_RUNNABLE_STAGES` or
`_LAST_RESULT_STAGES`, do **not** change `cmd_run` composition, and
do **not** change the behavior of the legacy exporter-rerun POST
routes or the `/new` form.

`POST /api/jobs/start` accepts a JSON body of either
`{"source": {"kind": "sources-root", "name": "..."}, "engine": "..."}`
or `{"source": {"kind": "absolute-path", "path": "..."}, "engine": "..."}`,
reuses the legacy `POST /run` safety primitives (Host pinning,
`X-Recap-Token` CSRF, 8 KiB body cap, source-path root containment,
engine allowlist, `DEEPGRAM_API_KEY` check, single `_run_slot`) and the
shared ingest + background-run implementation, and returns 202 with
`{job_id, engine, react_detail, legacy_detail, started_at}`. Validation
failures return JSON `{"error": "...", "reason": "..."}`. The legacy
`POST /run` fallback remains unchanged.

### Browser screen recording

`/app/new` also exposes a **Record screen** tab built on the browser's
Screen Capture API + `MediaRecorder`. The tab is available in any
modern Chromium, Edge, or Firefox; browsers without
`navigator.mediaDevices.getDisplayMedia` or `MediaRecorder` render a
small "not supported" notice instead. Users choose whether to include
microphone audio alongside display audio, click **Start screen
recording**, pick the screen/window/tab in the browser's own picker,
then stop when ready. Stopping produces a local preview —
transcription never starts automatically. A separate **Save to
sources** action uploads the captured clip via `POST /api/recordings`;
after that the recording is selected in the Sources picker and the
user clicks **Start job** to dispatch the run.

`POST /api/recordings` accepts a raw `video/webm` or `video/mp4` body
streamed into `<--sources-root>/recording-<UTC>-<hex>.<ext>` under a
server-picked filename (the browser filename is ignored entirely).
Uploads are bounded to 2 GiB by a Content-Length cap that rejects
oversized requests before reading any bytes; the streaming write is
also capped belt-and-braces. Host pinning and `X-Recap-Token` CSRF
still apply, and no request body, CSRF token, or `DEEPGRAM_API_KEY`
is ever logged. The resulting file appears in `GET /api/sources`
with no further plumbing, so `POST /api/jobs/start` can start a run
from it using the existing
`{"source": {"kind": "sources-root", "name": "..."}}` shape.
Everything stays on the local machine — no third-party upload
endpoint, no authentication, no cloud storage.

### Start a new job from the browser

`GET /new` renders a "Start new job" form that lists video files under
the configured sources root (default `sample_videos/`, configurable
via `recap ui --sources-root <path>`) and offers a free-text path
fallback. Submitting the form `POST`s to `/run`, which validates the
selected path, runs `recap ingest` synchronously, then spawns
`recap run` in a background daemon thread and redirects the browser
to the new job's detail page.

Only files whose extension is in `{.mp4, .mov, .mkv, .webm, .m4v}`
are accepted. The resolved path must live under the sources root; any
path outside it (or any path that isn't a regular file) is rejected
with a one-line error on the same `/new` page. The same CSRF token,
Host pinning, and 4 KiB body cap that guard the existing exporter
rerun POST surface also guard `/run`.

Only **one** `recap run` is allowed to be in flight across the whole
server at a time, enforced by a `threading.Semaphore(1)`. A second
POST while one is running returns 429 with `Retry-After: 30`. The
background subprocess is capped at 1 hour; captured stdout/stderr are
truncated to 8 KiB UTF-8 and cached in memory under `(job_id, "run")`,
visible at `/job/<id>/run/run/last`. The in-memory cache is lost when
the UI server restarts — the on-disk `job.json` and artifacts survive,
but the live subprocess is orphaned.

Browser-initiated runs still shell out exclusively to the CLI
(`python -m recap ingest` then `python -m recap run --job <dir>`).
The UI does not import any stage `run()` function. `recap run`
composition and `job.STAGES` remain unchanged.

Browser **file upload** is not part of this slice; users place videos
under the sources root using whatever tool they prefer (Finder,
`cp`, `scp`, etc.) and pick them from the `/new` dropdown.

The `/new` form also exposes a transcription-engine selector. The
default is `faster-whisper (local)`. A second option, `deepgram
(cloud; diarized speakers)`, is enabled only when the shell that
launched `recap ui` exported `DEEPGRAM_API_KEY` — the UI reads the
variable's presence via `os.environ` and renders a small note
("Deepgram available" or "Not detected"). The key value itself is
never accepted from the browser, never stored in a file, never shown
on any page, never logged. To enable Deepgram, stop the server,
export `DEEPGRAM_API_KEY=<your-key>` in the shell, and restart
`recap ui`. Picking `engine=deepgram` without the key in the server
environment returns a 400 with a clear inline error. The selected
engine is forwarded to the background `recap run` as
`--engine <value>`; the subprocess inherits the server's environment
so the key flows through to the transcribe stage automatically.
Diarized transcripts emit `utterances[]` with integer speaker ids,
which the transcript viewer then renders as colored rows + a
speakers legend.

### Generate rich report

Each job detail page carries a **Generate rich report** button in
the Actions section. Clicking it `POST`s to
`/job/<id>/run/rich-report`, which spawns a daemon thread that runs
this fixed 11-stage chain against the existing job:

1. `recap scenes`
2. `recap dedupe`
3. `recap window`
4. `recap similarity`
5. `recap chapters`
6. `recap rank`
7. `recap shortlist`
8. `recap verify --provider mock`
9. `recap assemble --force`
10. `recap export-html --force`
11. `recap export-docx --force`

Only the `mock` VLM provider is wired into this slice; Gemini is
deliberately not exposed through the dashboard. Skip-aware stages
short-circuit on reruns, so clicking the button again after a
partial failure finishes only the missing work. The three exporters
always run with `--force` so the final artifacts reflect the latest
inputs.

Expected runtime depends mostly on the `recap similarity` stage.
On a fresh checkout the first run downloads the OpenCLIP
`ViT-B-32` OpenAI weights (~350 MB) into the local cache, so the
first rich-report takes several minutes longer than subsequent
runs. `recap dedupe` requires the `tesseract` system binary; if it
is missing the chain stops at that step with a clean failure on
the results page, and the button can be clicked again after
installing it.

The chain shares the existing `_run_slot` semaphore with
`recap run` started from `/new`, so only **one** long-running job
(either a new `recap run` or a rich-report) is allowed at a time
across the whole server. A second click during contention returns
`429` with a `Retry-After` header and a friendly message. A
rich-report also holds the existing per-job lock for its whole
duration, so exporter rerun buttons on the same job return `429`
until the chain finishes.

Progress is visible at `/job/<id>/run/rich-report/last`: while the
chain is in-progress the page auto-refreshes every five seconds
and highlights the currently-running stage; on success it shows
the elapsed time and a link back to the job detail page; on
failure it shows the failed stage's captured `stderr` (truncated
to 8 KiB). The in-memory progress cache is not persisted across
UI server restarts — stop-and-restart loses the progress entry,
but any artifacts already written to disk (scenes.json,
candidate_frames/, report.md, etc.) survive and the button can
simply be re-clicked. `recap run` composition remains Phase-1
only; the browser-started run at `/new` still only executes
ingest → normalize → transcribe → assemble.

### Transcript viewer

Each job detail page includes a **View transcript** link (shown only
when `transcript.json` exists). Following it opens
`GET /job/<id>/transcript`, which renders a server-side HTML table of
the transcript with a `Time` column, an optional `Speaker` column, and
the segment text. The page prefers the Deepgram-style `utterances[]`
data source whenever it contains at least one entry with a valid
speaker id (integer or non-empty string) and non-empty text; otherwise
it falls back to the universal `segments[]` layer and the Speaker
column is omitted. Integer speaker ids render as `Speaker {n}`, string
ids render as the escaped string, and missing/null speakers render as
`—`. A metadata line above the table lists engine, model, language,
row count, and (for utterances) the distinct-speaker count.

Missing `transcript.json` shows `No transcript available yet.` and
still returns 200. Malformed `transcript.json` shows an inline banner
(`transcript.json could not be parsed.`), logs one short
`[recap-ui] transcript skipped: …` line, and still returns 200 —
the rest of the dashboard keeps working. The viewer is strictly
read-only: no editing, no video playback, no row-click handlers yet.
The raw whitelisted artifact route at `/job/<id>/transcript.json` is
unchanged.

Speaker labels are only available today when the transcript came from
Deepgram (`recap transcribe --engine deepgram` or `recap run --engine
deepgram`). Faster-whisper transcripts render without a Speaker
column. Local WhisperX/pyannote diarization remains deferred.

When the job has an `analysis.mp4` on disk (produced by the normalize
stage), the transcript page additionally renders an inline
`<video controls preload="metadata">` player above the table, and each
Time cell becomes a small `<button class="ts">` that sets
`player.currentTime` to that row's start offset. ~10 lines of inline
JavaScript wire the click handler; there is no external script and no
framework. When `analysis.mp4` is absent (jobs mid-run, or imported
without normalize), the player and buttons are silently omitted and
the transcript renders exactly as before.

Diarized transcripts (those whose data source is `utterances[]` with
valid speaker ids) get a pale speaker-tint on each row and a small
legend above the table. The palette has 8 colors; if a transcript has
more than 8 distinct speakers, the classes cycle modulo 8. During
playback the active-row yellow overrides the speaker tint so the
reader can still tell which row is currently playing. Segments-only
transcripts render unchanged, and segments-only pages never emit
speaker classes or the legend. No JavaScript is added for this
colouring — it's pure CSS + server-rendered class names.

As the video plays, the transcript keeps up with it: the row whose
`start` is the greatest value at or below `currentTime` is highlighted
(soft background + a left-accent border so the cue is not color-only),
and the page smoothly scrolls to keep that row in view. Auto-scroll is
suspended for about three seconds after any user scroll or
`ArrowUp` / `ArrowDown` / `PageUp` / `PageDown` / `Home` / `End` key
press, so the page does not fight the reader when they jump elsewhere.
Clicking any timestamp button jumps the video to that row's start and
resumes play. When `analysis.mp4` is absent the player, buttons, and
sync script are all omitted and the transcript renders as a static
table. No speaker-coloured rows, chapter timeline, keyboard shortcuts,
or live-caption effects yet — those remain deferred.

`analysis.mp4` is served with HTTP Range support so browsers can scrub
without downloading the entire file first. The server implements
single-range requests (`Range: bytes=a-b`, `bytes=a-`, and
`bytes=-n`), streams the slice in 64 KiB chunks, returns `206 Partial
Content` with a correct `Content-Range`, and responds `416 Range Not
Satisfiable` for out-of-bounds ranges. Malformed or multi-range
`Range` headers are ignored and fall back to a full-body 200. Every
video response carries `Accept-Ranges: bytes`. Only `analysis.mp4` is
served as video — `original.*` source uploads and other formats are
not on the whitelist. Active-row highlighting, speaker-isolated
audio, and transcript editing remain deferred.

### Read-only Actions block

The per-job detail page exposes an **Actions** block with three small
HTML forms — `Rerun recap assemble`, `Rerun recap export-html`,
`Rerun recap export-docx` — each of which POSTs to
`/job/<id>/run/<stage>` and re-runs the corresponding CLI command with
`--force` as a subprocess under the hood. No other stage is runnable
from the UI: `recap run` and every opt-in pipeline stage (`scenes`,
`dedupe`, `window`, `similarity`, `chapters`, `rank`, `shortlist`,
`verify`) remain CLI-only. Captured `stdout` / `stderr` / exit code
from the most recent run of each exporter are shown at
`/job/<id>/run/<stage>/last`.

Every POST carries a CSRF token generated at server startup and
rendered into each form; the server compares it with
`secrets.compare_digest` and rejects bad or missing tokens with 403.
The server also pins the `Host` header to `127.0.0.1:<port>`, caps
request bodies at 4096 bytes, serializes concurrent runs against the
same job with a per-job `threading.Lock` (returning 429 with
`Retry-After: 2` if another run is in flight), and kills the
subprocess after a 60-second timeout. Captured stdout and stderr are
truncated to 8 KiB UTF-8 before being shown or cached. The server
still binds to `127.0.0.1` only — **do not expose this port to a
network**; the safety model is designed for localhost use only.

The per-job detail page also surfaces a top-of-page **Errors** section
when any stage in `job.json` has `status == "failed"` (one line per
failed stage, in canonical pipeline order), and a **Chapters &
selected frames** section rendered when both `selected_frames.json`
and `chapter_candidates.json` exist and validate. Each chapter block
shows its timestamp, a short snippet of the chapter body text, and
inline thumbnails for the selected hero and supporting frames linked
to the full-size candidate images through the existing
`/job/<id>/candidate_frames/<file>` route. Rejected frames
(`vlm_rejected`) are not rendered. If either artifact is malformed,
the Chapters section is silently omitted and the page still returns
200. No new routes, no new dependencies.

Press `Ctrl-C` in the terminal to stop the server.

### Pre-release validation

A small offline script exercises the three report exporters against a
tiny committed fixture under `scripts/fixtures/minimal_job/`:

```bash
.venv/bin/python scripts/verify_reports.py
```

It runs `recap assemble`, `recap export-html`, and `recap export-docx`
through both the selected-frames path (hero + supporting images with
captions omitted) and the absent-selected path (no Chapters section),
then runs a small set of negative cases — malformed
`selected_frames.json`, traversal `frame_file`, and missing candidate
image — to confirm each command exits `2` with a clean one-line error
and leaves no `.tmp` files behind. It is entirely offline: no model
downloads, no network calls, no API keys. Requires the project's
Python dependencies to be installed (in particular `python-docx`).
Runtime is about one second on a modern laptop. The committed
fixture is never mutated; each case runs in a fresh temp copy.

A second script smoke-validates the legacy dashboard:

```bash
.venv/bin/python scripts/verify_ui.py
```

It copies the fixture into a temp jobs root, picks a free localhost
port, spawns `recap ui` as a subprocess, and uses stdlib `http.client`
(so path segments like `..` are sent verbatim) to check the jobs
index, the per-job detail page, whitelisted JSON and JPEG artifacts,
an unnormalized traversal URL, a non-whitelisted filename, and an
unknown route. It then runs the three report exporters against the
scratch copy and re-checks that `report.html` / `report.docx` / the
referenced candidate-frame JPEG all serve correctly. Stdlib only, no
network, no model downloads; runtime is about half a second. The
UI server is terminated in a `finally` block and the scratch
directory is cleaned up.

The JSON API has its own stdlib verifier:

```bash
.venv/bin/python scripts/verify_api.py
```

It starts `recap ui` against a scratch copy of the fixture and checks
`/api/csrf`, `/api/jobs` (listing + malformed-entry skip),
`/api/jobs/<id>`, `/api/jobs/<id>/transcript`, and
`/api/jobs/<id>/speaker-names`, including CSRF rejection, forged-host
rejection, malformed overlay fallback, key-shape validation, length
validation, successful atomic writes, and clearing a speaker-name
mapping. It does not mutate `scripts/fixtures/*`.

The React workspace is validated with:

```bash
cd web
npm install
npm run build
npm test -- --run
```

`npm run build` type-checks the TypeScript app and emits `web/dist/`
for Python to serve under `/app/*`. The React routes currently are
`/app/` (jobs index with hero stats, search, and status filter) and
`/app/job/<id>/transcript` (transcript workspace with video, speaker
filter chips, and transcript search + highlighting). The Vitest suite
covers the speaker rename form, the speaker legend filter chips, the
jobs-index page (search + status filter), the job card, the
transcript search utilities, the transcript table highlights and
empty states, and the transcript search bar interactions.
`npm audit --audit-level=moderate` should remain clean; runtime
dependencies are intentionally small.

### Structured insights (`recap insights`)

`recap insights --job <path>` is an opt-in slice that reads
`transcript.json` (plus `chapter_candidates.json`, `speaker_names.json`,
and `selected_frames.json` when present) and writes a single
`insights.json` artifact with an overview, quick bullets, per-chapter
title/summary/bullets/action items, and a flat list of action items:

```bash
.venv/bin/python -m recap insights --job jobs/<id> --provider mock
```

Two providers are supported:

- `--provider mock` (default) — deterministic, offline, zero network
  calls. Produces a useful summary derived from the transcript and
  chapter text so local users can inspect the pipeline without any
  credentials.
- `--provider groq` — calls Groq's chat-completions API in strict JSON
  mode using stdlib HTTP (no new Python dependencies). Requires
  `GROQ_API_KEY` in the environment; honors `GROQ_MODEL` (default
  `llama-3.3-70b-versatile`) and `GROQ_BASE_URL`. Fails cleanly with
  a one-line error when the key is missing. Transcript input is
  truncated to 48 000 characters and per-chapter text to 2 000
  characters to keep request size bounded.

`recap insights` is **not** part of `job.STAGES` and is **not** invoked
by `recap run`. When `insights.json` exists, `recap assemble`,
`recap export-html`, and `recap export-docx` automatically enrich their
output with:

- an `## Overview` section (short + detailed summary, quick bullets,
  action items with timestamp + chapter suffixes);
- per-chapter titles and summaries inside the existing `## Chapters`
  section when `selected_frames.json` is also present, or a standalone
  chapter list built from insights alone when it is not.

When `insights.json` is absent, exports stay byte-compatible with
today's output. Re-running `recap insights` without `--force` skips
when the artifact already exists. The API surfaces the artifact flag
(`insights_json`) and a raw URL at `/job/<id>/insights.json`, and the
React jobs index shows an "Insights" chip on each `JobCard`.

### Cloud transcription (Deepgram)

`faster-whisper` is the default transcription engine for both
`recap run` and `recap transcribe`. An optional cloud engine is
available via `--engine deepgram` and is opt-in at the command line:

```bash
.venv/bin/python -m recap transcribe --job jobs/<job_id> --engine deepgram --force
```

Environment variables (read from the process environment; no `.env`
loader):

- `DEEPGRAM_API_KEY` — required when a Deepgram recompute is needed.
  A skip path (stored `engine` and `model` already match the
  requested ones) does NOT require the key.
- `DEEPGRAM_MODEL` — optional override of the pinned default
  `"nova-3"`.
- `DEEPGRAM_BASE_URL` — optional override of
  `"https://api.deepgram.com"`.

Deepgram output is additive: `transcript.json` keeps the same
`segments` / `duration` shape every existing stage reads, and gains
optional `utterances`, `speakers`, `words`, and `provider_metadata`
fields containing diarized utterance data (integer speaker cluster
ids), a per-speaker summary, word-level timestamps when Deepgram
returns them, and the request parameters used. `faster-whisper`
transcripts are unchanged on disk — they do not emit those fields.

Downstream stages work unchanged over either engine's output.
`recap window`, `recap rank`, `recap shortlist`, and `recap
assemble` consume the existing `segments` / `duration` / chapter
contracts. `recap chapters` additionally reads the optional
`utterances` list when present and fuses speaker-change boundaries
on top of its existing pause-based boundaries, and — when
`scenes.json` is present, not a fallback, and carries at least one
scene cut that maps to a segment boundary — also fuses scene-cut
boundaries (see the Phase 3 section above); faster-whisper
transcripts without `scenes.json` continue to produce pause-only
chapters with output byte-identical to the pre-scene-fusion version
of that stage. Topic-shift detection, speaker recognition / manual
labeling, chapter titling, WhisperX, pyannote, Groq, captions,
report screenshot embedding, `selected_frames.json`, UI, and
exports remain deferred.

### Sample videos

Local recordings for development and validation runs live in
`sample_videos/`. They are not required by the code — they are there so you
can exercise the full Phase 1 flow end-to-end without hunting for a
recording. Example:

```bash
.venv/bin/python -m recap run \
  --source "sample_videos/Cap Upload - 24 February 2026.mp4" \
  --model small
```

Quote paths that contain spaces. Add or remove files freely; the directory
holds fixtures only and is not read by the pipeline except as the `--source`
you pass in.
