# Tasks

## Phase 1: Reliable Core

- [x] Create a job model and working-directory convention with `job.json`
- [x] Implement ingest to accept a source recording and persist `original.ext`
- [x] Add metadata extraction via `ffprobe` and persist `metadata.json`
- [x] Add FFmpeg normalization to produce `analysis.mp4`
- [x] Add FFmpeg audio extraction to produce `audio.wav` as 16kHz mono WAV
- [x] Integrate faster-whisper as the default transcription engine
- [ ] Support WhisperX as an optional precision path when word-level timing is needed
- [x] Persist transcript outputs to `transcript.json` and `transcript.srt`
- [x] Implement basic Markdown report generation as `report.md`
- [x] Make every Phase 1 step restartable from existing artifacts
- [x] Add basic job status updates to reflect stage progress and failures
- [x] Validate the Phase 1 flow on a sample recording end to end

## Phase 2: Smart Visuals v1

- [x] Integrate PySceneDetect and write `scenes.json` (opt-in via `recap scenes`)
- [x] Extract one representative frame per scene into `candidate_frames/` (with single-scene fallback when no cuts)
- [x] Add pHash-based duplicate marking (`frame_scores.json`, opt-in via `recap dedupe`)
- [x] Add SSIM checks for borderline duplicate frames (folded into `recap dedupe`; extends `frame_scores.json`)
- [x] Integrate Tesseract OCR for text extraction and novelty scoring (folded into `recap dedupe`; extends `frame_scores.json` with per-frame `ocr_text` and `text_novelty`)

## Phase 3: Semantic Alignment

- [ ] Implement full chapter proposal logic using transcript shifts, pauses, speaker changes, and scene boundaries
  - [x] First slice shipped: transcript-pause-only chapter proposal (opt-in via `recap chapters`; writes `chapter_candidates.json`). Scene-boundary fusion, topic-shift detection, and speaker-change detection remain deferred.
- [x] Persist pause-only chapter proposals to `chapter_candidates.json` (full-fusion chaptering remains deferred)
- [x] Add transcript windowing around frame timestamps using a fuzzy plus or minus 5 to 7 second range (opt-in via `recap window`; writes `frame_windows.json`)
- [x] Integrate OpenCLIP scoring between candidate frames and transcript chunks (opt-in via `recap similarity`)
- [x] Rank frames per chapter using deduplication, OCR novelty, and semantic similarity together (opt-in via `recap rank`; writes `frame_ranks.json`)
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
