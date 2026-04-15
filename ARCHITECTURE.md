# Architecture

## System Shape

The system is a job-based pipeline that writes explicit artifacts after each stage. Every stage should be restartable from disk outputs rather than requiring a full rerun.

The architecture follows a strict cost ladder:

1. Deterministic media processing and filtering
2. Reduced-set semantic scoring
3. Optional VLM verification on finalists only

## End-to-End Flow

### Stage 1: Ingest

- Accept an uploaded video or completed recording.
- Create a unique job ID and working directory.
- Store the original file as `original.ext`.
- Run `ffprobe` and persist `metadata.json`.
- Persist job-level configuration and status in `job.json`.

### Stage 2: Normalize

- Transcode the source into `analysis.mp4`.
- Standardize on MP4 container with H.264 video.
- Extract `audio.wav` as 16kHz mono WAV for speech-to-text.

### Stage 3: Transcribe

- Run faster-whisper by default.
- Use WhisperX only when word-level precision is needed.
- Write transcript outputs such as `transcript.json` and `transcript.srt`.
- Preserve segment timestamps and, when available, word-level timing anchors.

### Stage 4: Propose Chapters

- Build `chapter_candidates.json`.
- Derive chapter boundaries from transcript topic shifts, speech pauses, speaker changes, and scene boundaries.
- Avoid naive fixed time slicing.

### Stage 5: Candidate Frame Extraction

- Run PySceneDetect against normalized video.
- Write scene boundaries to `scenes.json`.
- Extract one representative frame per scene into `candidate_frames/`.

### Stage 6: Deduplicate and Score

- Use pHash to remove clear duplicates.
- Use SSIM to resolve borderline near-duplicates.
- Run OCR to measure text novelty against nearby frames.
- Align each frame to a fuzzy transcript window of about plus or minus 5 to 7 seconds.
- Use OpenCLIP to score frame and transcript similarity.
- Write frame-level scoring results to `frame_scores.json`.

### Stage 7: VLM Verification

- Take only the top 1 to 3 candidates per chapter.
- Provide the exact transcript context with each shortlisted frame.
- Use a VLM only to verify relevance, break ties, or generate a caption.
- Write final selections to `selected_frames.json`.

### Stage 8: Assemble Document

- Build `report.md` as the primary output.
- Structure the document around finalized chapters.
- Embed summaries, transcript-backed content, timestamps, and selected screenshots.
- Optionally compile to `report.docx` or `report.html`.

## Artifact Layout

Each job directory should contain:

- `original.ext`
- `metadata.json`
- `job.json`
- `analysis.mp4`
- `audio.wav`
- `transcript.json`
- `transcript.srt`
- `chapter_candidates.json`
- `scenes.json`
- `candidate_frames/`
- `frame_scores.json`
- `selected_frames.json`
- `report.md`
- optional `report.docx`
- optional `report.html`

## Screenshot Selection Policy

- Default budget: 1 hero screenshot per chapter
- Expanded budget: up to 3 supporting screenshots only when they add new visual information
- Keep when transcript references on-screen content, OCR text changes meaningfully, OpenCLIP similarity is strong, or the frame clearly shows code, diagrams, settings, or dashboards
- Reject when the frame is too similar to the last kept frame, has low OCR novelty, has weak transcript relevance, or is blurry or low-information

## Phase 1 Implementation Boundary

Phase 1 includes only:

- Stage 1 ingest
- Stage 2 normalize
- Stage 3 transcribe
- Stage 8 basic Markdown assembly

Stages 4 through 7 remain part of the target architecture but should not block the initial build.
