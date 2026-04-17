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

## Phase 3 (in progress)

Phase 3 adds semantic alignment on top of Phase 2. Four slices are
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
- Pause-only chapter proposal (first chaptering slice) — reads
  `transcript.json` and writes `chapter_candidates.json`. A boundary
  is placed between adjacent transcript segments whenever their gap
  is at least `PAUSE_SECONDS = 2.0`; chapters shorter than
  `MIN_CHAPTER_SECONDS = 30.0` are iteratively merged to avoid
  over-fragmentation. The first chapter starts at `0.0` with
  `trigger="start"`; boundary-created chapters use `trigger="pause"`.
  Both constants and `SOURCE_SIGNAL = "pauses"` are fixed at the code
  level. This is not full Stage 4 chaptering — it uses pauses only.
  Scene-boundary fusion, topic-shift detection, speaker-change
  detection, and LLM titling remain deferred to later Phase 3 slices.
  Pure stdlib, no new dependencies. Run via
  `recap chapters --job <path>` after `recap transcribe`. `recap run`
  does not invoke this stage.
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
  not invoke this stage. The rest of Phase 3 (keep/reject rules) is
  not implemented.

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
`recap chapters` is the first chaptering slice — a pause-only
proposal — and is also not invoked by `recap run`; it reads only
`transcript.json` and writes `chapter_candidates.json` with one entry
per chapter (`index`, `start_seconds`, `end_seconds`,
`first_segment_id`, `last_segment_id`, `segment_ids`, `text`,
`trigger`). This is not full Stage 4 chaptering: it uses transcript
pause gaps only (`PAUSE_SECONDS = 2.0`) with a minimum-chapter-length
merge (`MIN_CHAPTER_SECONDS = 30.0`). It does not consult scene
boundaries, embeddings, or speaker diarization, and does not generate
chapter titles. It is pure stdlib and requires no new dependencies or
system binaries.
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
