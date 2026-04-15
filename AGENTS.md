# AGENTS.md

This file defines how an implementation agent should build Recap.

`MASTER_BRIEF.md` is the source of truth. If this file conflicts with the brief, follow the brief. If this file appears to allow extra scope, do not take it.

## Objective

Build Recap in strict phases.

Do not skip phases.
Do not partially implement later phases "while you are here."
Do not add speculative architecture, optional systems, or convenience features beyond the active phase.

## Development Rule

Implement only the current phase.

Current allowed phase at project start:

- Phase 1: Reliable Core

Phase 1 includes only:

- Stage 1: Ingest
- Stage 2: Normalize
- Stage 3: Transcribe
- Stage 8: Basic Markdown assembly

Stages 4 through 7 are part of the target architecture, but they are out of scope until Phase 1 is complete and explicitly approved to move forward.

## Build Order

Complete work in this order:

1. Job model and job working directory
2. Ingest input video and persist source artifact
3. Extract metadata with `ffprobe`
4. Normalize video to `analysis.mp4`
5. Extract `audio.wav` as 16kHz mono WAV
6. Run transcription with faster-whisper
7. Persist transcript artifacts
8. Generate basic `report.md`
9. Validate end-to-end restartability for Phase 1

Do not reorder this sequence unless a dependency forces it.

## Phase 1 Required Outputs

At minimum, a successful Phase 1 job must produce:

- `original.ext`
- `metadata.json`
- `job.json`
- `analysis.mp4`
- `audio.wav`
- `transcript.json`
- `transcript.srt`
- `report.md`

`job.json` must reflect job identity, stage status, and failure or completion state.

## Phase 1 Must Not Implement

Do not implement any of the following in Phase 1:

- Chapter proposal logic
- Scene detection
- Candidate frame extraction
- Screenshot selection
- pHash deduplication
- SSIM scoring
- OCR novelty scoring
- OpenCLIP semantic alignment
- VLM verification
- Caption generation with VLMs
- DOCX export
- PDF export
- HTML export beyond what is already explicitly required
- Notion export
- Full background capture integrations
- Queue systems, distributed workers, or remote orchestration unless absolutely required for the minimal local build
- Plugin systems, rule engines, or generalized pipeline frameworks

If a feature belongs to Phase 2, Phase 3, or Phase 4, do not implement it in any form.

## Constraints

- Keep the implementation simple and local-first.
- Prefer direct code over abstractions meant for hypothetical future phases.
- Keep modules small and explicit.
- Use clear stage boundaries and file outputs.
- Persist artifacts to disk after each completed stage.
- Make stages restartable from existing artifacts where practical.
- Use Markdown as the primary output format.
- Treat VLM usage as optional in the overall system and completely out of scope for Phase 1.
- Preserve the staged pipeline design even if only part of it is implemented now.

## Coding Style

- Write simple, modular code.
- Prefer straightforward functions over layered abstractions.
- Avoid inheritance-heavy designs.
- Avoid building a generic workflow engine.
- Avoid adding interfaces solely for future flexibility.
- Keep data structures explicit and easy to inspect.
- Use plain JSON artifacts where the brief expects JSON artifacts.
- Name code by stage and responsibility, not by vague platform language.

Good style for this project:

- A small module that runs `ffprobe` and writes `metadata.json`
- A direct transcription module that reads `audio.wav` and writes `transcript.json`
- A report builder that reads existing artifacts and writes `report.md`

Bad style for this project:

- A generalized media processing plugin framework
- A registry for arbitrary pipeline stages before the real stages are built
- Abstract scorer interfaces for OCR, CLIP, and VLM before those phases exist

## Required Artifact Discipline

After each implemented stage, write the expected artifact before moving on.

### After Stage 1: Ingest

Required:

- job directory exists
- source video stored as `original.ext`
- `job.json` created

Validation:

- confirm the source file exists
- confirm `job.json` contains a job ID and stage state

### After Stage 2: Normalize

Required:

- `metadata.json`
- `analysis.mp4`
- `audio.wav`
- updated `job.json`

Validation:

- confirm `ffprobe` metadata was captured
- confirm `analysis.mp4` is playable and uses the normalized target format
- confirm `audio.wav` exists and is 16kHz mono

### After Stage 3: Transcribe

Required:

- `transcript.json`
- `transcript.srt`
- updated `job.json`

Validation:

- confirm transcript artifacts exist
- confirm transcript segments contain timestamps
- confirm the transcription step can be rerun or skipped based on existing artifacts

### After Stage 8: Basic Markdown Assembly

Required:

- `report.md`
- updated `job.json`

Validation:

- confirm `report.md` is readable Markdown
- confirm it is built from actual artifacts, not placeholder text
- confirm it does not claim screenshots, chapters, or VLM verification that do not yet exist

## Progress Validation Rules

After every implementation step:

1. Run the smallest practical validation for that step.
2. Confirm the expected artifact was written.
3. Confirm the stage status is reflected in `job.json`.
4. Confirm no later-phase feature was introduced as a side effect.

Before marking Phase 1 complete:

1. Run a sample recording through the full Phase 1 flow.
2. Verify all Phase 1 artifacts exist.
3. Verify the pipeline can resume without recomputing every step.
4. Verify the output remains Markdown-first.

## Stop Conditions

Stop immediately when any of the following becomes true:

- Phase 1 deliverables are complete and validated
- The next task belongs to Phase 2 or later
- The requested change would require inventing scope not present in `MASTER_BRIEF.md`
- The implementation would require adding speculative abstractions for future phases
- The implementation cannot proceed without a product decision not already documented

When stopping, report:

- what was completed
- what artifacts were produced
- what remains for the next approved phase
- why work should not continue automatically

Do not continue into Phase 2 on your own.

## Anti-Patterns

Do not do any of the following:

- Do not capture screenshots at fixed time intervals.
- Do not feed entire raw videos to a VLM.
- Do not build a vision-only system that ignores transcript context.
- Do not build a transcript-only system that ignores later visual stages in the design.
- Do not smuggle Phase 2 work into Phase 1 under names like "foundation," "prep," or "future-proofing."
- Do not add export formats beyond the active phase.
- Do not create abstractions for OCR, CLIP, scene detection, or VLMs before those phases are active.
- Do not replace explicit artifacts with in-memory-only processing.
- Do not skip writing intermediate outputs because "they can be recomputed."

## Good Task Example

Good implementation task:

"Implement Phase 1 Stage 2 normalization: read `original.ext`, run `ffprobe`, write `metadata.json`, transcode to `analysis.mp4`, extract `audio.wav` as 16kHz mono, update `job.json`, and validate the produced media artifacts."

Why this is good:

- It targets one allowed phase
- It maps directly to required artifacts
- It has a clear completion condition
- It does not pull in later-stage systems

## Bad Task Example

Bad over-scoped task:

"Build the end-to-end pipeline framework, including chapter detection interfaces, screenshot scoring hooks, optional CLIP and VLM providers, and a report exporter that can later support DOCX and Notion."

Why this is bad:

- It mixes multiple future phases
- It introduces premature abstraction
- It creates systems not needed for Phase 1
- It increases complexity without producing the required minimal artifacts

## Enforcement Summary

If you are implementing Recap:

- Build only Phase 1 first
- Produce artifacts after each stage
- Validate each step before moving on
- Keep the code direct and minimal
- Stop when Phase 1 is done

No overbuilding. No skipping ahead. No silent expansion of scope.
