# Decisions

## 1. Use a staged cascade instead of end-to-end multimodal processing

Decision:
Build the system as an 8-stage pipeline that progressively reduces data before applying more expensive analysis.

Rationale:
This is the core strategy in `MASTER_BRIEF.md`. It keeps cost and latency controlled, makes intermediate outputs inspectable, and avoids sending entire videos to expensive models.

## 2. Keep Markdown as the primary document format

Decision:
Use Markdown as the main assembly target, with DOCX, PDF, or HTML as downstream conversions.

Rationale:
Markdown is practical for inspection, versioning, and pipeline handoff. It also keeps Phase 1 minimal while still allowing later export through Pandoc or python-docx.

## 3. Make Phase 1 intentionally narrow

Decision:
Ship ingest, normalization, transcription, and basic Markdown output first.

Rationale:
The brief explicitly defines Phase 1 as the reliable core. This keeps the first build achievable without blocking on scene detection, OCR, semantic alignment, or VLM integration.

## 4. Treat visual selection as a later pipeline concern

Decision:
Do not include screenshot extraction or selection in Phase 1, but preserve the architecture for Stages 4 through 7.

Rationale:
The system needs the full staged design, but the initial deliverable must remain buildable. Deferring visual stages preserves scope discipline without discarding the target architecture.

## 5. Use transcript and visual evidence together

Decision:
Score screenshots with both transcript context and visual novelty instead of relying on only one signal source.

Rationale:
The brief rejects both transcript-only and vision-only approaches. The intended design combines chaptering, OCR novelty, scene boundaries, and OpenCLIP alignment.

## 6. Restrict VLM usage to finalists only

Decision:
VLM verification is optional and should run only on the top 1 to 3 candidate frames per chapter.

Rationale:
This preserves the open-source-first, cost-controlled approach and follows the explicit shortlist-only rule in the brief.

## 7. Store explicit per-job artifacts

Decision:
Persist intermediate files such as normalized media, transcript outputs, scene data, scoring data, and final reports in a clear job directory.

Rationale:
The brief requires an inspectable and restartable artifact structure. Persisted outputs make debugging, retries, and incremental development practical.

## 8. Reject fixed-interval screenshot capture

Decision:
Do not sample screenshots at regular time intervals.

Rationale:
The brief marks this as an anti-pattern because it produces redundant low-context results and misses semantically important moments.
