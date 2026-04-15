# Recap — Continuation Guide

This file exists so a future session can resume from the current repo
state without re-deriving context. It is not a roadmap. For what the
system does and produces, read `HANDOFF.md`.

## Current state

- Phase 1 of Recap is implemented, audited, hardened, and closed out.
- Two Phase 2 opt-in entry points are implemented: Stage 5 candidate
  frame extraction (`recap scenes`) and the combined pHash + SSIM
  duplicate marking with Tesseract OCR novelty scoring
  (`recap dedupe`). Every item in the `TASKS.md` Phase 2 checklist is
  ticked.
- The first Phase 3 slice is implemented: transcript-window alignment
  per candidate frame (`recap window` → `frame_windows.json`, ±6 s
  fixed window around each scene midpoint). The remaining Phase 3
  bullets (chapter proposal, OpenCLIP similarity, keep/reject rules)
  and all of Phase 4 remain out of scope.
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

Phase 3 (first slice only):

- Transcript-window alignment (`frame_windows.json`, opt-in via
  `recap window --job <path>`; for each candidate frame, collects the
  transcript segments that overlap a fixed ±`WINDOW_SECONDS = 6.0`
  window around `midpoint_seconds` with strict inequalities, clamps
  the upper bound to `transcript.duration` when present, records the
  overlapping segment ids in transcript order, and stores the
  whitespace-normalized concatenation of their text as `window_text`;
  pure stdlib, no new dependencies)

Stages 4 and 7 are deliberately absent. Stage 6 is complete for the
Phase 2 checklist (pHash, SSIM, and OCR all shipped) and now also
includes transcript-window alignment as the first Phase 3 slice. The
broader target-architecture Stage 6 in the brief additionally calls for
OpenCLIP similarity; that and chaptering remain Phase 3 work.

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
plus the first Phase 3 slice (transcript-window alignment via
`recap window`). Any remaining Phase 3/4 work — chaptering, OpenCLIP
semantic alignment, frame ranking, keep/reject rules, VLM
verification, DOCX/HTML/Notion export, WhisperX, queues, workers,
plugin systems — stays out until the next chunk is explicitly
approved.

If a proposed change requires scope not documented in `MASTER_BRIEF.md`,
stop and raise it for a product decision instead of inventing scope.

## Resuming safely in a future session

1. Re-read the binding docs listed above, in order. Treat them as
   authoritative.
2. Read `HANDOFF.md` to confirm what is actually on disk.
3. Verify the environment (`python3.12 -m venv .venv`, `pip install -r
   requirements.txt`, `ffmpeg`/`ffprobe` on PATH, `tesseract` on PATH
   when exercising `recap dedupe`; Python 3.14 is not supported).
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
PATH). Re-run each to confirm the skip path, or pass `--force` to
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
