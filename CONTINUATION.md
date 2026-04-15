# Recap — Continuation Guide

This file exists so a future session can resume from the current repo
state without re-deriving context. It is not a roadmap. For what the
system does and produces, read `HANDOFF.md`.

## Current state

- Phase 1 of Recap is implemented, audited, hardened, and closed out.
- The repository contains only Phase 1 code. No Phase 2+ scaffolding,
  stubs, abstractions, or configuration exist.
- `HANDOFF.md` is the definitive closeout document. It reflects the code
  on disk today.

## What Phase 1 includes

- Stage 1 — Ingest (`original.<ext>`, `job.json`)
- Stage 2 — Normalize (`metadata.json`, `analysis.mp4`, `audio.wav`)
- Stage 3 — Transcribe (`transcript.json`, `transcript.srt`, faster-whisper
  only, with the narrow function-level swap seam documented in
  `recap/stages/transcribe.py`)
- Stage 8 — Basic Markdown assembly (`report.md`)

Stages 4 through 7 are deliberately absent.

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
phase is Phase 1 and Phase 1 is complete. Any work that belongs to Phase
2, 3, or 4 — chaptering, scene detection, frame extraction,
pHash/SSIM/OCR, OpenCLIP, VLM verification, DOCX/HTML/Notion export,
WhisperX, queues, workers, plugin systems — stays out until Phase 2 (or
later) is explicitly approved.

If a proposed change requires scope not documented in `MASTER_BRIEF.md`,
stop and raise it for a product decision instead of inventing scope.

## Resuming safely in a future session

1. Re-read the binding docs listed above, in order. Treat them as
   authoritative.
2. Read `HANDOFF.md` to confirm what is actually on disk.
3. Verify the environment (`python3.12 -m venv .venv`, `pip install -r
   requirements.txt`, `ffmpeg`/`ffprobe` on PATH; Python 3.14 is not
   supported).
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

A new job directory is created under `jobs/<job_id>/` with the eight
artifacts listed in `HANDOFF.md`. Re-running the same command with
`--job jobs/<job_id>` exercises restartability — completed stages should
short-circuit.

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
