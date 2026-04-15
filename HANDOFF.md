# Recap — Phase 1 Handoff (+ Phase 2 checklist complete)

This document closes out Phase 1 of Recap and records the Phase 2
slices approved and implemented so far: Stage 5 candidate frame
extraction, and the combined pHash + SSIM duplicate marking with
Tesseract OCR novelty scoring. All checklist items in
`TASKS.md` Phase 2 are ticked; transcript-window alignment, OpenCLIP
similarity, chaptering, VLM verification, and export formats remain
Phase 3/4 work. This file reflects the current code in this
repository — not a plan, not a roadmap. Anything not listed here is
explicitly deferred.

Binding references: `MASTER_BRIEF.md`, `ARCHITECTURE.md`, `TASKS.md`,
`DECISIONS.md`, `AGENTS.md`, `README.md`, `PRD.md`.

## What Phase 1 includes

Phase 1 implements only the "reliable core" stages from the brief:

- **Stage 1 — Ingest.** Accept a source video, create a per-job working
  directory, copy the source in as `original.<ext>`, initialize `job.json`.
- **Stage 2 — Normalize.** Run `ffprobe` → `metadata.json`, transcode with
  `ffmpeg` → `analysis.mp4` (H.264 / AAC / `yuv420p` / `+faststart`), and
  extract `audio.wav` as 16 kHz mono PCM `s16le`.
- **Stage 3 — Transcribe.** Run `faster-whisper` on `audio.wav` and write
  `transcript.json` and `transcript.srt`.
- **Stage 8 — Basic Markdown assembly.** Read real artifacts and write
  `report.md` with media summary and timestamped transcript segments.

Stage 5 is implemented as the first approved Phase 2 slice (see the
next section). Every item in the `TASKS.md` Phase 2 checklist is
complete: Stage 5 candidate frame extraction lives under
`recap scenes`, and pHash duplicate marking, SSIM borderline checks,
and Tesseract OCR novelty scoring live under `recap dedupe`. The
broader target-architecture Stage 6 from the brief also names
transcript-window alignment and OpenCLIP similarity, which remain
deferred to Phase 3 along with chaptering (Stage 4) and VLM
verification (Stage 7). No OpenCLIP or VLM code exists in the
repository.

## What the Phase 2 slices include

- **Stage 5 — Candidate frame extraction.** Run PySceneDetect's
  `ContentDetector` against `analysis.mp4`, write `scenes.json` (scene
  list with start/end timestamps and frame numbers, per-scene
  `frame_file`, plus a `fallback` flag), and extract one representative
  frame per scene into `candidate_frames/`. If the detector finds no
  cuts, a single full-video fallback scene is written so there is always
  one candidate frame.
- **pHash + SSIM duplicate marking with OCR novelty.** Read
  `scenes.json` and the JPEGs in `candidate_frames/`, compute an
  ImageHash `phash` per frame (hash size 8 → 64-bit hash), and compare
  each frame to its immediate predecessor with Hamming distance. Frames
  at or below a fixed code-level threshold are marked as duplicates of
  their predecessor. For adjacent pairs whose pHash Hamming distance
  is strictly above `DUPLICATE_THRESHOLD` and at or below
  `SSIM_DISTANCE_BAND_MAX`, SSIM is computed on the grayscale frames
  with `skimage.metrics.structural_similarity`; pairs whose SSIM
  reaches `SSIM_DUPLICATE_THRESHOLD` are promoted to duplicates of
  their predecessor. Every frame is also passed through Tesseract via
  `pytesseract.image_to_string`; the output is whitespace-normalized
  (internal whitespace collapsed, leading/trailing trimmed) and stored
  per frame as `ocr_text`. A `text_novelty` score is computed against
  the immediate predecessor's `ocr_text` as
  `1.0 - difflib.SequenceMatcher(None, prev, curr).ratio()`; it is an
  additional signal only and does not influence `duplicate_of`.
  Results are written to `frame_scores.json` with per-frame entries
  (`scene_index`, `frame_file`, `phash`, `duplicate_of`,
  `hamming_distance`, `ssim`, `ocr_text`, `text_novelty`) and
  top-level metadata (`video`, `metric=phash+ssim+ocr`, `hash_size`,
  `duplicate_threshold`, `ssim_distance_band_max`,
  `ssim_duplicate_threshold`, `ocr_engine=tesseract`, `frame_count`,
  `duplicate_count`, `ssim_computed_count`,
  `ocr_frames_with_text_count`). `ssim` is `null` for the first frame,
  for pairs outside the band, and for pairs already marked duplicate
  by pHash. `ocr_text` is always a string (possibly `""`);
  `text_novelty` is `null` for the first frame. No frames are deleted,
  renamed, or moved.

