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
- Chapter proposal — reads `transcript.json` and writes
  `chapter_candidates.json`. A boundary is placed between adjacent
  transcript segments whenever their gap is at least
  `PAUSE_SECONDS = 2.0`. When the transcript additionally contains a
  non-empty `utterances` list with at least one non-null `speaker`
  id (Deepgram path), a boundary is also placed on every adjacent
  segment pair whose speaker ids differ. Either signal is enough;
  both on the same pair is recorded as `trigger="pause+speaker"`.
  Chapters shorter than `MIN_CHAPTER_SECONDS = 30.0` are iteratively
  merged to avoid over-fragmentation — the merge is content-agnostic
  and speaker-only groups are legitimate merge candidates. The first
  chapter is always `trigger="start"`; boundary-created chapters use
  `"pause"`, `"speaker"`, or `"pause+speaker"`. `source_signal` is
  `"pauses"` when utterances are absent (faster-whisper) or present
  but empty / all-null-speaker, and `"pauses+speakers"` in
  speaker-aware mode. A top-level `speaker_change_count` counts
  pre-merge speaker-change boundaries; it appears only in
  speaker-aware mode and is deliberately pre-merge so the raw signal
  is observable even after short speaker-only groups are merged
  away. All thresholds and source-signal tokens are fixed at the
  code level. Scene-boundary fusion, topic-shift detection, speaker
  recognition / manual labels, and LLM chapter titling remain
  deferred. Pure stdlib, no new dependencies. Run via
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
`recap chapters` is the chaptering slice and is also not invoked by
`recap run`; it reads only `transcript.json` and writes
`chapter_candidates.json` with one entry per chapter (`index`,
`start_seconds`, `end_seconds`, `first_segment_id`,
`last_segment_id`, `segment_ids`, `text`, `trigger`) and a
top-level `source_signal` ∈ {`"pauses"`, `"pauses+speakers"`}. On
faster-whisper transcripts the slice is pause-only and the output
is byte-identical to the previous version of the stage; on
Deepgram transcripts it additionally fuses speaker-change
boundaries and emits a top-level `speaker_change_count`. It does
not consult scene boundaries, embeddings, speaker recognition, or
LLM chapter titling. It is pure stdlib and requires no new
dependencies or system binaries.
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
(reserved for Phase 4 post-VLM finalists), invoke any VLM, generate
captions, embed screenshots in `report.md`, export DOCX / HTML /
Notion / PDF, add UI, or do any speaker diarization / recognition /
separation work. Blur / low-information detection and
VLM-dependent "shows code / diagrams / settings / dashboards"
judgments are deferred. It is pure stdlib and requires no new
dependencies or system binaries.

Stages skip work when their artifacts already exist. Pass `--force` to
recompute a stage.

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
on top of its existing pause-based boundaries (see the Phase 3
section above); faster-whisper transcripts — which carry no
`utterances` — continue to produce pause-only chapters with output
byte-identical to the pre-Deepgram version of that stage. Speaker
recognition / manual labeling, WhisperX, pyannote, Groq, captions,
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
