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
  - [x] Pause + speaker-change + scene-boundary fusion shipped (opt-in via `recap chapters`; reads `transcript.json` and, when present, `scenes.json`; writes `chapter_candidates.json` with `source_signal` in {"pauses","pauses+speakers","pauses+scenes","pauses+speakers+scenes"}, emits pre-merge `speaker_change_count` in speaker-aware mode and `scenes_source` plus pre-merge `scene_change_count` in scenes-aware mode). Topic-shift detection, speaker recognition/labeling, and chapter titling remain deferred.
- [x] Persist chapter proposals to `chapter_candidates.json` (pause-only when neither speakers nor a usable `scenes.json` are available; fuses speaker-change boundaries when Deepgram utterances are present and scene-cut boundaries when `scenes.json` is present and not a fallback; topic-shift detection, speaker recognition/labeling, and chapter titling remain deferred)
- [x] Add transcript windowing around frame timestamps using a fuzzy plus or minus 5 to 7 second range (opt-in via `recap window`; writes `frame_windows.json`)
- [x] Integrate OpenCLIP scoring between candidate frames and transcript chunks (opt-in via `recap similarity`)
- [x] Rank frames per chapter using deduplication, OCR novelty, and semantic similarity together (opt-in via `recap rank`; writes `frame_ranks.json`)
- [x] Apply deterministic screenshot keep/reject rules before shortlist finalization (opt-in via `recap shortlist`; writes `frame_shortlist.json`; `selected_frames.json` remains reserved for Phase 4 post-VLM finalists; blur/VLM-dependent visual-quality rules remain deferred).
- [x] Add optional Deepgram cloud transcription engine with diarized utterances (opt-in via `--engine deepgram` on `recap run` and `recap transcribe`; `DEEPGRAM_API_KEY` env required only on recompute; adds `utterances`, `speakers`, `words`, `provider_metadata` as additive optional fields on `transcript.json`; `faster-whisper` remains the default; Groq, WhisperX, pyannote, and speaker recognition/manual labels remain deferred).

## Phase 4: Precision Polish

- [x] Add optional VLM verification for only the top 1 to 3 frames per chapter (opt-in via `recap verify`; reads `frame_shortlist.json` and only verifies frames with `decision in {"hero","supporting"}`; mock + Gemini providers via stdlib only; `recap run` remains Phase-1-only)
- [x] Pass exact transcript context into finalist verification (per-frame `window_text` from `frame_windows.json` and per-chapter `text` from `chapter_candidates.json`, truncated to `WINDOW_CONTEXT_CHARS = 1500` / `CHAPTER_CONTEXT_CHARS = 1500`)
- [x] Support tie-breaking and caption generation during VLM verification (hero promotion of the highest-ranked surviving supporting when the original hero is VLM-rejected, tagged `vlm_tie_broken_by_rank`; captions returned by Gemini are stored on `verification.caption` truncated to `VLM_MAX_CAPTION_CHARS = 240`; mock provider never captions and keeps `caption_mode = "off"`)
- [x] Persist final frame selections to `selected_frames.json`
- [x] Improve Markdown assembly to embed finalized screenshots and captions (opt-in via presence of `selected_frames.json`; `recap assemble` reads `selected_frames.json` and `chapter_candidates.json` and inserts a `## Chapters` section between `## Media` and `## Transcript` with hero/supporting images and VLM-provided captions, atomic write via `report.md.tmp`; absent `selected_frames.json` → report is byte-identical to the Phase-1 basic output; no VLM calls; no chapter titling; no new CLI flag; `recap run` remains Phase-1-only)
- [ ] Add optional export to DOCX and HTML

## Guardrails

- [ ] Do not add fixed-interval screenshot capture anywhere in the pipeline
- [ ] Do not send full raw videos to a VLM
- [ ] Do not make VLM usage mandatory for successful processing
- [ ] Do not expand Phase 1 beyond the reliable core