Both Phase 2 entry points are opt-in. `recap run` continues to execute
the Phase 1 stages only. Stage 5 runs via `recap scenes --job <path>`;
pHash + SSIM duplicate marking with OCR novelty runs via
`recap dedupe --job <path>`. All Phase 2 checklist items are
implemented; broader Stage 6 work (transcript-window alignment,
OpenCLIP similarity) remains Phase 3.

## Running Phase 1 locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# full pipeline on a new job
.venv/bin/python -m recap run --source path/to/recording.mp4 --model small

# per-stage / resume
.venv/bin/python -m recap ingest     --source recording.mp4
.venv/bin/python -m recap normalize  --job jobs/<job_id>
.venv/bin/python -m recap transcribe --job jobs/<job_id> --model small
.venv/bin/python -m recap scenes     --job jobs/<job_id>
.venv/bin/python -m recap dedupe     --job jobs/<job_id>
.venv/bin/python -m recap assemble   --job jobs/<job_id>
.venv/bin/python -m recap status     --job jobs/<job_id>
```

CLI flags that apply to most subcommands: `--job <path>` to target an
existing job directory, `--jobs-root <path>` to change where new jobs are
created (default `./jobs`), `--force` to recompute a stage even when its
artifacts already exist. `recap run` and `recap transcribe` also accept
`--model` (default `small`).

Unexpected misuse (missing source, missing `ffmpeg`/`ffprobe`, re-ingest
with a different source without `--force`) prints a one-line
`error: ...` message to stderr and exits with code 2 instead of a Python
traceback.

Local sample recordings for development and validation runs live in
`sample_videos/`. They are fixtures only — the pipeline does not read the
directory itself, it reads whatever path you pass via `--source`. A full
Phase 1 run against a sample:

```bash
.venv/bin/python -m recap run \
  --source "sample_videos/Cap Upload - 24 February 2026.mp4" \
  --model small
