# Recap

Recap is an automated video-to-documentation pipeline for turning screen recordings into structured, chaptered documentation with a small set of relevant screenshots.

The system is designed around a staged cascade: cheap deterministic processing first, semantic alignment on a reduced candidate set, and optional VLM checks only on the final shortlist of frames.

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
- `selected_frames.json`
- `report.md`

Optional downstream outputs include `report.docx` and `report.html`.

## Phase 1

Phase 1 delivers the reliable core:

- ingest
- FFmpeg normalization
- transcription
- basic Markdown text output

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
.venv/bin/python -m recap assemble   --job jobs/<job_id>
.venv/bin/python -m recap status     --job jobs/<job_id>
```

`recap scenes` is the Stage 5 (Phase 2) entry point and is not invoked
by `recap run`. It writes `scenes.json` and `candidate_frames/`.
`recap dedupe` is the pHash + SSIM duplicate-marking and Tesseract OCR
novelty-scoring slice and is also not invoked by `recap run`; it reads
`scenes.json` plus the JPEGs in `candidate_frames/` and writes
`frame_scores.json`. It requires the system `tesseract` binary
(`brew install tesseract` on macOS, `apt-get install tesseract-ocr` on
Debian/Ubuntu).

Stages skip work when their artifacts already exist. Pass `--force` to
recompute a stage.

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
