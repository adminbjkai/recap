***

# MASTER_BRIEF.md: Automated Intelligent Video-to-Documentation Pipeline

> **Status (historical north star).** This brief is the original
> long-form specification for Recap's pipeline philosophy. It is
> preserved as the **pipeline north star** for how stages should
> behave — cheap deterministic filters first, semantic alignment on
> a reduced set, expensive AI (VLM / LLM) only on a small shortlist,
> Markdown-first outputs. It is **not** a description of what Recap
> currently ships.
>
> For the current architecture (React SPA, JSON API, browser
> recording, opt-in cloud providers) see
> [ARCHITECTURE.md](ARCHITECTURE.md). For the ordered list of
> product slices in flight, see
> [docs/product_roadmap.md](docs/product_roadmap.md). For accepted
> decisions and rejected alternatives, see
> [DECISIONS.md](DECISIONS.md). When those documents conflict with
> this one, they win.

This document serves as the definitive, action-oriented specification for building an efficient, open-source-first pipeline that converts screen recordings into structured, chaptered documentation with intelligently selected screenshots.

## 1. Core Philosophy and Strategy

The fundamental principle of this system is to avoid processing entire videos with expensive AI models. Instead, the system must utilize a staged, cascading pipeline. The pipeline runs cheap deterministic filters first, applies semantic alignment on the reduced set, and reserves expensive AI (Vision-Language Models) exclusively for evaluating a small shortlist of finalist frames.

## 2. Technology Stack Definition

* **Ingestion and Capture:** OBS Studio for standard recording, Screenpipe for background event-driven capture, or Cap for polished UX.
* **Media Normalization:** FFmpeg for transcoding, audio extraction, and metadata retrieval.
* **Transcription Engine:** faster-whisper for fast default processing, and WhisperX when word-level timestamp precision is critical.
* **Scene Detection:** PySceneDetect to identify visual boundaries and cut the candidate frame count from thousands to dozens.
* **Deduplication:** ImageHash (Perceptual Hashing / pHash) for fast duplicate removal, with scikit-image (SSIM) for borderline identical frames.
* **Text Extraction:** Tesseract OCR to detect text changes and UI novelty.
* **Semantic Alignment:** OpenCLIP to compute cosine similarity between the candidate frame and the transcript text chunk.
* **VLM Verification (Optional):** Qwen2.5-VL (local) or Gemini 1.5 Flash (cloud) for final quality checks and caption generation on shortlisted frames.
* **Document Assembly:** Markdown as the primary intermediate format, utilizing python-docx or Pandoc for final DOCX, PDF, or HTML generation.

## 3. The 8-Stage Execution Pipeline

### Stage 1: Ingest
* Accept the uploaded video or completed recording.
* Store the original file and run `ffprobe` to extract metadata.
* Create a unique job ID and working directory.

### Stage 2: Normalize
* Transcode the incoming video to a standard analysis-friendly format, specifically an MP4 container with an H.264 video codec.
* Extract the audio stream as a 16kHz Mono WAV file, which is the ideal format for speech-to-text models.

### Stage 3: Transcribe
* Process the audio using faster-whisper or WhisperX.
* Extract segment timestamps and critical word-level timestamps to anchor visual elements to exact spoken moments.

### Stage 4: Propose Chapters
* Identify potential chapter breaks based on a fusion of signals, rather than simple time slicing.
* Utilize transcript topic shifts, speech pauses, speaker changes, and scene boundaries to define semantic chapters.

### Stage 5: Candidate Frame Extraction
* Run PySceneDetect to identify major visual shifts and discard the vast majority of static frames.
* Extract one representative frame per detected scene.

### Stage 6: Deduplicate and Score
* Run Perceptual Hashing (pHash) and SSIM across candidate frames to eliminate "static desktop" redundancy.
* Process surviving frames through OCR to score novelty based on text changes from the previous frame.
* Establish a fuzzy time window of ±5 to ±7 seconds around the frame's timestamp and extract the corresponding transcript.
* Use OpenCLIP to compute embedding similarity scores between the visual frame and the spoken transcript chunk.

### Stage 7: VLM Verification (Finalists Only)
* Send only the top 1 to 3 candidate frames per chapter to a Vision-Language Model alongside the exact transcript context.
* Prompt the model to verify relevance, resolve borderline ties, or generate a high-quality caption.

### Stage 8: Assemble Document
* Construct a foundational Markdown document mirroring the determined chapter structure.
* Embed the finalized summary, transcript segments, and verified "hero" screenshots at their appropriate timestamps.
* Compile the final deliverable into formats like DOCX, PDF, or Notion via Pandoc or python-docx.

## 4. Intelligent Screenshot Selection Policy

* **The Baseline Budget:** Aim for 1 primary "hero" screenshot per chapter, allowing up to 3 supporting screenshots only if they provide genuinely new visual data.
* **Keep Rules:** Retain a frame if the transcript explicitly references on-screen content, if the OCR text changed meaningfully, if OpenCLIP similarity is above a threshold (e.g., > 0.30), or if the frame clearly shows code, diagrams, settings, or dashboards.
* **Reject Rules:** Discard a frame if it is very similar to the last kept frame, lacks OCR novelty, has low transcript relevance, or is blurry/low-information.

## 5. Recommended Build Phases

> Historical build phasing. Phases 1–4 below were the original
> delivery plan. Phase 1 is now the frozen `recap run` core; every
> later phase's stages have shipped as opt-in CLI verbs (see
> [ARCHITECTURE.md](ARCHITECTURE.md) §3 for the current list).

* **Phase 1 (Reliable Core):** Build ingest, FFmpeg normalization, transcription, and basic Markdown text output without visual processing.
* **Phase 2 (Smart Visuals v1):** Integrate PySceneDetect, candidate extraction, hash deduplication, and OCR novelty checks.
* **Phase 3 (Semantic Alignment):** Implement the OpenCLIP transcript-to-frame matching and finalize the intelligent chapter proposal logic.
* **Phase 4 (Precision Polish):** Add the optional VLM verification for borderline finalists, refine captions, and implement DOCX/Notion export functionality.

## 6. Project Artifact Directory Layout

Maintain an explicit intermediate artifact structure per job to ensure the pipeline remains inspectable and restartable:
* `original.ext`
* `metadata.json`
* `job.json`
* `analysis.mp4`
* `audio.wav`
* `transcript.json` / `transcript.srt`
* `chapter_candidates.json`
* `scenes.json`
* `candidate_frames/` (Directory)
* `frame_scores.json`
* `selected_frames.json`
* `report.md` / `report.docx` / `report.html`

## 7. Strict Anti-Patterns

* Do not capture screenshots at fixed time intervals (e.g., every 5 seconds), as this misses context and generates redundant junk.
* Do not feed the entire raw video file directly to an expensive multimodal VLM.
* Do not build a purely computer-vision-based system that ignores the contextual evidence of the spoken transcript.
* Do not rely solely on the transcript while ignoring critical visual shifts like UI changes or slide transitions.