```

## Dependencies and environment assumptions

- **Python**: 3.10, 3.11, 3.12, or 3.13. Python 3.14 is not supported
  because `faster-whisper`'s `ctranslate2` dependency has no 3.14 wheels
  yet and source builds typically fail. The README recommends 3.12.
- **System binaries**: both `ffmpeg` and `ffprobe` must be on `PATH`
  (`brew install ffmpeg` on macOS, `apt-get install ffmpeg` on
  Debian/Ubuntu). `recap dedupe` additionally requires `tesseract`
  (`brew install tesseract` on macOS, `apt-get install tesseract-ocr`
  on Debian/Ubuntu). The stages resolve these via `shutil.which` and
  raise a clear install hint if any is missing.
- **Python packages**: `faster-whisper>=1.0.3`,
  `scenedetect[opencv]>=0.6.4`, `ImageHash>=4.3.1`, `Pillow>=10.0.0`,
  `scikit-image>=0.22`, and `pytesseract>=0.3.10` (all pinned in
  `requirements.txt` and `pyproject.toml`). First transcription
  downloads the requested Whisper model (default `small`) from the
  internet; subsequent runs use the local cache. PySceneDetect ships
  its own opencv-python wheel via the `[opencv]` extra and runs
  entirely offline. ImageHash pulls in Pillow, NumPy, SciPy, and
  PyWavelets; scikit-image pulls in imageio, tifffile, networkx, and
  lazy-loader; pytesseract is a thin wrapper around the system
  `tesseract` binary. All run locally.
- **Compute**: the stage instantiates `WhisperModel(model, device="cpu",
  compute_type="int8")`. No GPU configuration is wired up.

## Artifacts produced per job

Every successful Phase 1 job produces the following files inside its job
directory:

- `original.<ext>` — the ingested source file (extension preserved).
- `job.json` — job identity (`job_id`, `source_path`,
  `original_filename`, `created_at`), per-stage status
  (`pending`/`running`/`completed`/`failed` with `started_at`,
  `finished_at`, and `error` when applicable), and a rolled-up top-level
  `status` and `error`. The top-level rollup is driven only by the four
  Phase 1 stages (`ingest`, `normalize`, `transcribe`, `assemble`) so a
  Phase-1-only `recap run` reaches `completed`.
- `metadata.json` — raw `ffprobe -show_format -show_streams` JSON of the
  original.
- `analysis.mp4` — normalized H.264 + AAC video.
- `audio.wav` — 16 kHz mono PCM `s16le`.
- `transcript.json` — normalized transcript (shape below).
- `transcript.srt` — SubRip captions generated from the same segments.
- `report.md` — basic Markdown report built from `job.json`,
  `metadata.json`, and `transcript.json`. `report.md` does not yet
  embed scene data.

Running `recap scenes --job <path>` adds the Stage 5 outputs:

- `scenes.json` — `video`, `detector`, `threshold`, `fallback`,
  `scene_count`, `frames_dir`, and a `scenes` list. Each scene entry
  has `index` (1-based), `start_seconds`, `end_seconds`, `start_frame`,
  `end_frame`, `midpoint_seconds`, and `frame_file`.
- `candidate_frames/scene-NNN.jpg` — one representative JPEG per scene.

Running `recap dedupe --job <path>` adds the pHash + SSIM + OCR slice
output:

- `frame_scores.json` — top-level `video`, `scenes_source`,
  `frames_dir`, `metric` (`phash+ssim+ocr`), `hash_size`,
  `duplicate_threshold`, `ssim_distance_band_max`,
  `ssim_duplicate_threshold`, `ocr_engine` (`tesseract`),
  `frame_count`, `duplicate_count`, `ssim_computed_count`,
  `ocr_frames_with_text_count`, and a `frames` list with one entry per
  scene: `scene_index`, `frame_file`, `phash`,
  `hamming_distance` (null for the first frame, integer otherwise),
  `ssim` (float when SSIM was computed for that pair, else null),
  `ocr_text` (whitespace-normalized string, possibly `""`),
  `text_novelty` (null for the first frame, else
  `1.0 - difflib.SequenceMatcher(None, prev_text, curr_text).ratio()`),
  and `duplicate_of` (predecessor `scene_index` when `hamming_distance`
  is at or below the pHash threshold, or when `ssim` reaches
  `ssim_duplicate_threshold`; else null). OCR does not influence
  `duplicate_of`.

The `stages.scenes` and `stages.dedupe` entries on `job.json` appear
the first time each stage runs (they are intentionally not pre-populated
for new jobs, so the rollup is not held back by unmet Phase 2
obligations).

Job directories are created under `./jobs/` by default (the directory is
in `.gitignore`). Job IDs have the form `YYYYMMDD-HHMMSS-<8hex>`.

`report.md` deliberately does not claim chapters, screenshots, or VLM
verification. It contains only a media summary and a timestamped list of
transcript segments — whatever is actually on disk.

## Restart and resume behavior

- Each stage checks for its own outputs before running. If the expected
  artifacts exist and `--force` is not set, the stage short-circuits and
  marks itself `completed` (with `skipped: true` where relevant). Re-running
  `recap run --job <existing>` against a fully-completed job finishes in
  well under a second.
- `--force` recomputes the target stage. For `normalize`, each sub-output
  (`metadata.json`, `analysis.mp4`, `audio.wav`) is checked individually.
- **Ingest safety.** If `recap ingest` is invoked against an existing job
  with a `--source` path different from the one recorded in `job.json`, it
  refuses and exits 2 with a message naming both sources. Re-running with
  `--force` replaces the original and invalidates the downstream artifacts
  (`metadata.json`, `analysis.mp4`, `audio.wav`, `transcript.json`,
  `transcript.srt`, `scenes.json`, `frame_scores.json`, `report.md`,
  and the `candidate_frames/` directory) and resets the `normalize`,
  `transcribe`, `scenes`, `dedupe`, and `assemble` stage entries to
  `pending`, so the next `recap run` (plus an explicit `recap scenes`
  and `recap dedupe` if the Phase 2 slices were in use) regenerates them
  cleanly from the new source.
- **Stage 5 restart.** `recap scenes` skips when `scenes.json` is
  present and every `frame_file` it lists is on disk; otherwise it
  recomputes. `recap scenes --force` removes `scenes.json` and the
  `candidate_frames/` directory in full before re-running.
- **`recap dedupe` restart.** `recap dedupe` skips when
  `frame_scores.json` already matches the current `scenes.json` and
  `candidate_frames/` — same metric (`phash+ssim+ocr`), hash size,
  pHash threshold, SSIM band, SSIM threshold, and `ocr_engine`, same
  scene indices and frame files, every frame file still on disk, and
  every entry carries an `ocr_text` string and a `text_novelty` key.
  Any drift (including a pre-OCR `metric=phash+ssim` or even earlier
  `metric=phash` file written by an earlier version) triggers a
  recompute. `recap dedupe --force` removes `frame_scores.json`
  before recomputing. Missing `scenes.json`, missing
  `candidate_frames/`, any scene whose `frame_file` is absent from
  disk, a malformed `scenes.json`, or a missing `tesseract` binary
  (only on the recompute path) exits 2 with a one-line `error: ...`
  message.
- Failures are recorded on the failing stage with `status: failed` and an
  `error` string, and surfaced as the top-level `status`/`error` on
  `job.json`. Re-running the command (or a specific subcommand) retries
  from that stage.

## Transcription behavior and the swap seam

The default and only shipped engine is `faster-whisper`. `transcript.json`
has this stable shape:

```json
{
  "engine": "faster-whisper",
  "provider": null,
  "model": "small",
  "language": "en",
  "language_probability": 0.99,
  "duration": 123.45,
  "segments": [
    {"id": 0, "start": 0.0, "end": 3.08, "text": "..."}
  ]
}
```

`engine`, `provider`, `model`, and `segments` are the stable contract read
by downstream code. `provider` is `null` for local engines and is the only
addition compared with a strictly-local Whisper setup.

**Swap seam (present, narrow, not implemented for any other engine).** The
transcription stage is a function-level strategy. `recap/stages/
transcribe.py` is the only file in the project that imports
`faster_whisper` (verified). To add a new engine later (Deepgram, Groq, an
OpenRouter-hosted Whisper, Nvidia-hosted, Gemma, or another Whisper
variant), add a sibling `_transcribe_<name>(audio, model_name) -> dict`
that returns the same shape and add a branch on `engine` inside `run()`.
No other file, schema, CLI flag, or artifact is expected to change.

No registry, abstract base class, plugin system, config file, or env-var
indirection is in place or planned for Phase 1 — and per the docstring in
`transcribe.py` should not be added.

## Known limitations and assumptions

- **Single-engine.** Only `faster-whisper` is implemented. `WhisperX` is
  listed as optional in `TASKS.md` but intentionally not wired up; the
  seam above is the integration point when it or another engine is added.
- **CPU-only transcription.** The model is instantiated on CPU with
  `int8` quantization; no GPU or batched-pipeline configuration is
  exposed.
- **Empty-speech handling.** Videos with no speech produce a valid
  `transcript.json` with `segments: []` and an empty `transcript.srt`.
  The report honestly reports `Segments: 0`.
- **Metadata comes from `original.*`, not `analysis.mp4`.** This matches
  the brief's Stage 1 definition; values such as audio sample rate in
  `report.md` reflect the original container.
- **Model download on first run.** First transcription requires network
  access to fetch the Whisper weights into the local cache.
- **Local-first, single-process.** No queue, worker pool, remote
  orchestration, plugin system, or service layer. Everything runs in the
  calling process and writes directly into the job directory.

## Explicitly deferred to Phase 2 and later

Per `AGENTS.md`, `DECISIONS.md`, and `TASKS.md`, the following belong to
later phases and are **not** present in the current codebase:

- Phase 3: chapter proposal from transcript/scene fusion
  (`chapter_candidates.json`), fuzzy transcript-window alignment,
  OpenCLIP similarity scoring, and the screenshot keep/reject rules.
  The target-architecture Stage 6 in the brief also places transcript
  alignment and OpenCLIP similarity inside Stage 6; both are deferred
  to Phase 3 by design.
- Phase 4: optional VLM verification on finalists only
  (`selected_frames.json`), caption generation, chapter-aware Markdown
  assembly with embedded screenshots, and optional DOCX / HTML / Notion /
  PDF export.
- WhisperX as an optional word-level precision path.

These names are preserved in the binding docs and the artifact layout
section of `ARCHITECTURE.md`, but no code, interface, stub, or
configuration for any of them exists in the repo.

## Phase 1 closeout (+ Phase 2 checklist complete)

Phase 1 is complete, audited, hardened, and validated end-to-end on a
real speech sample. The required artifacts are produced, the pipeline
is restartable from disk, `job.json` reflects per-stage and overall
state, and the output remains Markdown-first. Two opt-in Phase 2 entry
points are implemented: Stage 5 candidate frame extraction
(`recap scenes` → `scenes.json` + `candidate_frames/`) and the combined
pHash + SSIM duplicate marking with Tesseract OCR novelty scoring
(`recap dedupe` → `frame_scores.json`). Every item in the `TASKS.md`
Phase 2 checklist is now ticked. Both entry points have been validated
against a multi-scene sample and the single-scene fallback, including
legacy-metric auto-recompute, skip-on-rerun, `--force` recompute, and
clean `error: ... / exit 2` paths for missing `scenes.json`, missing
`candidate_frames/`, malformed `scenes.json`, and missing `tesseract`.
No Phase 3+ scaffolding has been introduced. Further work should
begin a separate, explicitly approved Phase 3 chunk.
