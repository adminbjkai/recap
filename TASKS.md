# Tasks

## Phase 1: Reliable Core

- [ ] Create a job model and working-directory convention with `job.json`
- [ ] Implement ingest to accept a source recording and persist `original.ext`
- [ ] Add metadata extraction via `ffprobe` and persist `metadata.json`
- [ ] Add FFmpeg normalization to produce `analysis.mp4`
- [ ] Add FFmpeg audio extraction to produce `audio.wav` as 16kHz mono WAV
- [ ] Integrate faster-whisper as the default transcription engine
- [ ] Support WhisperX as an optional precision path when word-level timing is needed
- [ ] Persist transcript outputs to `transcript.json` and `transcript.srt`
- [ ] Implement basic Markdown report generation as `report.md`
- [ ] Make every Phase 1 step restartable from existing artifacts
- [ ] Add basic job status updates to reflect stage progress and failures
- [ ] Validate the Phase 1 flow on a sample recording end to end

## Phase 2: Smart Visuals v1

- [x] Integrate PySceneDetect and write `scenes.json` (opt-in via `recap scenes`)
- [x] Extract one representative frame per scene into `candidate_frames/` (with single-scene fallback when no cuts)
- [x] Add pHash-based duplicate marking (`frame_scores.json`, opt-in via `recap dedupe`)
- [ ] Add SSIM checks for borderline duplicate frames
- [ ] Integrate Tesseract OCR for text extraction and novelty scoring

## Phase 3: Semantic Alignment

- [ ] Implement chapter proposal logic using transcript shifts, pauses, speaker changes, and scene boundaries
- [ ] Persist chapter proposals to `chapter_candidates.json`
- [ ] Add transcript windowing around frame timestamps using a fuzzy plus or minus 5 to 7 second range
- [ ] Integrate OpenCLIP scoring between candidate frames and transcript chunks
- [ ] Rank frames per chapter using deduplication, OCR novelty, and semantic similarity together
- [ ] Apply screenshot keep and reject rules before shortlist finalization

## Phase 4: Precision Polish

- [ ] Add optional VLM verification for only the top 1 to 3 frames per chapter
- [ ] Pass exact transcript context into finalist verification
- [ ] Support tie-breaking and caption generation during VLM verification
- [ ] Persist final frame selections to `selected_frames.json`
- [ ] Improve Markdown assembly to embed finalized screenshots and captions
- [ ] Add optional export to DOCX and HTML

## Guardrails

- [ ] Do not add fixed-interval screenshot capture anywhere in the pipeline
- [ ] Do not send full raw videos to a VLM
- [ ] Do not make VLM usage mandatory for successful processing
- [ ] Do not expand Phase 1 beyond the reliable core
