# Recap — Phase 1 Handoff (+ Stage 5 and pHash slices)

This document closes out Phase 1 of Recap and records the Phase 2 slices
approved and implemented so far: Stage 5 candidate frame extraction and
pHash-based duplicate marking. It reflects the current code in this
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
next section). Stage 6 is **partially** implemented via the pHash
duplicate-marking slice; SSIM and OCR remain unimplemented. Stages 4
and 7 from the brief are **not** implemented. No chaptering, SSIM,
OCR, OpenCLIP, or VLM code exists in the repository.

## What the Phase 2 slices include

- **Stage 5 — Candidate frame extraction.** Run PySceneDetect's
  `ContentDetector` against `analysis.mp4`, write `scenes.json` (scene
  list with start/end timestamps and frame numbers, per-scene
  `frame_file`, plus a `fallback` flag), and extract one representative
  frame per scene into `candidate_frames/`. If the detector finds no
  cuts, a single full-video fallback scene is written so there is always
  one candidate frame.
- **pHash duplicate marking.** Read `scenes.json` and the JPEGs in
  `candidate_frames/`, compute an ImageHash `phash` per frame (hash
  size 8 → 64-bit hash), and compare each frame to its immediate
  predecessor with Hamming distance. Frames at or below a fixed
  code-level threshold are marked as duplicates of their predecessor.
  Results are written to `frame_scores.json` with per-frame entries
  (`scene_index`, `frame_file`, `phash`, `duplicate_of`,
  `hamming_distance`) and top-level metadata (`video`, `metric=phash`,
  `hash_size`, `duplicate_threshold`, `frame_count`, `duplicate_count`).
  No frames are deleted, renamed, or moved.

Both slices are opt-in. `recap run` continues to execute the Phase 1
stages only. Stage 5 runs via `recap scenes --job <path>`; pHash
duplicate marking runs via `recap dedupe --job <path>`. The remaining
Phase 2 work (SSIM, OCR) is not yet implemented.

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
  Debian/Ubuntu). The stages resolve these via `shutil.which` and raise a
  clear install hint if either is missing.
- **Python packages**: `faster-whisper>=1.0.3`,
  `scenedetect[opencv]>=0.6.4`, `ImageHash>=4.3.1`, and `Pillow>=10.0.0`
  (all pinned in `requirements.txt` and `pyproject.toml`). First
  transcription downloads the requested Whisper model (default `small`)
  from the internet; subsequent runs use the local cache. PySceneDetect
  ships its own opencv-python wheel via the `[opencv]` extra and runs
  entirely offline. ImageHash pulls in Pillow, NumPy, SciPy, and
  PyWavelets; all run locally.
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

Running `recap dedupe --job <path>` adds the pHash slice output:

- `frame_scores.json` — top-level `video`, `scenes_source`,
  `frames_dir`, `metric` (`phash`), `hash_size`, `duplicate_threshold`,
  `frame_count`, `duplicate_count`, and a `frames` list with one entry
  per scene: `scene_index`, `frame_file`, `phash`,
  `hamming_distance` (null for the first frame, integer otherwise), and
  `duplicate_of` (predecessor `scene_index` when `hamming_distance` is
  at or below the threshold, else null).

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
- **pHash dedupe restart.** `recap dedupe` skips when
  `frame_scores.json` already matches the current `scenes.json` and
  `candidate_frames/` — same metric/hash-size/threshold, same scene
  indices and frame files, every frame file still on disk. Any drift
  triggers a recompute. `recap dedupe --force` removes
  `frame_scores.json` before recomputing. Missing `scenes.json` or
  `candidate_frames/`, or any scene whose `frame_file` is absent from
  disk, exits 2 with a one-line `error: ...` message.
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

- Remaining Phase 2: SSIM borderline checks and Tesseract OCR novelty
  scoring (both would extend `frame_scores.json` with additional
  per-frame fields).
- Phase 3: chapter proposal from transcript/scene fusion
  (`chapter_candidates.json`), fuzzy transcript-window alignment,
  OpenCLIP similarity scoring, and the screenshot keep/reject rules.
- Phase 4: optional VLM verification on finalists only
  (`selected_frames.json`), caption generation, chapter-aware Markdown
  assembly with embedded screenshots, and optional DOCX / HTML / Notion /
  PDF export.
- WhisperX as an optional word-level precision path.

These names are preserved in the binding docs and the artifact layout
section of `ARCHITECTURE.md`, but no code, interface, stub, or
configuration for any of them exists in the repo.

## Phase 1 closeout (+ Phase 2 slices)

Phase 1 is complete, audited, hardened, and validated end-to-end on a
real speech sample. The required artifacts are produced, the pipeline
is restartable from disk, `job.json` reflects per-stage and overall
state, and the output remains Markdown-first. Two Phase 2 slices are
also implemented as opt-in subcommands: Stage 5 candidate frame
extraction (`recap scenes` → `scenes.json` + `candidate_frames/`) and
pHash duplicate marking (`recap dedupe` → `frame_scores.json`). Both
have been validated against a multi-scene sample and the single-scene
fallback, including skip-on-rerun and `--force` recompute. No further
Phase 2+ scaffolding has been introduced. Further work should begin a
separate, explicitly approved Phase 2 chunk.
