# Product Requirements Document

## Product Goal

Build a practical pipeline that converts screen recordings into structured documentation without sending the entire video through expensive multimodal models.

The product must preserve context by combining transcript evidence with visual signals, while keeping the first build minimal and reliable.

## Primary User Flow

1. A user provides an uploaded video or completed recording.
2. The system creates a job workspace and extracts metadata.
3. The video is normalized into analysis-ready audio and video files.
4. The audio is transcribed into timestamped transcript artifacts.
5. The system proposes chapter boundaries from transcript and scene signals.
6. The system extracts and scores candidate screenshots per chapter.
7. The system optionally runs VLM verification only on shortlisted frames.
8. The system writes a Markdown report with chapter structure, transcript-backed content, and selected screenshots.

## MVP Scope

### Phase 1 MVP

The MVP is the reliable core only:

- accept a recording as input
- create a unique job directory
- store the original file and metadata
- normalize media with FFmpeg
- transcribe audio with faster-whisper
- persist transcript artifacts with timestamps
- generate a basic Markdown report from transcript and chapter placeholders or simple chapter structure

### Full Planned Scope

The planned system includes the full 8-stage pipeline:

- ingest
- normalize
- transcribe
- propose chapters
- candidate frame extraction
- deduplicate and score
- optional VLM verification for finalists only
- assemble Markdown and optional export formats

## Non-Goals

- Fixed-interval screenshot capture
- Whole-video VLM processing
- A vision-only pipeline that ignores transcript context
- A transcript-only pipeline that ignores scene and UI changes
- Broad export surface in Phase 1 beyond Markdown-first output

## Functional Requirements

- The system must maintain a per-job artifact layout that is inspectable and restartable.
- The system must use a staged pipeline where higher-cost analysis happens only after aggressive reduction.
- Chaptering must be based on fused signals rather than fixed time slices.
- Screenshot selection must target 1 hero image per chapter by default, with up to 3 supporting images only when they add new information.
- VLM usage must remain optional and restricted to the top 1 to 3 frames per chapter.
- Markdown must remain the primary assembly format.

## Success Criteria

- A recording can be processed end to end into a job directory with normalized media and transcript artifacts.
- The system can produce a readable `report.md` from the pipeline outputs.
- The pipeline structure supports restartability from intermediate artifacts.
- Candidate screenshot selection is reduced from raw video frames to a small chapter-level shortlist before any optional VLM call.
- Phase 1 is buildable without scene detection, OCR, OpenCLIP, or VLM dependencies.
