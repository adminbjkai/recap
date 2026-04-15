# Recap — Phase 1 Handoff

This document closes out Phase 1 of Recap. It reflects the current code in
this repository — not a plan, not a roadmap. Anything not listed here is
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

Stages 4 through 7 from the brief are **not** implemented. No chaptering,
scene detection, frame extraction, pHash/SSIM, OCR, OpenCLIP, or VLM code
exists in the repository.

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
- **Python package**: `faster-whisper>=1.0.3` (pinned in
  `requirements.txt` and `pyproject.toml`). First transcription download
  fetches the requested Whisper model (default `small`) from the internet;
  subsequent runs use the local cache.
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
  `status` and `error`.
- `metadata.json` — raw `ffprobe -show_format -show_streams` JSON of the
  original.
- `analysis.mp4` — normalized H.264 + AAC video.
- `audio.wav` — 16 kHz mono PCM `s16le`.
- `transcript.json` — normalized transcript (shape below).
- `transcript.srt` — SubRip captions generated from the same segments.
- `report.md` — basic Markdown report built from `job.json`,
  `metadata.json`, and `transcript.json`.

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
  `transcript.srt`, `report.md`) and resets the `normalize`, `transcribe`,
  and `assemble` stage entries to `pending`, so the next `recap run`
  regenerates them cleanly from the new source.
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

- Phase 2: PySceneDetect scene boundaries (`scenes.json`), candidate frame
  extraction (`candidate_frames/`), pHash deduplication, SSIM checks,
  Tesseract OCR, and `frame_scores.json`.
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

## Phase 1 closeout

Phase 1 is complete, audited, hardened, and validated end-to-end on a
real speech sample. The required artifacts are produced, the pipeline is
restartable from disk, `job.json` reflects per-stage and overall state,
and the output remains Markdown-first. No Phase 2+ scaffolding has been
introduced. Further work should begin a separate, explicitly approved
Phase 2 task.
