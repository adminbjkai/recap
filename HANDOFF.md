# Recap — Phase 1 Handoff (+ Phase 2 checklist complete, + first five Phase 3 slices, + first Phase 4 slice)

> **Product direction:** see [docs/product_roadmap.md](docs/product_roadmap.md)
> for the ordered list of slices and
> [docs/ux_inspiration.md](docs/ux_inspiration.md) for which patterns
> are borrowed from Cap5, CapSoftware/Cap, and steipete/summarize. The
> rule is "borrow patterns, not code."

This document closes out Phase 1 of Recap and records the Phase 2
slices approved and implemented so far: Stage 5 candidate frame
extraction, and the combined pHash + SSIM duplicate marking with
Tesseract OCR novelty scoring. All checklist items in
`TASKS.md` Phase 2 are ticked. Five Phase 3 slices are also
implemented: transcript-window alignment per candidate frame
(`recap window` → `frame_windows.json`), OpenCLIP frame/text cosine
similarity (`recap similarity` → `frame_similarities.json`), a
chaptering slice that fuses transcript pauses with speaker-change
boundaries when Deepgram utterances are present and scene-cut
boundaries when a non-fallback `scenes.json` with at least one scene
cut mapping to a segment boundary is present, falling back to
pause-only otherwise (`recap chapters` → `chapter_candidates.json`),
per-chapter deterministic ranking fusion
(`recap rank` → `frame_ranks.json`), and a deterministic pre-VLM
keep/reject shortlist
(`recap shortlist` → `frame_shortlist.json`). The chaptering slice
is explicitly **not** full Stage 4 chaptering — topic-shift
detection, speaker recognition / manual labels, and LLM chapter
titling remain deferred. The
ranking slice is marking-only: it does not apply keep/reject
thresholds, enforce a screenshot budget, write
`selected_frames.json`, or modify `report.md`. The shortlist slice
is marking-only and pre-VLM: it does not write
`selected_frames.json`. One Phase 4 slice is also implemented:
optional VLM verification over the shortlist
(`recap verify` → `selected_frames.json`) with a deterministic
`mock` provider (default) and an opt-in `gemini` provider, wired
up through a narrow function-level swap seam in
`recap/stages/verify.py`. `recap run` continues to stay
Phase-1-only. The remainder of Phase 3 (topic-shift detection,
speaker recognition / manual labels, chapter titling) and the
remaining Phase 4 items (report screenshot embedding, caption
rendering, DOCX / HTML / Notion / PDF export) remain out of
scope. This file reflects the current code in this repository —
not a plan, not a roadmap. Anything not listed here is explicitly
deferred.

Binding references: `MASTER_BRIEF.md`, `ARCHITECTURE.md`, `TASKS.md`,
`DECISIONS.md`, `AGENTS.md`, `README.md`, `PRD.md`.

## What Phase 1 includes

Phase 1 implements only the "reliable core" stages from the brief:

- **Stage 1 — Ingest.** Accept a source video, create a per-job working
  directory, copy the source in as `original.<ext>`, initialize `job.json`.
- **Stage 2 — Normalize.** Run `ffprobe` → `metadata.json`, transcode with
  `ffmpeg` → `analysis.mp4` (H.264 / AAC / `yuv420p` / `+faststart`), and
  extract `audio.wav` as 16 kHz mono PCM `s16le`.
- **Stage 3 — Transcribe.** Run `faster-whisper` on `audio.wav` and write
  `transcript.json` and `transcript.srt`.
- **Stage 8 — Markdown assembly.** Read real artifacts and write
  `report.md` with media summary and timestamped transcript segments.
  When `selected_frames.json` is present on disk (produced by
  `recap verify`), additionally embed finalized hero/supporting
  screenshots and any VLM-provided captions under a `## Chapters`
  section between `## Media` and `## Transcript`; when absent, output is
  byte-identical to the Phase-1 basic report. `recap run` itself
  remains Phase-1-only.

Stage 5 is implemented as the first approved Phase 2 slice (see the
next section). Every item in the `TASKS.md` Phase 2 checklist is
complete: Stage 5 candidate frame extraction lives under
`recap scenes`, and pHash duplicate marking, SSIM borderline checks,
and Tesseract OCR novelty scoring live under `recap dedupe`.
Transcript-window alignment and OpenCLIP frame/text similarity —
the first two Phase 3 slices of Stage 6 from the brief — are also
implemented (see the Phase 3 sections below). Full Stage 4
chaptering and Stage 7 VLM verification remain deferred. A
chaptering slice is implemented that fuses transcript pauses with
speaker-change boundaries when Deepgram utterances are present and
with scene-cut boundaries when a usable `scenes.json` is present,
and falls back to pause-only otherwise; no VLM code exists in the
repository.

## What the Phase 2 slices include

- **Stage 5 — Candidate frame extraction.** Run PySceneDetect's
  `ContentDetector` against `analysis.mp4`, write `scenes.json` (scene
  list with start/end timestamps and frame numbers, per-scene
  `frame_file`, plus a `fallback` flag), and extract one representative
  frame per scene into `candidate_frames/`. If the detector finds no
  cuts, a single full-video fallback scene is written so there is always
  one candidate frame.
- **pHash + SSIM duplicate marking with OCR novelty.** Read
  `scenes.json` and the JPEGs in `candidate_frames/`, compute an
  ImageHash `phash` per frame (hash size 8 → 64-bit hash), and compare
  each frame to its immediate predecessor with Hamming distance. Frames
  at or below a fixed code-level threshold are marked as duplicates of
  their predecessor. For adjacent pairs whose pHash Hamming distance
  is strictly above `DUPLICATE_THRESHOLD` and at or below
  `SSIM_DISTANCE_BAND_MAX`, SSIM is computed on the grayscale frames
  with `skimage.metrics.structural_similarity`; pairs whose SSIM
  reaches `SSIM_DUPLICATE_THRESHOLD` are promoted to duplicates of
  their predecessor. Every frame is also passed through Tesseract via
  `pytesseract.image_to_string`; the output is whitespace-normalized
  (internal whitespace collapsed, leading/trailing trimmed) and stored
  per frame as `ocr_text`. A `text_novelty` score is computed against
  the immediate predecessor's `ocr_text` as
  `1.0 - difflib.SequenceMatcher(None, prev, curr).ratio()`; it is an
  additional signal only and does not influence `duplicate_of`.
  Results are written to `frame_scores.json` with per-frame entries
  (`scene_index`, `frame_file`, `phash`, `duplicate_of`,
  `hamming_distance`, `ssim`, `ocr_text`, `text_novelty`) and
  top-level metadata (`video`, `metric=phash+ssim+ocr`, `hash_size`,
  `duplicate_threshold`, `ssim_distance_band_max`,
  `ssim_duplicate_threshold`, `ocr_engine=tesseract`, `frame_count`,
  `duplicate_count`, `ssim_computed_count`,
  `ocr_frames_with_text_count`). `ssim` is `null` for the first frame,
  for pairs outside the band, and for pairs already marked duplicate
  by pHash. `ocr_text` is always a string (possibly `""`);
  `text_novelty` is `null` for the first frame. No frames are deleted,
  renamed, or moved.

Both Phase 2 entry points are opt-in. `recap run` continues to execute
the Phase 1 stages only. Stage 5 runs via `recap scenes --job <path>`;
pHash + SSIM duplicate marking with OCR novelty runs via
`recap dedupe --job <path>`. All Phase 2 checklist items are
implemented.

## What the first Phase 3 slice includes

- **Transcript-window alignment.** Read `transcript.json` and
  `scenes.json` and write `frame_windows.json`. For each candidate
  frame, compute `window_start = max(0.0, midpoint_seconds - 6.0)` and
  `window_end = midpoint_seconds + 6.0` (clamped to `transcript.duration`
  when present), collect the transcript segments that overlap the
  window with strict inequalities (`segment.start < window_end` and
  `segment.end > window_start`), record their ids in transcript order,
  and concatenate their text with a single space after whitespace
  normalization. `WINDOW_SECONDS = 6.0` is a fixed code-level constant
  at the midpoint of the brief's ±5 to ±7 second range. No new Python
  or system dependencies are introduced; no ML model is loaded. The
  stage is marking-only: it does not touch transcript, scenes,
  candidate frames, `frame_scores.json`, or `report.md`. Per-frame
  entries are `scene_index`, `frame_file`, `midpoint_seconds`,
  `window_start`, `window_end`, `segment_ids`, `window_text`; top-level
  keys are `video`, `transcript_source`, `scenes_source`,
  `window_seconds`, `frame_count`, `frames_with_text_count`, `frames`.

This Phase 3 slice is opt-in. `recap run` continues to execute the
Phase 1 stages only. Transcript-window alignment runs via
`recap window --job <path>`.

## What the second Phase 3 slice includes

- **OpenCLIP frame/text similarity.** Read `scenes.json`,
  `frame_windows.json`, and the JPEGs in `candidate_frames/` and write
  `frame_similarities.json`. For each candidate frame that has
  non-empty `window_text`, compute the cosine similarity between the
  OpenCLIP image embedding of the frame and the OpenCLIP text
  embedding of the window text, each L2-normalized, under
  `torch.no_grad()` with `model.eval()`. Frames with empty
  `window_text` record `clip_similarity: null`. The model (`MODEL =
  "ViT-B-32"`, `PRETRAINED = "openai"`), device (`DEVICE = "cpu"`),
  and image preprocessing (`IMAGE_PREPROCESS = "open_clip.default"`,
  the model's shipped transforms) are fixed code-level constants in
  `recap/stages/similarity.py`. `ViT-B-32/openai` was trained with
  QuickGELU activations, so the stage pins the activation with
  `force_quick_gelu=True` inside
  `open_clip.create_model_and_transforms`; this is a correctness fix
  for this specific (model, pretrained) pair, not a tunable knob.
  None of the constants are exposed as CLI flags, env vars, or
  config. The stage is marking-only: it does not threshold, rank,
  select, keep, reject, or mutate any frame, and it does not touch
  `transcript.json`, `scenes.json`, `frame_windows.json`,
  `frame_scores.json`, `candidate_frames/`, or `report.md`. Per-frame
  entries are `scene_index`, `frame_file`, `midpoint_seconds`,
  `window_start`, `window_end`, `window_text`, `has_window_text`,
  `clip_similarity`; top-level keys are `video`, `frames_dir`,
  `windows_source`, `scenes_source`, `model`, `pretrained`, `device`,
  `image_preprocess`, `frame_count`, `frames_with_window_text_count`,
  `frames_scored_count`, `frames`. `clip_similarity` is a plain
  Python float in `[-1.0, 1.0]` when `has_window_text` is true, else
  `null`. `frames_scored_count` equals the count of non-null
  `clip_similarity` values.

This Phase 3 slice is opt-in. `recap run` continues to execute the
Phase 1 stages only. OpenCLIP similarity runs via
`recap similarity --job <path>`.

## What the third Phase 3 slice includes

- **Chapter proposal from transcript pauses plus optional
  speaker-change and scene-boundary fusion.** Read `transcript.json`
  and, when present, `scenes.json`, and write
  `chapter_candidates.json`. A chapter boundary is placed between
  two adjacent transcript segments whenever any of the three fusion
  signals fires:

  - pause: `next.start - previous.end >= PAUSE_SECONDS`.
  - speaker: the transcript carries a non-empty `utterances` list
    with at least one non-null `speaker` id (Deepgram output;
    segments are 1:1 with utterances on the Deepgram path, sharing
    the same `id` values) and the adjacent segments' speaker ids
    differ.
  - scene: `scenes.json` is present, `fallback != true`, and the
    next segment's id is in the set of segment ids that scene cuts
    mapped to. For each scene with `start_seconds > 0`, the mapped
    segment is the smallest transcript segment index `i` in
    `[1, len(segments)-1]` whose `start >= scene.start_seconds`; if
    no such `i` exists, the scene cut is dropped. Multiple scene
    cuts mapping to the same segment id collapse to one boundary
    and count once.

  Any single signal is enough. The trigger label is built in the
  fixed order pause, speaker, scene; non-first triggers are drawn
  from `{"pause", "speaker", "scene", "pause+speaker",
  "pause+scene", "speaker+scene", "pause+speaker+scene"}`. The first
  chapter starts at `0.0` with `trigger="start"`. The last chapter
  ends at `transcript.duration` (falling back to the maximum segment
  end when `duration` is absent; if `duration` is present but less
  than the maximum segment end, the maximum end is used). Chapters
  whose span is shorter than `MIN_CHAPTER_SECONDS` are iteratively
  merged: chapter 1 merges into its successor, all other short
  chapters merge into their predecessor, until every chapter meets
  the minimum or only one chapter remains. The merge is
  content-agnostic — speaker-only or scene-only groups are
  legitimate merge candidates and can disappear from the emitted
  trigger distribution. Segment ids come from `segment.id` when
  present, otherwise the segment's 0-based array index. Per-chapter
  `text` is the whitespace-normalized concatenation of the contained
  segments' `text`. `PAUSE_SECONDS = 2.0` and
  `MIN_CHAPTER_SECONDS = 30.0` are fixed code-level constants in
  `recap/stages/chapters.py`. Source-signal tokens (`"pauses"`,
  `"pauses+speakers"`, `"pauses+scenes"`,
  `"pauses+speakers+scenes"`) are also fixed at the code level; a
  later change that tunes the speaker or scene rule must rename the
  token so the skip contract invalidates any older artifact. None
  are exposed as CLI flags, env vars, or config. No new Python or
  system dependencies are introduced; no ML model is loaded. The
  stage is marking-only: it reads `scenes.json` when present but
  never modifies it, and it does not touch `candidate_frames/`,
  `frame_scores.json`, `frame_windows.json`,
  `frame_similarities.json`, or `report.md`. Per-chapter entries
  are `index` (1-based), `start_seconds`, `end_seconds`,
  `first_segment_id`, `last_segment_id`, `segment_ids`, `text`,
  `trigger`; top-level keys are `video`, `transcript_source`,
  `source_signal` ∈ {`"pauses"`, `"pauses+speakers"`,
  `"pauses+scenes"`, `"pauses+speakers+scenes"`}, `pause_seconds`,
  `min_chapter_seconds`, `chapter_count`, `chapters`, and — in
  speaker-aware mode only — `speaker_change_count` (integer count
  of pre-merge speaker-change boundaries; deliberately pre-merge so
  the raw signal is observable even after short speaker-only groups
  are merged away), and — in scenes-aware mode only —
  `scenes_source` (basename of the scenes artifact, `scenes.json`)
  and `scene_change_count` (integer count of pre-merge scene-change
  boundaries; counts adjacent segment pairs on which the scene
  signal fired, not raw scene rows).

Pause-only fallback (faster-whisper transcript without usable
`utterances` and without a usable `scenes.json`) produces output
byte-identical to the pre-scene-fusion version of this stage:
`source_signal = "pauses"`, trigger vocabulary `{"start", "pause"}`,
no `speaker_change_count`, no `scenes_source`, no
`scene_change_count`. Missing `scenes.json` is a fallback, not an
error; `scenes.json` with `fallback == true`, or a non-fallback
`scenes.json` whose scene cuts do not map to any segment boundary,
likewise disables scenes-aware mode and the artifact carries no
scenes-aware keys. A malformed `scenes.json` exits 2 with a
single-line `error: scenes.json ...` and leaves no partial
`chapter_candidates.json{,.tmp}` on disk.

This slice fuses transcript pauses plus speaker changes plus scene
boundaries. Topic-shift detection, speaker recognition / manual
labels, chapter titling, Groq, WhisperX, pyannote, VLM, UI,
captions, report screenshot embedding, `selected_frames.json`, and
exports remain deferred.

This Phase 3 slice is opt-in. `recap run` continues to execute the
Phase 1 stages only. The chapter proposal runs via
`recap chapters --job <path>`.

## What the fourth Phase 3 slice includes

- **Per-chapter deterministic ranking fusion.** Read `scenes.json`,
  `chapter_candidates.json`, `frame_scores.json`,
  `frame_windows.json`, and `frame_similarities.json` and write
  `frame_ranks.json`. For each candidate frame, compute a composite
  score:

  `composite_score = W_CLIP * clip_similarity + W_OCR * text_novelty
  - (W_DUP if duplicate_of is not None else 0.0)`

  where `clip_similarity` defaults to `0.0` when null, and
  `text_novelty` defaults to `0.0` when null. Frames are assigned to
  chapters by `midpoint_seconds` (half-open intervals, last chapter
  closed on both ends) and ranked within each chapter by composite
  score descending with tie-breaking on `scene_index` ascending.
  `W_CLIP = 1.0`, `W_OCR = 0.5`, `W_DUP = 0.5`,
  `MISSING_SIMILARITY_VALUE = 0.0`, `MISSING_NOVELTY_VALUE = 0.0`,
  and `SOURCE_SIGNALS = "phash+ssim+ocr+clip"` are fixed code-level
  constants in `recap/stages/rank.py`. None are exposed as CLI flags,
  env vars, or config. No new Python or system dependencies are
  introduced; no ML model is loaded. The stage is marking-only: it
  does not apply keep/reject thresholds, enforce a screenshot budget,
  write `selected_frames.json`, modify `report.md`, or invoke any
  VLM. It does not touch `transcript.json`, `scenes.json`,
  `chapter_candidates.json`, `frame_scores.json`,
  `frame_windows.json`, `frame_similarities.json`, or
  `candidate_frames/`. Per-chapter entries are `chapter_index`
  (1-based), `start_seconds`, `end_seconds`, `frame_count`, `frames`;
  per-frame entries are `rank`, `scene_index`, `frame_file`,
  `midpoint_seconds`, `clip_similarity`, `text_novelty`,
  `duplicate_of`, `composite_score`; top-level keys are `video`,
  `scenes_source`, `chapters_source`, `scores_source`,
  `windows_source`, `similarities_source`, `weights`,
  `missing_similarity_value`, `missing_novelty_value`,
  `source_signals`, `input_fingerprints` (SHA-256 over canonical
  JSON for each of the five input artifacts, keyed by filename),
  `chapter_count`, `frame_count`, `chapters`.

This Phase 3 slice is opt-in. `recap run` continues to execute the
Phase 1 stages only. Per-chapter ranking runs via
`recap rank --job <path>`.

## What the fifth Phase 3 slice includes

- **Deterministic pre-VLM keep/reject shortlist.** Read
  `frame_ranks.json` and write `frame_shortlist.json`. For every
  candidate frame in every chapter, a closed-vocabulary
  `decision` and ordered `reasons` list are recorded. Evaluation
  is per-frame in the rank-ascending order already in
  `frame_ranks.json`:

  1. If `duplicate_of is not None` → `decision =
     "rejected_duplicate"`, reasons = `["duplicate_of_predecessor"]`.
  2. Else if `clip_similarity_or_0 < CLIP_KEEP_THRESHOLD` and
     `text_novelty_or_0 < OCR_NOVELTY_THRESHOLD` → `decision =
     "rejected_weak_signal"`, reasons =
     `["clip_similarity_below_threshold",
     "text_novelty_below_threshold"]`.
  3. Else if the chapter has fewer than `HERO_PER_CHAPTER` heroes
     → `decision = "hero"`, reasons = `["kept_as_hero"]`.
  4. Else if the chapter has fewer than `SUPPORTING_PER_CHAPTER`
     supporting → `decision = "supporting"`, reasons =
     `["kept_as_supporting"]`.
  5. Else → `decision = "dropped_over_budget"`, reasons =
     `["exceeds_total_per_chapter"]`.

  `CLIP_KEEP_THRESHOLD = 0.30`, `OCR_NOVELTY_THRESHOLD = 0.25`,
  `HERO_PER_CHAPTER = 1`, `SUPPORTING_PER_CHAPTER = 2`,
  `TOTAL_PER_CHAPTER = 3`, and
  `POLICY_VERSION = "keep_reject_v1"` are fixed code-level
  constants in `recap/stages/shortlist.py`. None are exposed as
  CLI flags, env vars, or config. A retune must bump
  `POLICY_VERSION` so the skip contract invalidates any stored
  shortlist. The `TOTAL_PER_CHAPTER = 3` budget is intentionally
  matched to Stage 7's "top 1 to 3 candidate frames per chapter"
  VLM verification step — this is a pre-VLM shortlist, not the
  final report screenshot budget, and it does not implement
  final screenshot embedding. No new Python or system
  dependencies are introduced; no ML model is loaded. The stage
  is marking-only and pre-VLM: it does not write
  `selected_frames.json` (that filename is reserved for Phase 4
  post-VLM finalists), invoke any VLM, generate captions, embed
  screenshots in `report.md`, export DOCX / HTML / Notion / PDF,
  add UI, or do any speaker diarization / recognition /
  separation work. It does not touch `transcript.json`,
  `scenes.json`, `chapter_candidates.json`, `frame_scores.json`,
  `frame_windows.json`, `frame_similarities.json`,
  `frame_ranks.json`, `candidate_frames/`, or `report.md`. Blur /
  low-information detection and VLM-dependent "shows code /
  diagrams / settings / dashboards" judgments are deferred.
  Per-chapter entries are `chapter_index` (1-based),
  `start_seconds`, `end_seconds`, `frame_count`, `kept_count`,
  `hero_scene_index` (int or null), `supporting_scene_indices`
  (list of ints, possibly empty), `frames`; per-frame entries
  are `rank`, `scene_index`, `frame_file`, `midpoint_seconds`,
  `composite_score`, `clip_similarity` (original, possibly
  null), `text_novelty` (original, possibly null),
  `duplicate_of` (original, possibly null), `decision`,
  `reasons`; top-level keys are `video`, `ranks_source`
  (`frame_ranks.json`), `thresholds`, `budget`, `policy_version`,
  `input_fingerprints` (SHA-256 hex over canonical JSON of
  `frame_ranks.json`), `chapter_count`, `frame_count`,
  `kept_count`, `rejected_count`,
  `dropped_over_budget_count`, `chapters`.

This Phase 3 slice is opt-in. `recap run` continues to execute the
Phase 1 stages only. The keep/reject shortlist runs via
`recap shortlist --job <path>`.

## What the first Phase 4 slice includes

- **Optional VLM verification over the pre-VLM shortlist.** Read
  `frame_shortlist.json`, `chapter_candidates.json`, and
  `frame_windows.json`, load each kept candidate's JPEG from
  `candidate_frames/<frame_file>`, and write `selected_frames.json`.
  Only frames with shortlist `decision in {"hero", "supporting"}`
  are verified; `rejected_duplicate`, `rejected_weak_signal`, and
  `dropped_over_budget` frames are never sent to the provider.
  Two providers live as siblings in `recap/stages/verify.py`,
  dispatched by a single `if/elif` on `--provider` (no registry,
  ABC, plugin system, queue, worker, or config file):

  - `_verify_mock` (default) — fully deterministic, no network.
    Per frame: `relevance = "relevant"` when
    `composite_score >= 0.30`, else `"uncertain"`;
    `confidence = clamp(composite_score, 0.0, 1.0)`;
    `caption = null`. Output is byte-identical across re-runs.
  - `_verify_gemini` (opt-in via `--provider gemini`) — one stdlib
    `urllib.request` POST per kept frame to
    `{base_url}/v1beta/models/{model}:generateContent?key=<key>`
    with an inline `image/jpeg` part. The prompt requires a
    single strict JSON object shaped
    `{"relevance","confidence","caption"}`; out-of-vocabulary
    `relevance`, non-numeric `confidence`, or non-string
    `caption` raise a stage error. `caption` is stripped,
    truncated to `VLM_MAX_CAPTION_CHARS = 240`, and an empty
    string collapses to `null`. One request per frame, no
    retries in this slice. No API key is persisted to
    artifacts, logs, docs, or prompts.

  Decision policy (closed vocabulary):

  - `relevance == "not_relevant"` → `decision = "vlm_rejected"`,
    reasons append `"vlm_not_relevant"`.
  - `relevance == "relevant"` → keep at the shortlist rung:
    `"selected_hero"` if the frame was the shortlist hero,
    else `"selected_supporting"`; reasons append
    `"vlm_relevant"`.
  - `relevance == "uncertain"` and
    `confidence >= VLM_CONFIDENCE_KEEP_THRESHOLD` → keep at the
    shortlist rung, reasons append `"vlm_uncertain_kept"`.
    Otherwise reject as `"vlm_not_relevant"`.
  - Hero promotion: if the original hero is rejected and at
    least one supporting survives, the surviving supporting with
    the lowest `rank` is promoted to `"selected_hero"` and its
    reasons append `"vlm_tie_broken_by_rank"`. The chapter
    `hero` and `supporting_scene_indices` are rebuilt after
    promotion.

  Fixed code-level constants in `recap/stages/verify.py`:
  `VLM_DEFAULT_PROVIDER = "mock"`,
  `GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"`,
  `GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"`,
  `GEMINI_TIMEOUT_SECONDS = 120`,
  `VLM_PROVIDER_VERSION = "vlm_v1"`,
  `VLM_POLICY_VERSION = "vlm_select_v1"`,
  `VLM_CONFIDENCE_KEEP_THRESHOLD = 0.50`,
  `CHAPTER_CONTEXT_CHARS = 1500`,
  `WINDOW_CONTEXT_CHARS = 1500`,
  `VLM_MAX_CAPTION_CHARS = 240`. None are exposed as CLI flags.
  A retune of the prompt, request shape, parse rules, or decision
  policy must bump either `VLM_PROVIDER_VERSION` or
  `VLM_POLICY_VERSION` so the skip contract invalidates any
  stored artifact.

  Environment variables (read only on `--provider gemini` and only
  when a recompute is required): `GEMINI_API_KEY` (required),
  `GEMINI_MODEL` (optional override of the default), and
  `GEMINI_BASE_URL` (optional override of the default). A skip
  path whose stored artifact already matches the requested
  provider / model does NOT require the key.

  Per-chapter entries: `chapter_index` (1-based), `start_seconds`,
  `end_seconds`, `hero` (object with `scene_index`, `frame_file`,
  `midpoint_seconds` when a hero was selected, else `null`),
  `supporting_scene_indices` (list of ints, possibly empty),
  `frame_count` (count of shortlist frames in the chapter across
  all decisions), `verified_count` (count of kept shortlist frames
  sent to the provider), `selected_count`, `rejected_count`,
  `frames`. Per-frame entries: `rank`, `scene_index`,
  `frame_file`, `midpoint_seconds`, `composite_score`,
  `clip_similarity` (original, possibly null), `text_novelty`
  (original, possibly null), `window_text` (the truncated
  per-frame transcript window actually shown to the provider),
  `shortlist_decision` (`"hero"` or `"supporting"`),
  `verification` (`{provider, model, relevance, confidence,
  caption}`), `decision`
  ∈ `{"selected_hero","selected_supporting","vlm_rejected"}`,
  `reasons` (ordered; first entry is the shortlist keep reason —
  `"kept_as_hero"` or `"kept_as_supporting"` — followed by one
  of `"vlm_relevant"`, `"vlm_uncertain_kept"`,
  `"vlm_not_relevant"`, optionally `"vlm_tie_broken_by_rank"`).
  Top-level keys: `video`, `shortlist_source`
  (`frame_shortlist.json`), `chapters_source`
  (`chapter_candidates.json`), `windows_source`
  (`frame_windows.json`), `frames_dir` (`candidate_frames`),
  `provider` (`"mock"` or `"gemini"`), `model` (`null` for mock,
  the resolved Gemini model id otherwise), `provider_version`,
  `policy_version`, `caption_mode` (`"off"` for mock, `"short"`
  for gemini), `context` (dict with `chapter_context_chars` and
  `window_context_chars`), `input_fingerprints` (dict with
  SHA-256 hex digests over canonical JSON for
  `frame_shortlist.json`, `chapter_candidates.json`, and
  `frame_windows.json`), `chapter_count`, `frame_count`
  (top-level total shortlist frames across all chapters and
  decisions), `verified_count`, `selected_count`,
  `rejected_count`, and `chapters`.

  **Skip contract.** `recap verify` skips when the stored
  `selected_frames.json` matches the requested provider, resolved
  model, `provider_version`, `policy_version`, `caption_mode`,
  `context`, and all three `input_fingerprints`. On skip the
  `GEMINI_API_KEY` is NOT required (mirrors the Deepgram slice).
  Any drift in any of the three input artifacts — including
  drift in chapter `text` or per-frame `window_text` that does
  not alter the shortlist decisions — triggers a recompute.
  `recap verify --force` deletes `selected_frames.json` before
  recomputing.

  **Atomic writes.** `selected_frames.json` is written via a
  `.json.tmp` sibling and `os.replace`; any failure removes the
  temp file, so no partial artifact remains on disk.

  **Error paths (all exit 2 with a single-line `error: ...`, no
  traceback, no partial `selected_frames.json{,.tmp}` on disk):**
  missing or malformed `frame_shortlist.json`,
  `chapter_candidates.json`, or `frame_windows.json`; missing
  candidate frame image under `candidate_frames/`; missing
  `GEMINI_API_KEY` on recompute with `--provider gemini`; Gemini
  401/403 (`gemini authentication failed`), other non-2xx
  (`gemini request failed`), timeout (`gemini request timed out
  after <n>s`), network error (`gemini network error: <reason>`),
  invalid envelope JSON (`gemini returned invalid JSON`),
  malformed verification payload (`gemini returned invalid
  verification JSON`), or out-of-vocabulary `relevance`
  (`gemini returned unsupported relevance`).

  **Ingest invalidation.** `recap ingest --force` against a
  job with a different source now also removes
  `selected_frames.json` and resets `stages.verify` to
  `pending`, matching the existing downstream invalidation
  behavior for all other Phase 2/3 artifacts.

  This slice is explicitly a verification slice. It does not
  write to `report.md`, embed screenshots, render captions into
  the report, export DOCX / HTML / Notion / PDF, add UI, or
  change the composition of `recap run`. `selected_frames.json`
  is now produced by `recap verify` rather than being reserved
  for later work. No new Python or system dependencies are
  introduced; no ML model is loaded locally.

This Phase 4 slice is opt-in. `recap run` continues to execute
the Phase 1 stages only. The slice runs via
`recap verify --job <path> [--provider {mock,gemini}]`. Remaining
Phase 3 / Phase 4 work (topic-shift detection, speaker
recognition / manual labels, chapter titling, DOCX / HTML /
Notion / PDF export, WhisperX, pyannote, Groq, UI) remains
deferred.

## What the second Phase 4 slice includes

- **Report screenshot and caption embedding.** `recap assemble`
  now reads `selected_frames.json` (when present) and
  `chapter_candidates.json`, and inserts a `## Chapters` section
  between `## Media` and `## Transcript` in `report.md`. Each
  chapter renders the selected hero image first, then the selected
  supporting images in the order of the chapter's
  `supporting_scene_indices`, followed by the chapter body `text`
  from `chapter_candidates.json` (whitespace-collapsed; omitted if
  empty). Only frames with `decision in {"selected_hero",
  "selected_supporting"}` are rendered; `vlm_rejected` frames are
  never rendered. Image links use relative POSIX paths of the form
  `candidate_frames/<frame_file>` and no image file is copied,
  renamed, or rewritten. When a rendered frame's
  `verification.caption` is a non-empty string, the caption is
  rendered in italics on its own paragraph directly below that
  image; otherwise no caption is rendered and no fallback text is
  invented. Chapter headings are `### Chapter {chapter_index} —
  [HH:MM:SS – HH:MM:SS]`. No chapter titles are generated (titling
  remains deferred). No VLM is invoked during assembly.
- **Absent-selected fallback.** When `selected_frames.json` does
  not exist, the emitted `report.md` is byte-identical to the
  Phase-1 basic report (no `## Chapters` section, no image links,
  no captions). `recap run`'s stage composition is unchanged
  (ingest → normalize → transcribe → assemble), so a fresh run on
  a new recording still produces the Phase-1 basic report.
- **Atomic write.** `report.md` is written via a `report.md.tmp`
  sibling and atomically `replace`d on success. On failure the
  temp file is removed and any existing `report.md` is left
  unchanged.
- **Skip contract.** The existing simple skip contract is
  preserved: if `report.md` already exists and `--force` is not
  passed, the stage is skipped. After running `recap verify` to
  produce or refresh `selected_frames.json`, run
  `recap assemble --force` to regenerate `report.md` with the
  embedded screenshots and captions. No fingerprint-based
  auto-recompute is introduced in this slice.
- **Validation and errors.** When `selected_frames.json` is
  present, the stage additionally requires
  `chapter_candidates.json` to exist and be readable. The
  following conditions exit `2` with a single-line
  `error: ...` and leave any existing `report.md` unchanged
  (no `report.md.tmp` remains on disk): invalid JSON or
  structurally malformed `selected_frames.json`; a selected
  frame missing `frame_file`, `scene_index`, `midpoint_seconds`,
  or `decision`; missing or malformed `chapter_candidates.json`;
  a candidate image referenced by a selected frame missing from
  `candidate_frames/` (`error: missing candidate frame:
  candidate_frames/<frame_file>`); a `supporting_scene_indices`
  entry that does not resolve to a `selected_supporting` frame
  in that chapter.
- **What this slice does not do.** It does not mutate
  `selected_frames.json`, `chapter_candidates.json`, or any
  image on disk. It does not add a new CLI flag or new stage
  to `job.STAGES`. It does not call any VLM. It does not add
  a Python or system dependency. It does not export DOCX /
  HTML / Notion / PDF. It does not add UI. It does not
  implement chapter titling or topic-shift detection.

Optional HTML and DOCX export are both implemented as later
Phase 4 slices (see below). PDF and Notion export remain
deferred, as do topic-shift chaptering, chapter titling,
WhisperX, pyannote, Groq, speaker recognition / manual labels,
and UI. `recap run` remains Phase-1-only.

## What the third Phase 4 slice includes

- **Optional HTML export.** `recap export-html --job <path>
  [--force]` writes `report.html` at the job root. It reads the
  same artifacts as `recap assemble` (`job.json`,
  `metadata.json`, `transcript.json`, and — when present —
  `selected_frames.json` + `chapter_candidates.json`) and emits a
  standalone HTML document via direct string construction. No
  Markdown parser is used; no network call is made; no new
  Python or system dependency is introduced. The document
  declares `<!doctype html>`, `<html lang="en">`,
  `<meta charset="utf-8">`, and a viewport meta tag, and embeds
  a small inline `<style>` block (basic typography plus
  `img { max-width: 100%; height: auto; }`). Every
  content-bearing string — job ID, source filename, container /
  codec metadata, transcript engine, detected language,
  transcript segment text, chapter body text, and VLM captions —
  is escaped with stdlib `html.escape(..., quote=True)`, so raw
  transcript or caption content cannot inject markup.
- **Content parity with `recap assemble`.** When
  `selected_frames.json` is present, an `<h2>Chapters</h2>`
  block sits between Media and Transcript with one
  `<section class="chapter">` per chapter: the selected hero
  image first (when present), then selected supporting images in
  `supporting_scene_indices` order, with `<p><em>...</em></p>`
  captions rendered only when `verification.caption` is a
  non-empty string after whitespace collapse, followed by the
  chapter body text from the matching
  `chapter_candidates.json` entry as a single escaped `<p>`
  (omitted if empty). Image `src` values are relative POSIX
  paths exactly `candidate_frames/<frame_file>`; images are
  never copied, renamed, re-encoded, or base64-inlined. When
  `selected_frames.json` is absent, no Chapters section is
  rendered — only the header, media summary, and transcript
  segments.
- **Validation contract (matches `recap assemble`).** When
  `selected_frames.json` is present the stage enforces the same
  selected-path contract: structural and numeric/type checks on
  every chapter and frame (`chapter_index` integer,
  `start_seconds` / `end_seconds` / `midpoint_seconds` numeric,
  `decision` in `{"selected_hero", "selected_supporting",
  "vlm_rejected"}`, hero shape when non-null,
  `supporting_scene_indices` entries integers); at most one
  `selected_hero` per chapter; `chapter.hero` must match the
  selected_hero frame on `scene_index`, `frame_file`, and
  `midpoint_seconds`; the ordered `scene_index` list of
  `selected_supporting` frames must exactly equal
  `supporting_scene_indices`; every selected chapter's
  `chapter_index` must be present in `chapter_candidates.json`;
  every referenced candidate image must exist under
  `candidate_frames/`. Any violation exits `2` with a one-line
  `error: ...` (`selected_frames.json malformed: ...`,
  `chapter_candidates.json malformed: ...`,
  `chapter_candidates.json has no chapter with index <n>
  required by selected_frames.json`, or `missing candidate
  frame: candidate_frames/<frame_file>`) and leaves any existing
  `report.html` unchanged with no `report.html.tmp` on disk.
- **Skip / restart.** If `report.html` exists and `--force` is
  not passed, the stage is skipped and
  `stages.export_html.skipped` is set to `true`. `--force`
  recomputes. Writes are atomic via a `report.html.tmp` sibling
  and `Path.replace` on success; on exception the temp file is
  removed and any existing `report.html` is preserved. The
  `export_html` stage is **not** added to `job.STAGES`; it
  appends its own entry under `job.stages` the same way
  `verify`, `shortlist`, `rank`, etc. do.
- **What this slice does not do.** It does not modify
  `recap/stages/assemble.py`, `recap run` composition,
  `job.STAGES`, or any upstream stage. It does not invoke any
  VLM/LLM. It does not read or mutate `report.md`. It does not
  copy, rename, or rewrite images. It does not add a CLI flag
  beyond `--job` / `--force`. It does not export DOCX, Notion,
  or PDF, and does not add a Markdown parser dependency.

This slice is opt-in. `recap run` continues to compose only
`ingest → normalize → transcribe → assemble`. Notion and PDF
export, topic-shift chaptering, chapter titling, WhisperX,
pyannote, Groq, and UI all remain deferred.

## What the fourth Phase 4 slice includes

- **Optional DOCX export.** `recap export-docx --job <path>
  [--force]` writes `report.docx` at the job root using
  `python-docx >= 1.1` (newly added to `requirements.txt` and
  `pyproject.toml`). The stage reads the same artifacts as
  `recap export-html` (`job.json`, `metadata.json`,
  `transcript.json`, and — when present — `selected_frames.json`
  + `chapter_candidates.json`) and produces a standard OOXML
  document via `Document()` and its `add_heading` /
  `add_paragraph` / `add_picture` primitives. No Pandoc, no
  LibreOffice, no PDF output, and no hand-drafted XML. No
  network call is made. No VLM / LLM is invoked.
- **Content parity with the Markdown and HTML reports.**
  `Heading 1` is `Recap: {title}`; metadata paragraphs cover Job
  ID / Source file / Created when available; `Heading 2: Media`
  lists duration / container / video / audio. When
  `selected_frames.json` is present, a `Heading 2: Chapters`
  block appears with one `Heading 3` per chapter embedding the
  selected hero first and then each selected supporting image in
  `supporting_scene_indices` order via
  `Document.add_picture(path, width=Inches(6.0))`. Captions
  render as italic-run paragraphs only when
  `verification.caption` is a non-empty string after whitespace
  collapse. The chapter body text from the matching
  `chapter_candidates.json` entry is added as a single
  paragraph after the images, or omitted when empty. The final
  section is `Heading 2: Transcript` followed by
  `Heading 3: Segments` and one `List Bullet` paragraph per
  non-empty transcript segment.
- **Image handling.** Referenced candidate images are embedded
  into the DOCX package; the image files on disk are not
  copied, renamed, or re-encoded. A fixed width of `6.0` inches
  is applied to every embedded image; no per-frame sizing is
  computed.
- **Validation contract (matches `recap export-html`).** When
  `selected_frames.json` is present the stage enforces the same
  structural, numeric, and coherence checks export_html does:
  type checks on every chapter and frame, `decision` closed
  vocabulary (`selected_hero`, `selected_supporting`,
  `vlm_rejected`), at most one `selected_hero` per chapter,
  `chapter.hero` must match the selected_hero frame on
  `scene_index`, `frame_file`, and `midpoint_seconds`, the
  ordered `scene_index` list of `selected_supporting` frames
  must exactly equal `supporting_scene_indices`, every selected
  chapter's `chapter_index` must be present in
  `chapter_candidates.json`, and every referenced
  `frame_file` must pass the plain-filename safety check
  (no `/`, no `\`, no absolute paths, no `.` or `..`,
  `Path(name).name == name`) and the file must exist under
  `candidate_frames/`. Any violation exits `2` with a one-line
  `error: ...` (`selected_frames.json malformed: ...`,
  `chapter_candidates.json malformed: ...`,
  `chapter_candidates.json has no chapter with index <n>
  required by selected_frames.json`, or `missing candidate
  frame: candidate_frames/<frame_file>`) and leaves any
  existing `report.docx` untouched with no `report.docx.tmp`
  on disk.
- **Skip / restart.** If `report.docx` exists and `--force` is
  not passed, the stage is skipped and
  `stages.export_docx.skipped` is set to `true`. `--force`
  recomputes. Writes are atomic via `Document.save(str(tmp))`
  to a `report.docx.tmp` sibling followed by `Path.replace`; on
  exception the temp file is removed and any existing
  `report.docx` is preserved. The `export_docx` stage is
  **not** added to `job.STAGES`; it appends its own entry under
  `job.stages` exactly like `export_html`, `verify`,
  `shortlist`, `rank`, etc.
- **Determinism caveat.** DOCX output is not byte-identical
  across reruns because python-docx writes package-level
  timestamps (`dcterms:created`, `dcterms:modified`) into
  `core.xml`. This slice guarantees structural parity — the
  set of headings, inline-shape count, and paragraph content
  — not byte-level stability.
- **What this slice does not do.** It does not modify
  `recap/stages/assemble.py`, `recap/stages/export_html.py`,
  `recap/stages/verify.py`, any upstream stage, `recap run`
  composition, or `job.STAGES`. It does not invoke any
  VLM/LLM. It does not read or mutate `report.md`,
  `report.html`, or `selected_frames.json`. It does not copy,
  rename, or rewrite images. It does not add a CLI flag
  beyond `--job` / `--force`. It does not export PDF, Notion,
  or intermediate XML.

This slice is opt-in. `recap run` continues to compose only
`ingest → normalize → transcribe → assemble`. PDF and Notion
export, topic-shift chaptering, chapter titling, WhisperX,
pyannote, Groq, and UI all remain deferred.

## UI: local dashboard, JSON API, and React transcript workspace

`recap ui --host 127.0.0.1 --port 8765 --jobs-root jobs` starts a
stdlib `http.server.ThreadingHTTPServer` bound to `127.0.0.1` by
default and serves the legacy HTML dashboard, a small JSON API, and
the built React app under `/app/*`. The Python module lives at
`recap/ui.py`; the React source lives under `web/` and is built with
Vite into `web/dist/`. Existing server-rendered routes remain live.
Primary `GET` routes:

- `GET /` — jobs index. Scans direct subdirectories of the
  configured jobs root, reads each `job.json`, sorts by
  `created_at` descending, and renders a table with job id,
  created-at, status badge, md/html/docx artifact indicators, and
  a one-click link to `report.html` when present.
- `GET /job/<job_id>/` — job detail page. Renders metadata, a
  stage table in the canonical pipeline order (ingest, normalize,
  transcribe, assemble, scenes, dedupe, window, similarity,
  chapters, rank, shortlist, verify, export_html, export_docx;
  unknown stages appended alphabetically) with a compact "extra"
  cell rendering of fields beyond status/started_at/finished_at/
  error, and a list of every whitelisted artifact present on
  disk.
- `GET /job/<job_id>/<filename>` — serves one of a fixed
  whitelist of job-root files: `report.md`, `report.html`,
  `report.docx`, `metadata.json`, `transcript.json`,
  `transcript.srt`, `job.json`, `selected_frames.json`,
  `chapter_candidates.json`, `frame_shortlist.json`,
  `frame_ranks.json`, `frame_similarities.json`,
  `frame_windows.json`, `frame_scores.json`, `scenes.json`,
  `speaker_names.json`.
- `GET /job/<job_id>/candidate_frames/<filename>` — serves a
  single image under `candidate_frames/` with extension `.jpg`,
  `.jpeg`, or `.png`. Any other extension or any traversal
  attempt returns 404.
- `recap insights --job <path> --provider mock|groq [--force]` is an
  opt-in slice that writes `insights.json` with an overview, quick
  bullets, per-chapter title/summary/bullets/action items, and a flat
  list of action items. The mock provider is deterministic and
  offline; the Groq provider calls `https://api.groq.com` via stdlib
  HTTP using `GROQ_API_KEY` (+ `GROQ_MODEL`, `GROQ_BASE_URL`) and
  fails cleanly on a missing key with the stage marked `failed`.
  `recap insights` is **not** in `job.STAGES` and is **not** invoked
  by `recap run`. When `insights.json` is present, `recap assemble`,
  `recap export-html`, and `recap export-docx` render an `## Overview`
  section and enrich the existing `## Chapters` rendering with titles,
  summaries, bullets, action items, and speaker focus. When absent,
  exports stay byte-compatible with prior behavior.
- **2026-04-21 React product polish.** Frontend-only consolidation
  pass. `JobCard` lost the long artifact-chip strip in favour of a
  single readiness sentence ("Report ready · Insights · …" or
  "Transcript ready · Report not generated") with one primary
  "Open job dashboard" CTA and a secondary `Transcript` text link;
  the per-card status badge moved into the title group so readiness
  is obvious at a glance. `JobsIndexPage` stats collapsed from boxy
  tiles into a flat baseline-aligned row. `JobDetailPage` hero now
  carries one subline (status badge · updated · engine/model/segments
  chips) and a single action strip (primary "Open transcript
  workspace", ghost "Review screenshots", quiet text-link "Open
  report · HTML / Markdown / DOCX", small "Legacy detail page"). The
  artifact grid moved into a `<details>` disclosure labelled
  "Artifacts on disk". `RunActionsPanel` dropped the verbose intro
  paragraph and wraps the "11-stage chain" footer notes in an
  "About this run" disclosure. `TranscriptWorkspacePage` collapsed
  the redundant artifact-summary card and tightened the header to
  one status + meta line. `FrameReviewPage` now groups frame cards
  by chapter (`Chapter N — display_title` headings) instead of one
  flat grid; per-card raw scoring (CLIP similarity, text novelty,
  OCR text, duplicate_of) is behind a "Scoring details" disclosure
  so the algorithm's hero/supporting decision and VLM verdict stay
  on top. `AppShell` topbar carries a single primary "New recording"
  CTA and a quieter `Legacy` text link. The body background lost the
  triple radial wash for one soft warm gradient. No backend changes,
  no API changes, no new dependencies; legacy HTML routes still
  render their old surfaces unchanged.
- The React dashboard at `/app/job/<id>` links to a new frame-review
  workspace at `/app/job/<id>/frames`. `FrameReviewPage` fetches the
  merged view from `GET /api/jobs/<id>/frames`, lays out a
  `FrameCard` grid (one card per on-disk candidate frame) with
  image + timestamp + chapter context + algorithm-output pills
  (hero / supporting / VLM-rejected, shortlist decision, rank) and a
  **Review** fieldset with `keep` / `reject` / `unset` radios and a
  300-char note textarea. Changes batch locally and an explicit
  **Save review** writes the whole batch via
  `POST /api/jobs/<id>/frame-review`; **Discard changes** reverts.
  Filter tabs (All / Shortlist / Selected / Reviewed) narrow the
  grid. The page has an empty state when no visual artifacts exist,
  pointing at `Generate rich report`. The hero action bar on the
  dashboard carries a **Review screenshots** link that renders
  `Review screenshots (empty)` when `selected_frames.json` is
  missing so the CTA still targets the right surface and the empty
  state educates the user.
- The React transcript workspace at `/app/job/<id>/transcript`
  renders a **chapter sidebar** (`ChapterSidebar`) in the left rail
  when the merged chapter list from `GET /api/jobs/<id>/chapters`
  is non-empty. Each row shows the index, display title (with a
  `custom` pill when the title comes from the overlay), timestamp
  range, and (when insights are present) a short summary, bullets,
  and action items. Clicking a row calls `video.currentTime =
  chapter.start_seconds` and issues `video.play()`. Active-chapter
  highlight mirrors the existing active-row sync: a `timeupdate` /
  `seeking` / `play` listener walks the chapter list to find the
  chapter containing the current time, and the active row carries
  both an accent border and `aria-current="true"` so the cue is not
  color-only. Renaming a chapter opens an inline input
  pre-populated with the current title; Enter / Save writes to
  `POST /api/jobs/<id>/chapter-titles`; clearing the field removes
  the custom mapping; Escape cancels. A compact `ChaptersCard`
  preview on the React dashboard (`/app/job/<id>`) shows the first
  five titles, a "custom title" count, and a link to the transcript
  workspace. `RunActionsPanel`'s completion callback now also
  refreshes the chapter list so a freshly-run rich-report or
  insights run is reflected in the sidebar without a page reload.
- The React `/app/job/<id>` dashboard now hosts a **Generate &
  enrich** panel (`RunActionsPanel`) that drives the two new run-
  dispatch endpoints. It renders the latest insights / rich-report
  run status (no-run / in-progress / success / failed with both a
  colored dot and a labelled pill so no information is color-only),
  polls the status endpoints every 2.5s while something is in
  flight, shows the current rich-report stage and an ordered stage
  list with failed-stage stderr inlined as a bounded `<pre>`, and
  refreshes the parent job summary + insights preview on completion.
  Starting an insights run posts `{provider, force}`; starting the
  rich-report chain posts an empty body. The legacy rich-report
  status page at `/job/<id>/run/rich-report/last` remains live and
  is linked from the panel as a fallback. Actions are keyboard-
  accessible and the `aria-busy` / `disabled` attributes track the
  run state.
- The React surface now has four pages: `/app/` (jobs index),
  `/app/new` (start a new recap job — source picker, engine
  selector, "what happens next" panel, and a single dispatch button
  wired to `POST /api/jobs/start`), `/app/job/<id>` (job dashboard —
  hero, stage timeline, artifact grid, insights preview), and
  `/app/job/<id>/transcript` (transcript workspace). The legacy HTML
  detail page at `/job/<id>/` and the legacy `/new` form remain live
  as fallbacks. Jobs-index `JobCard` primary click now opens the
  React dashboard; the secondary "Transcript" action still routes
  to the transcript workspace. The `/app/new` page exposes three
  tabs inside the "Source video" card: **Sources root** (pick an
  existing file), **Record screen** (capture a clip in the browser
  via Screen Capture + `MediaRecorder` and upload it via
  `POST /api/recordings` — see below), and **Absolute path**. The
  record tab gracefully renders an "unsupported" notice when the
  browser lacks `getDisplayMedia` or `MediaRecorder`, and
  transcription never starts automatically — saving and starting
  are separate explicit actions.
- `GET /api/csrf` — returns the server CSRF token as JSON for the
  React app.
- `GET /api/jobs` — returns the jobs index listing as
  `{"jobs": [summary, ...]}`, sorted by `created_at` descending.
  Malformed `job.json` entries are silently dropped so the frontend
  always receives parseable summaries.
- `GET /api/jobs/<job_id>` — returns a single job summary. Summaries
  include artifact flags and canonical URLs for `analysis.mp4`,
  transcript JSON, speaker names, the legacy detail/transcript pages
  (`detail_html` / `legacy_detail` / `legacy_transcript`), the React
  dashboard + transcript workspace (`react_detail` / `react_transcript`),
  the three report formats, and the insights artifact + API endpoint
  (`insights_json` / `insights`).
- `GET /api/jobs/<job_id>/transcript` — returns the raw
  `transcript.json` payload as JSON.
- `GET /api/jobs/<job_id>/insights` — returns parsed
  `insights.json` (read-only). 404 with reason `no-insights` when
  absent; 500 with reason `insights-unreadable` when malformed.
  Never generates insights.
- `GET /api/jobs/<job_id>/speaker-names` — returns
  `speaker_names.json` or the empty default document when absent or
  malformed.
- `GET /api/sources` — lists video files under the configured
  `--sources-root` as
  `{sources_root, sources_root_exists, extensions, sources: [{name,
  size_bytes, modified_at}, ...]}`. Filters on the same extension set
  accepted by the legacy `POST /run`, skips non-files, and never reads
  file contents.
- `GET /api/engines` — reports transcription engine availability as
  `{engines: [{id, label, category, default, available, note}, ...],
  default}`. `faster-whisper` is always available and the default;
  `deepgram` is available only when `DEEPGRAM_API_KEY` is set in the
  server environment. The value of the key is never echoed.
- `POST /api/jobs/start` — dispatches a new run. Body:
  `{"source": {"kind": "sources-root", "name": "..."} | {"kind":
  "absolute-path", "path": "..."}, "engine": "..."}`. Reuses the
  legacy `POST /run` safety primitives (loopback Host pinning,
  `X-Recap-Token` CSRF, 8 KiB body cap, source-path containment under
  the sources root, engine allowlist, `DEEPGRAM_API_KEY` env check,
  single `_run_slot` semaphore) and the shared ingest +
  `_background_run` implementation. Returns 202 with
  `{job_id, engine, react_detail, legacy_detail, started_at}`.
  Validation failures return JSON `{"error": "...", "reason": "..."}`.
  Never logs the request body, CSRF token, Deepgram key, or captured
  subprocess output. A test-only `RECAP_API_STUB_JOB_START=1`
  environment flag — opted in only by `scripts/verify_api.py` — runs
  every validation step but skips the real `recap ingest` +
  `recap run` dispatch so CI can prove routing without running heavy
  transcription. The legacy `POST /run` form remains unchanged.
- `GET /api/jobs/<id>/chapters` — merged chapter-list view. Combines
  `chapter_candidates.json` (timing + transcript text), `insights.json`
  (title + summary + bullets + action_items + speaker_focus), and the
  new `chapter_titles.json` overlay (custom_title override). Response
  shape:
  `{chapters: [{index, start_seconds, end_seconds, fallback_title,
  custom_title, display_title, summary?, bullets?, action_items?,
  speaker_focus?}, ...], sources: {chapter_candidates, insights,
  chapter_titles_overlay, insights_sources}, overlay: {...}}`. Never
  generates; purely a read-merge. When neither `chapter_candidates.json`
  nor `insights.json` is present, `chapters` is an empty list. Malformed
  upstream artifacts log a single `[recap-ui] chapters list: <file>
  skipped: ...` line and degrade to an empty list rather than erroring.
  `fallback_title` prefers the insights-provided chapter title, then
  the first sentence of `chapter_candidates.text` (truncated to ~60
  chars), then the generic `"Chapter N"`.
- `GET /api/jobs/<id>/chapter-titles` — returns
  `{version: 1, updated_at: string|null, titles: {index-string:
  title, ...}}`. Returns the empty default when the file is absent
  or malformed; mirrors the `speaker_names.json` read-side policy.
- `POST /api/jobs/<id>/chapter-titles` — update the overlay. Reuses
  the speaker-names safety primitives: Host pinning, `X-Recap-Token`
  CSRF, `_API_POST_BODY_MAX` body cap, per-job lock, and atomic
  `<file>.tmp` → `os.replace` write. Body shape
  `{"titles": {"1": "Intro", "2": ""}}`. Keys must be non-negative
  integer strings; empty / whitespace-only values remove the mapping;
  values are trimmed, bounded at 120 chars
  (`_API_CHAPTER_TITLE_MAX_LEN`), and rejected when they contain
  control chars except tab. Reasons drawn from
  `{host, content-type, content-length-missing, body-too-large,
  csrf, no-such-job, bad-json, bad-schema, bad-key-shape, bad-value,
  too-long, write-failed, lock}`. The overlay **never** mutates
  `chapter_candidates.json` or `insights.json`. Exporter integration
  (`recap assemble` / `export-html` / `export-docx` reading the
  overlay) is a deferred follow-up — today the overlay only affects
  the React surface.
- **Library organization (projects / archive / rename, slice 12).**
  A new `<jobs-root>/.recap_library.json` sidecar maps
  ``{job_id: {title, project, archived}}``. Writes go through
  `_write_library(jobs_root, entries)` — atomic
  ``<file>.tmp`` → ``os.replace`` under a process-wide
  ``_library_lock`` so concurrent POSTs against different jobs
  don't race on the shared file. The job directory on disk is
  never moved, renamed, or deleted; organization lives entirely
  in the sidecar. Missing / malformed sidecar degrades silently
  via ``_load_library`` to the empty default
  ``{version: 1, updated_at: None, jobs: {}}``; a one-line
  ``[recap-ui] library skipped: ...`` log entry identifies the
  reason. Per-entry validation sanitizes title (string, ≤ 120
  chars, no control chars except tab), project (string, ≤ 80 chars,
  same control policy), and ``archived`` (strict bool). Empty
  strings clear a field; entries with no remaining fields are
  pruned on write. New public surfaces:
  - ``GET /api/library`` returns
    ``{version, updated_at, sidecar_path, sidecar_present,
    counts: {total, active, archived},
    projects: [{name, total, active, archived}]}``. Counts only
    cover jobs that exist on disk — orphaned library entries are
    ignored for rollups.
  - ``GET /api/jobs`` excludes archived jobs by default; pass
    ``?include_archived=1`` (accepts ``1``/``true``/``yes``) to
    surface them. The response now carries
    ``{jobs, include_archived}``.
  - Every ``/api/jobs`` and ``/api/jobs/<id>`` summary gains
    ``display_title`` (custom title → original_filename → job_id),
    ``custom_title`` (string or null), ``project`` (string or
    null), and ``archived`` (bool). ``urls.metadata`` points at
    ``/api/jobs/<id>/metadata`` and ``urls.library`` at
    ``/api/library``.
  - ``POST /api/jobs/<id>/metadata`` is the single mutation. Same
    safety primitives as the other overlay endpoints (Host
    pinning, ``X-Recap-Token`` CSRF, ``_API_POST_BODY_MAX`` body
    cap); validates only the allowlisted keys ``title``,
    ``project``, ``archived`` (any other keys are silently
    ignored); rejects wrong types with ``bad-value``, overlength
    strings with ``too-long``, control chars with ``bad-value``,
    and an empty request body with ``bad-schema``; returns the
    refreshed job summary on success. Log line records only the
    field names that changed; body + CSRF token are never logged.
  - ``scripts/verify_api.py`` grows by 17 cases (baseline empty
    library, default display_title fallback, missing CSRF,
    empty-body, bad title type, title too long, control-char
    project, bad archived type, no-such-job, happy-path title +
    project save + sidecar persistence, project rollup after
    save, archive + exclude-from-default, include_archived=1 opt-
    in + direct /api/jobs/<id> still reflects archive, counts-
    after-archive project rollup, unarchive + clear-project
    partial PATCH, clear-title-reverts-display + sidecar row
    pruned, malformed sidecar graceful) for 102 total.
- **Exporters honor transcript notes (slice 9b).**
  `recap assemble`, `recap export-html`, and `recap export-docx`
  now read `transcript_notes.json` at render time via the new
  `load_transcript_notes_overlay` + `resolve_transcript_row` +
  `transcript_row_id` helpers in
  `recap/stages/report_helpers.py`. The render pass walks the
  transcript's `utterances[]` (when present with valid speaker
  ids) or `segments[]` (faster-whisper fallback) and looks each row
  up by its stable id (`utt-<n>` / `seg-<n>`). A row with a
  `correction` renders the corrected text in place of the canonical
  line, followed by an `*(edited)*` / `(edited)` marker so
  downstream readers still see that the row was user-corrected; a
  row with a `note` emits a subordinate italic `Note: ...` block
  (Markdown: indented `_Note:_` bullet; HTML: styled
  `<p class="transcript-note">`; DOCX: italic indented paragraph).
  A correction-only row just rewrites the text; a note-only row
  keeps the canonical text and appends the note; an empty / missing
  item is a no-op. **Malformed-overlay policy:** missing file,
  invalid JSON, wrong top-level shape, bad per-item shape, bad key
  shape (`^(utt|seg)-\d+$`), overlength fields
  (correction > 2000 / note > 1000 chars), or non-printable control
  chars other than tab / newline / CR all degrade to "no overlay
  entry for that field" — the exporter falls back to canonical
  text and no `Note:` block. The overlay never mutates
  `transcript.json`; `scripts/verify_reports.py` statically checks
  the canonical transcript bytes are untouched after running all
  three exporters. The three `run()` functions now record
  `overlays.transcript_notes` in the `job.json#stages[...].extra`
  dict alongside the other overlay flags.
- **Exporters honor overlays (slice 9).** `recap assemble`,
  `recap export-html`, and `recap export-docx` now read
  `speaker_names.json`, `chapter_titles.json`, and
  `frame_review.json` at render time and apply them to
  `report.md` / `report.html` / `report.docx`. The canonical read
  helpers live in `recap/stages/report_helpers.py` as
  `load_speaker_names_overlay`, `load_chapter_titles_overlay`,
  `load_frame_review_overlay`, `resolve_chapter_title`,
  `resolve_speaker_label`, `apply_frame_review_to_chapter`, and
  `iter_transcript_utterances`. Overlay precedence:
  `chapter_titles.json > insights.json#chapters[].title > Chapter N`
  for chapter headings; `frame_review.json > selected_frames.json`
  for frame inclusion (`reject` suppresses, `keep` on a
  `vlm_rejected` frame promotes it to supporting sorted by
  `scene_index`, `keep` on a selected frame is a no-op);
  `speaker_names.json > Speaker N` when the transcript carries
  `utterances[]` with valid speaker ids. Segments-only transcripts
  (no utterances) continue to render the "Segments" section
  unchanged — the speaker overlay has no effect on that path, which
  preserves byte-compat for the faster-whisper fixture.
  **Malformed-overlay policy:** missing or malformed overlay JSON
  (invalid JSON, wrong top-level shape, per-entry bad shape) is
  treated as an empty overlay — no exception leaks to the caller,
  no behavior applies, and export output is byte-identical to the
  no-overlay baseline. The canonical coherence checks on
  `selected_frames.json` / `chapter_candidates.json` still run
  before the overlay is applied so a corrupted upstream artifact
  still fails loudly with the existing `... malformed: ...`
  prefixes. Exporters never mutate the upstream artifacts. The
  `run()` `extra` dict now carries an `overlays` sub-dict recording
  which overlays resolved to non-empty state for the run.
- `GET /api/jobs/<id>/transcript-notes` — read the per-row
  correction + note overlay. Returns
  `{version: 1, updated_at: string|null, items: {row-id: {correction?,
  note?}}}`. Falls back to the empty default when the file is absent
  or malformed, following the same read policy as the other
  overlays.
- `POST /api/jobs/<id>/transcript-notes` — update the overlay.
  Reuses Host pinning, `X-Recap-Token` CSRF, per-job lock, atomic
  `<file>.tmp` → `os.replace` write. Body shape
  `{"items": {"utt-0": {"correction": "...", "note": "..."}}}`.
  Row keys must match `^(utt|seg)-\d+$` — the same stable row-id
  convention the React workspace emits (`utt-<n>` for
  Deepgram-style utterances, `seg-<n>` for faster-whisper
  segments). Corrections are trimmed and bounded at 2000 chars;
  notes at 1000 chars. Both fields reject control characters other
  than tab / newline (line breaks are permitted because corrections
  are freeform text). Semantics: each POST merges into the existing
  overlay; sending `correction: ""` clears just that field; sending
  both fields empty drops the mapping entirely; sending only one
  field preserves the other. The endpoint uses a dedicated 64 KiB
  body cap rather than the default 8 KiB so batched saves remain
  feasible. Reasons drawn from
  `{host, content-type, content-length-missing, body-too-large,
  csrf, no-such-job, bad-json, bad-schema, bad-key-shape, bad-value,
  too-long, write-failed, lock}`. The upstream `transcript.json` is
  **never** mutated; the overlay lives at
  `jobs/<id>/transcript_notes.json` alongside the other review
  overlays. **Exporter integration is deferred** to a follow-up
  slice — today the overlay only drives the React transcript
  workspace; `recap assemble` / `export-html` / `export-docx` still
  render canonical transcript segments regardless of the overlay.
  `transcript_notes.json` is whitelisted as a raw artifact and
  served at `/job/<id>/transcript_notes.json`. The dashboard meta
  chip shows a "Transcript notes" marker when the artifact is
  present.
- `GET /api/jobs/<id>/frames` — merged visual-artifact view.
  Enumerates every image in `candidate_frames/` (the ground truth for
  what's reviewable) and enriches each with `frame_scores.json`
  (pHash / SSIM / OCR / text_novelty / duplicate_of),
  `scenes.json` (scene index + start/end timestamps),
  `selected_frames.json` (per-chapter `decision` /
  `shortlist_decision` / rank / composite_score / clip_similarity /
  reasons / verification / window_text / chapter_index), and the
  `frame_review.json` overlay (`review.decision` / `review.note`).
  Returns `{frames, chapters, sources, overlay}`. Always 200 with
  empty arrays when no upstream artifact is present. Malformed
  upstream artifacts log a single short reason and are skipped.
  Chapter context comes from the existing `_build_chapter_list`
  merger so `frame.chapter_index` can be resolved to a display title
  without a second round-trip.
- `GET /api/jobs/<id>/frame-review` — returns the overlay or the
  empty default. Mirrors the `speaker_names.json` /
  `chapter_titles.json` read policy.
- `POST /api/jobs/<id>/frame-review` — update the overlay. Reuses
  the speaker-names safety primitives (Host pinning,
  `X-Recap-Token` CSRF, `_API_POST_BODY_MAX` body cap, per-job lock,
  atomic `<file>.tmp` → `os.replace`). Body:
  `{"frames": {"scene-001.jpg": {"decision": "keep"|"reject"|"unset",
  "note": "..."}}}`. Keys must pass `is_safe_frame_file` **and**
  carry a whitelisted image extension (`.jpg` / `.jpeg` / `.png`).
  `decision="unset"` removes that mapping. Notes are trimmed and
  bounded at `_API_FRAME_REVIEW_NOTE_MAX_LEN = 300` chars; control
  chars (except tab) are rejected. Reasons drawn from
  `{host, content-type, content-length-missing, body-too-large,
  csrf, no-such-job, bad-json, bad-schema, bad-key-shape,
  bad-decision, bad-value, too-long, write-failed, lock}`. The
  overlay **never** mutates `selected_frames.json` or
  `frame_scores.json`; the files under `recap/stages/*` are not
  touched by this slice. Exporter integration (`recap assemble` /
  `export-html` / `export-docx` reading the review overlay) is a
  deferred follow-up — today the overlay only affects the React
  frame-review surface.
- `POST /api/jobs/<id>/runs/insights` — dispatch `recap insights`.
  Body: `{"provider": "mock" | "groq", "force": true | false}` (both
  keys optional; provider defaults to `mock`, force to `false`).
  Reuses Host pinning, `X-Recap-Token` CSRF, the 8 KiB body cap, the
  global `_run_slot` semaphore, and a per-job lock transferred into
  `_background_insights`. Runs the stage as a subprocess
  (`python -m recap insights --job <dir> --provider <p> [--force]`)
  so the UI module never imports `recap.stages.insights`. Groq
  requires `GROQ_API_KEY` in the server environment — the value is
  never logged, echoed, or written to `job.json`. On success returns
  `202 Accepted` with `{job_id, run_type, status_url, react_detail,
  started_at, provider, force}`. Validation errors return JSON
  `{"error": "...", "reason": "..."}` with reasons drawn from
  `{host, content-type, content-length-missing, body-too-large,
  csrf, no-such-job, bad-json, provider-invalid, groq-unavailable,
  force-invalid, slot, lock}`. A test-only
  `RECAP_API_STUB_RUN=1` env flag (opted into only by
  `scripts/verify_api.py`) short-circuits the subprocess and writes
  a canned success entry synchronously so CI never spawns the real
  provider call.
- `GET /api/jobs/<id>/runs/insights/last` — JSON status for the most
  recent insights run against this job.
  `{job_id, run_type, status: "no-run"|"in-progress"|"success"|
  "failure", started_at, finished_at, elapsed, exit_code, provider,
  force, stdout, stderr}`. Never generates; pure status readout.
- `POST /api/jobs/<id>/runs/rich-report` — dispatch the existing
  11-stage rich-report chain from the React surface. Reuses the
  legacy `_background_rich_report` worker and the
  `(job_id, "rich-report")` entry in `_last_run`, so a React-started
  chain and a legacy-HTML-started chain are indistinguishable from
  the status page's point of view. The body is ignored. Same safety
  primitives as the insights POST. `rich-report` is **not** added to
  `_RUNNABLE_STAGES` or `_LAST_RESULT_STAGES`. The test-only
  `RECAP_API_STUB_RUN=1` flag short-circuits the subprocess chain
  the same way the insights handler does.
- `GET /api/jobs/<id>/runs/rich-report/last` — JSON status for the
  most recent rich-report chain. Includes
  `{job_id, run_type, status, started_at, finished_at, elapsed,
  current_stage, failed_stage, stages: [{name, status, exit_code,
  stdout, stderr, elapsed}, ...]}`. Stages are ordered to match
  `_RICH_REPORT_STAGES` so the React panel can render chain progress
  without re-deriving the order.
- `POST /api/recordings` — accept a browser-recorded screen clip.
  Body is a raw `video/webm` or `video/mp4` upload (codec parameters
  are stripped); everything else returns 415 before the body is read.
  Content-Length is required and capped at 2 GiB
  (`_RECORDING_BODY_MAX`); the body is streamed to disk in 256 KiB
  chunks (`_RECORDING_CHUNK_BYTES`) and never held in memory, with a
  belt-and-braces running cap on bytes actually written. Host pinning
  and `X-Recap-Token` CSRF apply. The filename is **always** picked
  by the server — `recording-YYYYMMDDTHHMMSSZ-<hex>.<ext>` — so the
  browser-supplied filename (including any traversal attempt via
  Content-Disposition) is ignored entirely. Storage location is
  `<--sources-root>/<name>`, written as `<name>.tmp` and
  `os.replace`-d into place, so the recording immediately appears in
  `GET /api/sources` and can be started through `POST /api/jobs/start`
  with the existing `{"source": {"kind": "sources-root", "name":
  "..."}}` shape. On success returns `201 Created` with
  `{name, size_bytes, modified_at, content_type, source}`. Validation
  failures return JSON `{"error": "...", "reason": "..."}` with
  reasons drawn from
  `{host, content-type, content-length-missing, body-too-large,
  empty, csrf, no-sources-root, write-failed, short-body,
  replace-failed, name-invalid}`. Connection close is forced on
  rejects so a client that lied about `Content-Length` cannot keep
  the socket open. Request bodies, CSRF tokens, and the value of
  `DEEPGRAM_API_KEY` are never logged; only metadata
  (`name=<picked>`, `bytes=<size>`, `content_type=<ct>`) is logged
  on success.
- `GET /app/*` — serves `web/dist` assets when present, otherwise
  falls back to `web/dist/index.html` so React Router owns `/` (jobs
  index), `/job/<id>` (dashboard), and `/job/<id>/transcript`
  (transcript workspace).
- Anything else returns 404 with a tiny HTML error body.

Path safety: the jobs root is resolved once at startup; URLs with
any `..` path segment are rejected before resolution; resolved
static targets must still live under the jobs root; candidate
frame filenames must satisfy `Path(name).name == name` and carry
a whitelisted image extension. No directory listing is ever
emitted. Job IDs must map to a direct child of the jobs root.

The dashboard is no longer read-only: guarded POST surfaces exist for
exporter reruns, browser-started `recap run`, the rich-report chain,
and `POST /api/jobs/<id>/speaker-names`. They all preserve the
existing safety model: loopback Host pinning, CSRF, body-size caps,
per-job locks where mutation occurs, and no request bodies / tokens /
env vars in logs. The API speaker-name POST requires
`Content-Type: application/json`, `X-Recap-Token`, body <= 8192
bytes, top-level `{"speakers": {...}}`, numeric-string keys, string
values trimmed to <= 80 chars, and no control chars except tab.
It writes `speaker_names.json.tmp` and atomically replaces
`speaker_names.json`. The overlay never mutates `transcript.json`;
exporters still ignore it for now.

Rendering uses direct string construction with stdlib
`html.escape(..., quote=True)` on every content-bearing value, a
small inline `<style>` block for the legacy pages, and no external
dependencies in the Python server. The React app is a separate
`web/` package with React 18, Vite, TypeScript, and Vitest only:
no Tailwind, Zustand, Playwright, auth, remote binding, or exporter
integration in this slice. Cache-Control is `no-store` on dynamic
responses so reloads always reflect current disk state. `Ctrl-C`
calls `server.server_close()` and exits 0 cleanly.

The React surface currently has two pages, both wrapped in
`AppShell` which provides a sticky top bar with the product mark and
links to the legacy HTML dashboard and `/new`. The visual system
lives in `web/src/index.css` as a small set of CSS custom properties
(surfaces, ink, lines, brand, accent, status colors, elevation,
radii, typography scale, focus ring) plus a `prefers-reduced-motion`
block that zeroes out transitions and animations. No Tailwind and no
component library.

`/app/` is the jobs index. It fetches `GET /api/jobs` and renders a
hero section with the page title, a primary `New job` button, and a
stats row (total / completed / running / failed / pending). One
`JobCard` renders per job with a top status stripe, a status badge,
artifact chips that visibly distinguish ready vs. missing, created
and updated timestamps, and a primary action that opens the
transcript workspace plus optional ghost buttons for the legacy
detail page and the HTML report. A controls row below the hero
offers a search input (filename or job id) and a status pill row
(all / completed / running / failed / pending). Loading, error, "no
jobs yet", and "no matches" states are all rendered as full hero
cards; the "no matches" state offers a one-click reset of query +
status filter.

The transcript workspace lives at `/app/job/<id>/transcript`. It
fetches the job summary, transcript payload, and speaker-name
overlay from `/api/*`; renders native video from
`/job/<id>/analysis.mp4` in a sticky left rail; mirrors the legacy
active-row sync via `useActiveRow`; and renders speaker-colored rows
with a speaker legend. The legend's pills double as show/hide filter
chips — clicking a pill toggles its `aria-pressed` state and adds/
removes the speaker from a `hiddenSpeakers` set that filters the
rendered rows client-side. A "Show all" reset appears when any voice
is hidden. Renaming speakers still writes the `speaker_names.json`
overlay through `POST /api/jobs/<id>/speaker-names`.

The transcript card header carries a `TranscriptSearchBar` that
filters within the currently-visible rows. `lib/search.ts` computes
case-insensitive substring matches and produces a per-row split of
text/match segments; the table wraps each match in a `<mark>` with a
`data-match-index` attribute. A match-count display shows
`N / total` (or `0 matches`), prev/next buttons cycle through
matches, `Enter` / `Shift+Enter` are wired to the same cycle, and an
effect scrolls the active match into view. Active matches get a
stronger highlight; non-active matches use a softer accent tint. An
explicit empty state is shown when every speaker is hidden or when
the transcript has no rows.

The frontend fetch layer lazily calls `GET /api/csrf`, sends the
token in `X-Recap-Token` on save, and refreshes once on a 403 before
surfacing an error. The component test suite covers
`SpeakerRenameForm`, `SpeakerLegend` filter chips, `JobCard`,
`JobsIndexPage` (search + status filtering), `TranscriptSearchBar`
(match display, clear, disabled nav), `TranscriptTable` (highlight
rendering + empty states + toolbar slot), and the
`lib/search.ts` helpers. `scripts/verify_api.py` covers the API
contract against a scratch fixture and must remain green alongside
`scripts/verify_ui.py`.

The per-job detail page additionally renders two read-only sections
introduced in a follow-up slice. **Errors**, hoisted to the top of
the page between the `<h1>` header and the Metadata block, appears
only when one or more stages have `status == "failed"`; it emits a
`<ul class="errors">` with one line per failed stage in the
canonical pipeline order (`ingest`, `normalize`, `transcribe`,
`assemble`, `scenes`, `dedupe`, `window`, `similarity`, `chapters`,
`rank`, `shortlist`, `verify`, `export_html`, `export_docx`; unknown
stages appended alphabetically) showing the stage name and the
escaped error text. **Chapters & selected frames**, inserted between
the Stages table and the Artifacts list, appears only when both
`selected_frames.json` and `chapter_candidates.json` are present on
disk and validate through
`recap.stages.report_helpers.validate_selected_frames` and
`validate_chapter_candidates`; it emits one `<section
class="chapter-summary">` per chapter (sorted by `chapter_index`)
with a `<h3>` timestamp header, a whitespace-collapsed snippet of
the chapter body text truncated to 200 characters with a trailing
ellipsis, and an inline thumbnail row that renders only
`selected_hero` and `selected_supporting` frames (each thumbnail
links to the full-size candidate image via the existing
`/job/<id>/candidate_frames/<file>` route, with a small `hero` /
`supporting` label badge beneath). `vlm_rejected` frames are never
rendered. Frame filenames are rechecked with
`is_safe_frame_file` as defense in depth before any thumbnail URL is
emitted. When either artifact is missing the section is silently
omitted; when either artifact is malformed (invalid JSON or failing
validation) the UI writes a single
`[recap-ui] chapters section skipped: <error>` line to the server's
log stream, renders the rest of the page normally, and returns 200.
No new routes, no new dependencies, and the static-file whitelist is
unchanged. `scripts/verify_ui.py` now guards both new sections plus
the graceful-degradation path.

The per-job detail page also carries a POST-backed Actions block with
three HTML forms — `assemble`, `export-html`, `export-docx` — each of
which invokes `python -m recap <stage> --job <job_dir> --force` via
`subprocess.run` under a per-job `threading.Lock`. The allowed stage
set is the frozenset `_RUNNABLE_STAGES = {"assemble", "export-html",
"export-docx"}`; any other stage in a `/job/<id>/run/<stage>` path
returns 404 without spawning a subprocess. Every POST is validated in
order: `Host` header must match one of the server's
`allowed_hosts` via `secrets.compare_digest` (blocks DNS-rebinding
and forged `Origin` attacks; the allowed set is the bound
`host:port` plus its loopback aliases — so a browser typing
`localhost:8765` still reaches a server bound to `127.0.0.1:8765`
— but arbitrary hostnames are still rejected),
`Content-Length` must be present and within the 4096-byte
cap (returns 411 / 413), the form body's `_token` field must match a
`secrets.token_urlsafe(32)` token generated at server startup and
embedded in every rendered form (returns 403), the job directory must
pass the existing `_safe_job_dir` check, the stage must be in
`_RUNNABLE_STAGES`, and the per-job lock must be acquirable within
2 seconds (returns 429 with `Retry-After: 2`). Two POSTs to the same
job serialize; two POSTs to different jobs run in parallel. The
subprocess carries a 60 s timeout (kill on expiry, status="failure",
stderr="timeout after 60s"), and captured stdout/stderr are truncated
to 8192 UTF-8 bytes each with a trailing `…truncated (N bytes
omitted)` marker before being stored in the in-memory `_last_run`
cache. On success, the server responds with `303 See Other` and
`Location: /job/<id>/run/<stage>/last`, where a dedicated results
page renders the captured output, exit code, and status badge; an
`in-progress` status includes `<meta http-equiv="refresh" content="5">`.
Only a short rejection reason is logged on failed POSTs (`reason=host
|content-length-missing|body-too-large|body-parse|csrf|lock`); the
CSRF token, subprocess stdout/stderr, and full command line are never
logged. `scripts/verify_ui.py` grew to 31 checks covering the happy
path for assemble and export-html, the "no runs yet" empty state for
export-docx, missing/wrong token, forged Host header, oversize body,
unknown-stage allowlist, GET-on-POST-route, and raw-path traversal.

The dashboard additionally ships a browser-started video-processing
surface. `recap ui` now takes a `--sources-root` flag (default
`sample_videos`) and serves `GET /new`, which lists direct child
video files under that root (filtered by the whitelist `.mp4`,
`.mov`, `.mkv`, `.webm`, `.m4v`) plus a free-text path fallback.
Submitting the form POSTs to `/run`. The `/run` handler validates
`Host`, `Content-Length` (≤ 4096 bytes), `_token`, acquires the
module-level `_run_slot = threading.Semaphore(1)` non-blockingly
(429 + `Retry-After: 30` on contention), resolves the submitted path
under the resolved `sources_root` (`.relative_to()` check — outside →
403), requires `is_file()` (→ 400) and a whitelisted suffix (→ 400),
then runs `python -m recap ingest --source <path> --jobs-root
<jobs_root>` synchronously via `subprocess.run` with a 120 s timeout
and `capture_output=True`. On non-zero ingest exit, the slot is
released and the `/new` page is re-rendered with the captured stderr
as an inline error (400). On success, the handler parses the last
non-empty stdout line as the new job directory (this depends on
`cmd_ingest` in `recap/cli.py` printing `paths.root` — the only
coupling between the UI and the CLI's output format), derives the
job_id, re-validates via `_safe_job_dir`, writes an `in-progress`
entry to `_last_run[(job_id, "run")]`, spawns a daemon thread that
runs `python -m recap run --job <job_dir>` via `subprocess.Popen` +
`communicate(timeout=3600)`, transfers slot ownership to the thread,
and responds `303 See Other` with `Location: /job/<new_id>/`. The
thread captures stdout/stderr, truncates each to 8 KiB UTF-8 via the
existing `_truncate_output` helper, stores a final `success` or
`failure` entry in `_last_run`, and releases `_run_slot` in its
`finally` block. On subprocess timeout, the process is killed and
the result carries a failure marker with `timeout after 3600s`
appended to stderr. Rejected POSTs log one short reason (`host |
content-length-missing | body-too-large | body-parse | csrf | slot
| source-missing | source-invalid | source-outside-root |
source-not-file | source-bad-ext | ingest-timeout | ingest-spawn |
ingest-failed | ingest-no-root | ingest-unexpected-root`); the form
body, CSRF token, env, and captured command output are never
logged. The detail page renders a "Run in progress" banner + a
10-second HTML meta refresh whenever the top-level `status` or any
stage entry is `running`. The `run` stage name is added to a
read-only set `_LAST_RESULT_STAGES = _RUNNABLE_STAGES | {"run"}`
so `GET /job/<id>/run/run/last` renders via the existing
`render_run_last` helper; `_RUNNABLE_STAGES` itself is unchanged, so
there is no POST surface for `recap run` beyond `/run`. The
in-memory run-result cache does NOT survive a `recap ui` server
restart (documented limitation); the on-disk `job.json` state
updates written by each stage still do, so the detail page reflects
the last persisted stage status even if the live subprocess was
orphaned. `scripts/verify_ui.py` now seeds a scratch
`sources/fake.mp4` + `sources/bad.txt` and grew to 39 checks
covering the `/new` rendering, the `/new` link on the index, missing
/ wrong / forged token + host + body-size, missing source, source
outside the root, a bad-extension source, and the detail-page
running banner (via a `job.json` mutate-and-restore test). No full
`recap run` integration test lives in the verifier — that requires
faster-whisper weights and is covered manually.

The dashboard also ships a read-only transcript viewer at
`GET /job/<id>/transcript`. `render_transcript` reads the job's
`transcript.json` from disk and picks a data source: prefers
`utterances[]` when it is a non-empty list with at least one dict
entry carrying a valid `speaker` id (integer and not `bool`, or a
non-empty string) AND at least one non-empty `text.strip()`;
otherwise falls back to `segments[]`. Rows with empty text are
filtered out, matching the existing Markdown/HTML report behavior.
The utterances source renders a three-column table
`Time | Speaker | Text` with integer ids formatted as
`Speaker {id}`, string ids rendered as the escaped string, and
`null`/missing speakers rendered as `—` so rows stay aligned; the
segments fallback renders a two-column table with no Speaker
column. A metadata paragraph above the table surfaces engine,
model, language, row count, and (utterances only) the
distinct-speaker count. Missing `transcript.json` produces a 200
`No transcript available yet.` page; malformed JSON or a non-dict
top level produces a 200 page with an inline error banner
(`transcript.json could not be parsed.`) and a single
`[recap-ui] transcript skipped: <error>` line written to the
server's log stream — the rest of the dashboard keeps serving.
The detail page appends a `<p><a href="/job/<id>/transcript">View
transcript</a></p>` link only when `transcript.json` exists on
disk; the raw whitelisted `/job/<id>/transcript.json` artifact
route is unchanged. The viewer is strictly read-only: no
`<video>` element, no row-click handlers, no JS, no editing, no
diarization controls. Speaker labels remain sourced from
Deepgram-style `utterances[]` only; local WhisperX/pyannote is
deferred. `scripts/verify_ui.py` grew to 45 checks covering the
detail-page link, segments rendering, utterances rendering with
synthetic `Speaker 0` / `Speaker 1` / `2 speakers`, HTML escaping
of transcript text (`<script>` content is rendered as
`&lt;script&gt;`), the missing-file empty state, and the
malformed-file graceful path. All scratch mutations are restored
in `finally`.

The transcript page additionally renders an inline `<video
id="player" controls preload="metadata">` element above the table
when `analysis.mp4` exists in the job directory, and rewrites each
Time cell into `<button type="button" class="ts"
data-start="{float}"><code>HH:MM:SS</code></button>` with a ~10-line
inline `<script>` that wires clicks to set `player.currentTime =
parseFloat(el.dataset.start)` and auto-play if paused. The script
touches no other DOM state and makes no network call. When
`analysis.mp4` is absent (jobs mid-run, imports without normalize)
the `<video>`, buttons, and script are silently omitted and the
Time cells fall back to the previous plain `<code>` rendering —
the transcript stays usable as a plain table.

`analysis.mp4` is added to `_JOB_ROOT_FILES` and `.mp4 → video/mp4`
to `_CONTENT_TYPES`. A new `_send_ranged_file` handler helper is
invoked in the existing 3-segment static-file dispatch whenever
the resolved content type starts with `video/`. It implements
single-range HTTP Range support: accepts `Range: bytes=a-b`,
`bytes=a-`, and `bytes=-n` exclusively, ignores malformed,
empty, multi-range, or non-`bytes=` Range headers (falls through
to 200 full body per RFC tolerance), returns 416 with
`Content-Range: bytes */<size>` when a valid single-range is
unsatisfiable (start beyond EOF), and on valid range returns 206
with `Content-Range: bytes <a>-<b>/<size>`. Every video response
carries `Accept-Ranges: bytes` and `Cache-Control: no-store`. The
slice is streamed in 64 KiB chunks via `_stream_file`, which
seeks once then reads-and-writes in a loop; `BrokenPipeError` and
`ConnectionResetError` are caught silently (browsers routinely
abort partial range requests while scrubbing). The Range header
value is never logged. Only `analysis.mp4` is on the whitelist —
`original.*` and other media formats are explicitly not served.
`scripts/verify_ui.py` grew to 53 checks covering the
no-player-when-no-video baseline, the player+buttons+script when
`analysis.mp4` is present, full-body response headers, a byte
range `bytes=10-19`, prefix `bytes=0-`, suffix `bytes=-5`,
out-of-bounds `bytes=200-300` → 416, and a malformed `Range:
floop` → 200 fallback. All mutations live in the scratch job; a
pre-test assertion confirms `analysis.mp4` is absent before the
scratch bytes are written.

The dashboard also exposes a "Generate rich report" composite
action. `_RICH_REPORT_STAGES` is a tuple of 11
`(stage_name, extra_argv)` pairs covering the full chain
(`scenes`, `dedupe`, `window`, `similarity`, `chapters`, `rank`,
`shortlist`, `verify --provider mock`, `assemble --force`,
`export-html --force`, `export-docx --force`). `rich-report` is
deliberately **not** added to `_RUNNABLE_STAGES` or
`_LAST_RESULT_STAGES` — both the POST and the
`/last` GET are special-cased in `do_POST` and `do_GET` before
the single-stage per-stage routes so the semantics of the
frozensets stay "single-stage exporters" only.

`_handle_rich_report` runs the standard Host / Content-Length /
CSRF prelude, resolves `_safe_job_dir`, acquires the global
`_run_slot = threading.Semaphore(1)` (429 + `Retry-After: 30` on
contention with a `/run` or another rich-report), acquires the
per-job lock with the existing 2 s timeout (429 +
`Retry-After: 2` on contention with an exporter rerun), seeds an
in-progress entry under `_last_run[(job_id, "rich-report")]`,
spawns a daemon `_background_rich_report(job_id, job_dir,
job_lock)`, transfers both the slot and the lock to that thread,
and responds `303 See Other` with `Location:
/job/<id>/run/rich-report/last`. Ownership is explicit: the lock
is passed as an argument into the worker so there is no hidden
variable or lock leak; on the happy path the worker's `finally`
releases `job_lock` then `_run_slot`, and on any pre-spawn
failure the handler releases the lock and the slot before
returning. A single log line `[recap-ui] started rich-report
job=<id>` is emitted on spawn; argv, env, stdout and stderr are
never logged.

`_background_rich_report` invokes every stage via
`python -m recap <stage> --job <dir> [extra_args]` under
`subprocess.Popen`; it never imports or calls any
`recap.stages.* run()` function. `_FULL_RUN_TIMEOUT` (1 hour) is
a **hard total-chain ceiling**, not a per-stage floor. Before
each stage the worker computes `remaining = chain_deadline -
time.monotonic()`; if `remaining <= 0` the stage is recorded as
failed with a clear "chain budget … exhausted" stderr **without
spawning the subprocess**, the chain stops, and the remaining
stages stay `pending`. Otherwise `communicate(timeout=remaining)`
is passed to the subprocess so no single stage can run past the
deadline. Per-stage stdout / stderr are truncated to 8 KiB UTF-8 via
the existing `_truncate_output` helper and stored in the per-run
`stages[]` list, along with each stage's `status` / `exit_code` /
`elapsed`. On any non-zero exit or timeout the chain records the
`failed_stage`, sets overall `status = "failure"`, and breaks.
`assemble` / `export-html` / `export-docx` always run with
`--force`; the analytic stages rely on their own on-disk skip
contracts so re-clicking the button after a partial failure
short-circuits already-completed work.

`render_rich_report_last` emits four page states: no runs yet
(`No rich-report runs yet.` 200), in-progress (progress table
highlighting the running stage via `tr.active`, plus
`<meta http-equiv="refresh" content="5">`), success (elapsed
summary + link back to the job), and failure (progress table +
the failed stage's captured stderr in `<pre class="output">`).
Known limitation: the `_last_run` cache is in-memory only, so a
`recap ui` restart mid-chain loses the progress entry — on-disk
artifacts are unaffected and the button can be re-clicked.

`scripts/verify_ui.py` grew to 73 checks with five HTTP-surface
cases (`detail-has-rich-report-form-and-link`,
`rich-report-last-no-runs-yet`, `rich-report-unknown-job`,
`post-rich-report-missing-token`, `post-rich-report-forged-host`)
plus three in-process renderer cases that import `recap.ui`
directly and seed synthetic `_last_run` state to exercise
in-progress, success, and failure rendering without launching
the heavy chain (`rich-report-render-in-progress`,
`rich-report-render-success`, `rich-report-render-failure`),
plus one in-process budget-guard case
(`rich-report-respects-chain-budget`) that monkeypatches
`_FULL_RUN_TIMEOUT = 0.0`, invokes `_background_rich_report`
directly, and asserts the first stage is recorded as failed
without spawning a subprocess, later stages stay `pending`, and
both `_run_slot` and the per-job lock are released — proving
`_FULL_RUN_TIMEOUT` is enforced as a hard total-chain ceiling.
Actually running the 11-stage chain end-to-end remains a manual
integration test because it requires Tesseract and the OpenCLIP
weight download. Non-goals for this slice: no Gemini provider
(mock only), no stage-rerun expansion beyond the existing three
exporter buttons, no subprocess shim for CI, no cancel button,
no JS.

The `/new` form carries an engine selector. `_ENGINE_CHOICES =
{"faster-whisper", "deepgram"}` is the server-side allowlist; the
`<select name="engine">` renders both options, with the `deepgram`
option HTML-`disabled` when `os.environ.get("DEEPGRAM_API_KEY")` is
falsy at render time. A `<p class="secondary">` below the select
flags the availability state as text ("Deepgram available — …
detected" / "… Not detected"). The key value is never emitted, never
stored, never logged. On `POST /run`, after the existing source
validation and before `recap ingest` is spawned, the handler reads
`engine` from the form, defaults to `faster-whisper` when blank,
validates against `_ENGINE_CHOICES` (400 + `engine-invalid` log
reason on miss), and additionally requires `DEEPGRAM_API_KEY` in the
process environment when `engine == "deepgram"` (400 +
`deepgram-unavailable`). Both rejection paths release the global
`_run_slot` before returning and never spawn a subprocess. On the
happy path the engine is forwarded to `_background_run(job_id,
job_dir, engine)`, which appends `["--engine", engine]` to the
`recap run` argv. `subprocess.Popen` inherits the server's
environment (no `env=` override), so `DEEPGRAM_API_KEY` reaches the
transcribe stage without the UI touching its value. The successful
spawn log line widens to `[recap-ui] started recap run
job={id} engine={engine}`. Explicit non-goals: no API-key entry UI,
no env editor, no key storage in files, no per-engine model picker,
no WhisperX / pyannote / Groq, no network call from the verifier.
`scripts/verify_ui.py` extends `start_ui` with an optional `env=`
kwarg and in `main()` launches the test server with `DEEPGRAM_API_KEY`
stripped from a copy of `os.environ`, so the engine-validation tests
always run against a deterministic "key absent" state. Three new
cases cover the select + disabled-option rendering, the
`engine=whisperx` rejection, and the `engine=deepgram` rejection when
the key is absent; the UI check count is now 63. No happy-path
Deepgram case exists in the verifier — exercising the real engine
would need a live key and a network call.

Diarized transcripts additionally render speaker-colored rows and a
compact legend. When the data source is `utterances[]` and the
row's `speaker` id passes `_utterance_speaker_id_valid`, the first
time a speaker id is seen during iteration it is bound to the class
`speaker-{N % _SPEAKER_PALETTE_SIZE}` (where `_SPEAKER_PALETTE_SIZE
= 8`), and that class is emitted on the row's `<tr>`. The mapping is
stable within a single render (first-seen order) and survives the
segments-source fallback (it's never populated). A
`<p class="speakers-legend">` is emitted between the metadata
paragraph and the `<table>` when utterances mode is active and at
least one speaker class is assigned; each legend entry is a
`<span class="speaker-swatch speaker-N">` carrying the same label
that `_format_speaker` produces (integer → `Speaker {id}`, non-empty
string → escaped string). Eight pale background rules (`.speaker-0`
through `.speaker-7`) live in the inline `<style>` block **before**
`tr.active` so the active-row yellow still visibly overrides the
speaker tint during playback while the Speaker column text keeps
identifying who is speaking. The new CSS additions are purely
class-based so the same `.speaker-N` rule tints `<tr>` rows and the
`<span>` swatches alike. No JavaScript was added for this slice;
the existing `tr.active` sync script is unchanged. Segments-only
transcripts never emit `class="speaker-"` nor the legend, verified
by a dedicated negative case. Explicit non-goals: speaker rename /
editing UI, per-speaker filter, audio isolation, palette expansion
beyond 8, and any client-side script.
`scripts/verify_ui.py` grew to 60 checks with three additions —
`transcript-speaker-legend-with-utterances`,
`transcript-speaker-rows-with-utterances`, and
`transcript-no-speaker-classes-without-utterances`.

The transcript page additionally syncs with playback: each `<tr>`
is emitted with a `data-start="{float}"` attribute when the player
is present (no attribute in the no-video fallback), and the
existing inline `<script>` gains an ascending-sorted `rows`
index, a binary-search `findRow(t)` helper, and an `update()` that
toggles a `tr.active` CSS class on the row whose `start` is the
greatest value at or below `player.currentTime`. `update` is
registered on `timeupdate`, `seeking`, and `play`, and is called
once at script init so pages restoring a non-zero
`currentTime` get an immediate highlight. Newly-active rows are
scrolled via
`scrollIntoView({block:'nearest',behavior:'smooth'})`, gated by a
`lastUserScroll` timestamp: `wheel`, `touchmove`, and `scroll`
events on `window` (registered with `{passive:true,capture:true}`)
and the `ArrowUp`/`ArrowDown`/`PageUp`/`PageDown`/`Home`/`End`
keys set `lastUserScroll = Date.now()`, and auto-scroll only
fires when `Date.now() - lastUserScroll > 3000`. The `tr.active`
CSS uses both a soft background (`#fff7e0`) and a 3 px left
accent border (`#f5a623`) so the cue is not color-only. The
no-video fallback is strictly unchanged: no `<tr data-start>`,
no `button.ts`, no sync script. `scripts/verify_ui.py` grew to
57 checks with four additions: per-row `data-start` when video
is present, the `timeupdate` / `seeking` / `scrollIntoView`
registrations, the `tr.active { ... }` CSS rule, and a negative
assertion that the no-video fallback contains neither
`<tr data-start=` nor `scrollIntoView(`. Explicit non-goals for
this slice: speaker-coloured rows, chapter timeline, keyboard
shortcuts, ARIA live-region treatment, search/filter, transcript
editing.

Remaining UI items — browser file upload, cancelling a running
job, rerunning opt-in pipeline stages, deleting or archiving
jobs, persistent run history across server restarts, active-row
highlighting and auto-scroll while the video plays,
speaker-colored transcript rows, speaker-isolated audio, live
status streaming (SSE / WebSocket), auth, and remote access —
are explicitly deferred.

## Reliability: scenes stage handles Ctrl-C cleanly

`recap/stages/scenes.py` now catches `KeyboardInterrupt` separately
from the broader `except Exception`, because `KeyboardInterrupt`
inherits from `BaseException` and otherwise would propagate past
the `except Exception` block and leave `stages.scenes.status =
"running"` in `job.json`. The new handler:

- marks the stage `FAILED` with
  `error = "KeyboardInterrupt: interrupted by user"` via
  `update_stage(...)` so CLI/UI never show a stuck run;
- calls a small `_cleanup_partial_artifacts(paths)` helper that
  best-effort removes `candidate_frames/`, any `scenes.json.tmp`
  in-progress atomic write, **and** any pre-existing `scenes.json`
  — safe because the helper is only reached from inside the `run()`
  try-block (past the skip-check), at which point the caller has
  already committed to recomputing: either `--force` tore down the
  prior outputs upstream, or `_outputs_exist(paths)` returned False
  and treated the on-disk `scenes.json` as stale. The skip path
  never enters the handler, so a known-good completed
  `scenes.json` + `candidate_frames/` set is untouched;
- re-raises the `KeyboardInterrupt` so the CLI exits with the
  usual interrupt status.

Non-interrupt failures (`except Exception`) still go through the
existing path unchanged. `scripts/verify_reports.py` gained a
`check_scenes_interrupt_marks_failed` regression case (total 16
checks) that monkeypatches
`recap.stages.scenes._detect_and_extract` to raise
`KeyboardInterrupt` and asserts: `stages.scenes.status == "failed"`,
the error carries `KeyboardInterrupt`, `scenes.json` is absent,
`candidate_frames/` is cleaned up, and no `scenes.json.tmp` remains.
PySceneDetect itself is never invoked — the test is stdlib-only.

This slice is deliberately narrow: other long-running opt-in
stages (`dedupe`, `similarity`, `rank`, `shortlist`, `verify`) may
exhibit the same behavior on Ctrl-C but are left unchanged here.
Addressing them belongs in a follow-up reliability pass.

## Reliability: normalize hardening + MP4 fast path

`recap/stages/normalize.py` was rewritten end-to-end to address a real
production incident: a ~56-minute 4K MP4 got stuck with FFmpeg pinned
at 100% CPU, `analysis.mp4` never growing past a half-written tmp,
`job.json` frozen at `normalize=running`, and the partial output
unreadable ("moov atom not found"). The old code ran FFmpeg via
`subprocess.run(check=True, capture_output=True)` — no streaming, no
stall detection, no atomic tmp, no output validation — so a hung /
killed run could silently land a corrupt `analysis.mp4` at the final
path and poison every downstream stage. The new shape:

- **Atomic outputs.** Each of `metadata.json`, `analysis.mp4`, and
  `audio.wav` is produced at `<target>.tmp` first and promoted with
  `os.replace(tmp, target)` only after the FFmpeg subprocess exits
  cleanly **and** a shape-check `ffprobe` pass on the tmp confirms a
  readable video or pcm_s16le audio stream. A hung, killed, or
  otherwise failed run can never leave a bad file at the final path.
- **Fast path for compatible MP4.** A new pure helper
  `_decide_normalize_mode(probe)` inspects ffprobe JSON and returns
  `"remux"` when the container is MP4/MOV with H.264 + `yuv420p` video
  and AAC-or-absent audio; anything else — HEVC, VP9, `yuv444p`, Opus,
  WebM, malformed probe — falls back to `"reencode"`. The remux path
  runs `ffmpeg -c copy -map 0 -movflags +faststart` and finishes in
  seconds for an already-compatible 56-minute recording. The
  re-encode path keeps the existing `libx264 veryfast crf=23` + `aac
  128k` + `yuv420p` + `+faststart` profile. `audio.wav` is always
  extracted separately with the same 16 kHz mono `pcm_s16le` command
  as before.
- **Stall guard + wall-clock timeout.** A new `_run_ffmpeg_streaming`
  runs FFmpeg via `subprocess.Popen` with stdout→`/dev/null` and
  stderr drained by a background daemon thread into a bounded tail
  buffer. The main thread polls every 500 ms for `proc.poll()`, tmp
  file size growth, and last-stderr-line timestamp. When neither the
  tmp bytes nor FFmpeg's stderr has moved for `RECAP_NORMALIZE_STALL`
  seconds (default 90) the process is killed and the stage fails with
  `ffmpeg stalled: no output growth or stderr activity for Ns`. A
  hard wall-clock cap `RECAP_NORMALIZE_TIMEOUT` (default 7200s / 2h)
  fires `ffmpeg wall-clock timeout after Ns`.
- **Progress heartbeats.** Roughly every 2 seconds the runner calls
  `update_stage(paths, "normalize", RUNNING, extra=...)` with
  `command_mode` (`"remux"` or `"reencode"`), `elapsed_seconds`,
  `output_bytes`, `phase` (`"analysis"` / `"audio"` / `"probe"`),
  and — when ffprobe knew the input duration — `percent` +
  `input_duration_seconds`. `write_job()` bumps `updated_at`, so the
  React `/app/job/:id` dashboard shows motion on a long run instead
  of appearing frozen.
- **Clean failure.** A top-level `try/except` cascade unlinks every
  `*.tmp` on `NormalizeError`, `CalledProcessError`, or any other
  exception, marks the stage FAILED via `update_stage(..., error=...)`
  with a concise one-line message, and re-raises so the CLI exits
  non-zero. A retry starts from a clean slate with no stale `*.tmp`.
- **Env escapes:** `RECAP_NORMALIZE_TIMEOUT`, `RECAP_NORMALIZE_STALL`,
  and `RECAP_NORMALIZE_NO_FASTPATH=1` (force full re-encode even on a
  perfect input — debug escape).

Invariants explicitly preserved:

- `recap/job.py STAGES == ("ingest", "normalize", "transcribe",
  "assemble")` unchanged. A static pin in `scripts/verify_reports.py`
  rejects drift.
- `recap/cli.py cmd_run` composition unchanged. The same static pin
  confirms `cmd_run` calls `normalize.run` / `transcribe.run` /
  `assemble.run` and no opt-in stage.
- No new Python runtime deps; `recap/job.py` itself is untouched; no
  fixture bytes changed.

`scripts/verify_reports.py` grew from 60 → 64 checks with four new
regression cases:

- **`normalize-mode-decision`** — a pure-function matrix over MP4 /
  bare-mp4 / MOV containers, H.264 / HEVC codecs, `yuv420p` /
  `yuv444p` pixel formats, AAC / Opus / no-audio streams, zero-width
  video, WebM, and non-dict probes. Also flips
  `RECAP_NORMALIZE_NO_FASTPATH=1` and asserts a perfect input is
  forced back to `reencode`.
- **`normalize-failure-cleans-tmp`** — pre-seeds a scratch job dir
  with `original.mp4`, `metadata.json`, and `job.json`; monkey-patches
  `normalize._run_ffmpeg_streaming` to write a partial tmp and raise
  `NormalizeError("ffmpeg stalled: ...")`; asserts the run re-raises,
  `stages.normalize.status == "failed"` with "stalled" in the error,
  `analysis.mp4` was never promoted, and
  `analysis.mp4.tmp` / `audio.wav.tmp` / `metadata.json.tmp` are all
  gone.
- **`normalize-invalid-output-not-promoted`** — monkey-patches the
  runner to exit cleanly with garbage in the tmp, then
  monkey-patches `_validate_analysis` to reject; asserts the stage
  ends FAILED with a "validation" error, `analysis.mp4` is not
  promoted, and the tmp is unlinked.
- **`normalize-stages-and-cmd-run-unchanged`** — static pin that
  `recap.job.STAGES == ("ingest", "normalize", "transcribe",
  "assemble")` and that `cmd_run` in `recap/cli.py` calls
  `normalize.run`, `transcribe.run`, `assemble.run` and no opt-in
  stage (`scenes.run`, `dedupe.run`, ..., `insights.run`).

FFmpeg itself is never invoked by the verifier — every failure path
is simulated by function-level monkey patches so CI has no media
dependency and no wall-clock exposure.

## UX: screenshot-audit pass (2026-04-21 follow-up)

After the premium redesign pass shipped, a screenshot-driven
audit surfaced five concrete problems that theory had missed.
Playwright captured every React route (`/app/`, `/app/new`,
`/app/job/:id`, `/app/job/:id/transcript`,
`/app/job/:id/frames`) at 1440 × 900 and 390 × 844 against a
real completed job; the before screenshots live at
`/tmp/recap_ui_audit/before/`. The commit *Refine React UI from
screenshot audit* landed targeted fixes, one per finding:

1. **`StageTimeline` rewrite.** The right rail on the detail
   page had been rendering every stage's full `extras`
   dictionary as a visible `<dl>` — artifacts, `command_mode`,
   `elapsed_seconds`, `output_bytes`, `percent`, `phase`,
   engine, model, segments — on a rich-report job this meant
   50 – 80 admin-console rows dominating the dashboard. Fixed
   by rendering name + status chip + finish time as the default
   row; the extras `<dl>` now lives behind a per-stage
   `Details N ▾` disclosure, and the card heading shows a
   compact `N / M done · F failed` counter.
2. **`JobCard` readiness dots.** The readiness sentence
   (`Report ready · Insights · Screenshots · Renamed
   speakers`) was redundant with the existing chips. Replaced
   with three pill dots `T / R / I` (Transcript / Report /
   Insights, green fill when ready, outlined when pending); the
   wrapper carries an `aria-label` naming every slot's state,
   and a visually-hidden paragraph repeats the state sentence
   so nothing is color-only. The library grid also stepped up
   to `minmax(440 px, 1fr)` so cards breathe instead of feeling
   chunky at three-across.
3. **Detail-hero hierarchy.** The primary action strip had been
   a mix of a primary button, a ghost button, a chip group, and
   a text link — no hierarchy. Now `Open transcript workspace`
   and `Review screenshots` are the only items on the primary
   strip; report links dropped to a dedicated
   `Downloads HTML · Markdown · DOCX` row below; `Legacy detail
   page` moved into the meta-actions row alongside Rename /
   Archive so the primary CTA finally stands alone.
4. **`ChapterSidebar` nav-first.** The sidebar had been
   rendering per-chapter summary / bullets / action_items
   inline, so the rail read as documentation. Now summary /
   bullets / action_items sit behind an `Outline ▾`
   disclosure; titles + timestamps + rename button stay
   visible as the nav list. The editorial body lives in the
   Insights preview on the detail page.
5. **`FrameCard` CSS polish.** The fieldset scaffold
   (three radios + note textarea) was overwhelming the image
   on first paint. DOM structure stayed put (tests still
   match `getByLabelText("Keep")`, `getByLabelText("Reject")`,
   placeholder `/why keep or reject/i`); CSS restyles the
   radios as a compact segmented pill and forces the image to
   16 : 9 so the gallery feels uniform.

Plus one secondary fix: `.source-root-chip` dropped its
`max-width: 60%` cap so long absolute paths wrap cleanly on
`/app/new`.

All fixes landed with one small scoped CSS block reusing existing
tokens — no new palette, shadow, or elevation tokens — plus four
targeted JSX tweaks in `StageTimeline.tsx`, `JobCard.tsx`,
`JobDetailPage.tsx`, `ChapterSidebar.tsx`. After screenshots live
at `/tmp/recap_ui_audit/after/`. The 79-spec Vitest suite stays
green; `recap/job.py STAGES` and `recap/cli.py cmd_run`
composition unchanged; no new runtime deps.

## UX: premium React redesign pass (2026-04-21)

After the normalize hardening landed, the React product was
polished in a frontend-only pass whose ask was "it still looks
utility, make it feel premium". The pass is intentionally layered
on top of the previous visual system rather than a rewrite: every
component class name still resolves; `web/src/index.css` gains a
cohesive token-override block at the end plus a small set of new
component rules; the pages make surgical JSX edits for hierarchy,
not structural rewrites. No API or backend changes.

Concrete before/after:

- **Palette and elevation.** Warm off-white canvas softened
  (`--surface-0` → `#f8f4ec`); body background collapsed to a
  single linear wash instead of three radial overlays; shadow
  tokens halved in weight; radii tightened one step; pills stay
  pills. Focus ring promoted to a brand-tinted 3 px ring applied
  globally via `:focus-visible`.
- **Brand mark.** Lost its linear-gradient + shadow; now a flat
  brand-colored square with the wordmark beside it. The "local-
  first video docs" tagline is a quiet secondary label, not a
  competing headline.
- **Library hero (`/app/`).** Dropped the Total / Active / Archived
  stats grid — the same counts already live in the Active /
  Archived tabs and the "Showing N of M" subtitle. Hero is now
  eyebrow + `Recordings & reports` H1 + subline + single primary
  `New recording` CTA.
- **Job card.** Status now rendered as both a status chip (word
  never color-only) **and** a 3 px left-edge accent stripe on the
  card. Metadata chips went flat / neutral; the primary
  `Open job dashboard` button is the only filled element;
  `Transcript`, `Edit`, `Archive` are text-link affordances in a
  dashed-border action strip.
- **New job (`/app/new`).** Source-mode switcher collapsed into a
  single segmented pill (`Sources root` / `Record screen` /
  `Absolute path`) instead of three full-width tabs. "What happens
  next" moved behind a `<details>` so the launch action is always
  visible. The `Start job` primary button stands alone on the
  launch card; `Cancel` / `Use legacy /new` demoted to text links.
- **Detail page (`/app/job/:id`).** Hero split into two rows: a
  primary action strip (`Open transcript workspace`,
  `Review screenshots`, report chip group, `Legacy detail page`)
  and a quieter organize strip (`Rename / Project`, `Archive`).
  Reports are no longer scattered text links — they render as a
  single labeled chip group (`Report: HTML · Markdown · DOCX`).
  Artifacts-on-disk grid moved behind a `<details>` disclosure
  below run-actions / insights / chapters.
- **Transcript workspace (`/app/job/:id/transcript`).** Header
  dropped the ghost `← Dashboard` button for a quiet `← Back to
  dashboard` text link, and renders engine / model / language /
  duration as a row of flat neutral chips instead of a run-on
  meta sentence.
- **Frame review (`/app/job/:id/frames`).** Header totals render as
  chips (`N candidates`, `N shortlist`, `N selected`,
  `N reviewed`) and the nav becomes a pair of quiet text links.
  Frame cards keep the chapter-grouped editorial layout from the
  previous slice and add a subtle green / red border cue for
  `keep` / `reject` decisions (status word still in the chip).
- **Responsive.** `@media (max-width: 960px)` collapses the detail
  grid, workspace grid, and new-job grid to a single column and
  un-sticks the rails; `@media (max-width: 640px)` stacks every
  action strip so the primary button is always full width. No page
  scrolls horizontally on laptop or mobile widths.

Invariants explicitly preserved:

- `recap/job.py STAGES` and `recap/cli.py cmd_run` composition
  unchanged (not touched by this slice).
- No Python or npm runtime deps added.
- Every Vitest expectation (79 specs / 17 files) stays green —
  critical button text and chip content (`Open job dashboard`,
  `Transcript`, `Save review (n)`, `Legacy detail page`,
  `Engine · deepgram`, `42 segments`, status radio labels) were
  all retained.
- Legacy HTML routes unchanged.

Inspiration map: [docs/ux_inspiration.md](docs/ux_inspiration.md)
gains a "Patterns borrowed in the 2026-04-21 premium redesign
pass" section naming Cap5, CapSoftware/Cap, steipete/summarize,
Tabler, Nord, and ui-ux-pro-max as the sources for each change.

## Hardening: offline golden-path validation script

`scripts/verify_reports.py` is a small stdlib+`python-docx` script
that exercises `recap assemble`, `recap export-html`, and
`recap export-docx` against a tiny committed fixture under
`scripts/fixtures/minimal_job/` (job.json, metadata.json,
transcript.json, chapter_candidates.json, selected_frames.json, and
three ~600-byte JPEGs). It runs each exporter through the
selected-frames path (asserting heading structure, image link
presence for the selected hero + supporting frames, absence of
rejected frames, `python-docx` inline-shape count) and the
absent-selected path (no `## Chapters` / `<h2>Chapters</h2>` /
`Chapters` heading; zero DOCX inline shapes), then runs a small
set of negative cases — malformed `selected_frames.json`
(`start_seconds = "bad"`), traversal `frame_file = "../report.md"`,
and a removed referenced candidate image — to confirm each command
exits `2` with a clean one-line `error: ...` and leaves no
`report.{md,html,docx}.tmp` file on disk. No network, no model
downloads, no API keys. Runtime is roughly one second on a modern
laptop. The committed fixture is never mutated; every case runs
in a fresh temp copy. This script is the pre-release guard for the
three exporter slices; running it from a clean checkout confirms
the Markdown/HTML/DOCX surface still matches the contract.

A second stdlib-only script, `scripts/verify_ui.py`, smoke-validates
the read-only `recap ui` dashboard. It copies the same fixture into
a temp jobs root, picks a free localhost port, spawns
`recap ui` as a subprocess, waits for `/` to respond, and uses
stdlib `http.client` to issue raw, unnormalized HTTP paths. It
checks the jobs index, the per-job detail page (asserting stage
rows for ingest / normalize / transcribe / assemble), the
whitelisted JSON artifacts (job.json / metadata.json /
transcript.json with `application/json` content type and
parseable bodies), a candidate-frame JPEG (with JPEG magic-byte
verification), plus 404 responses for an unnormalized
`../../etc/passwd` traversal (no passwd content leak), a
non-whitelisted `report.html.tmp` filename, and an unknown route
`/nope`. It then runs `recap assemble` / `export-html` /
`export-docx` against the scratch copy and re-checks that the
detail page links report.md/report.html/report.docx, that
`report.html` and `report.docx` serve with the correct content
type, and that the `candidate_frames/<file>.jpg` references inside
`report.html` resolve to valid JPEGs through the same server. The
UI server process is terminated in a `finally` block via SIGINT
(falling back to SIGKILL on timeout) and the scratch tree is
removed. Runtime is about half a second. This is the pre-release
guard for the dashboard's routing, path safety, and artifact
serving.

## Hardening: shared report helpers

`recap/stages/report_helpers.py` is the canonical home for the small
validators and formatters used by the three report stages. It exports
`format_ts`, `summarize_metadata`, `collapse_whitespace`, `is_int`,
`is_number`, `is_safe_frame_file`, `validate_selected_frames`,
`validate_chapter_candidates`, `caption_for`, `check_hero_coherence`,
and `check_supporting_coherence`. `recap/stages/assemble.py`,
`recap/stages/export_html.py`, and `recap/stages/export_docx.py`
import these names (aliased with a leading underscore locally so the
existing render-site call sites did not need to change), so a future
fix to the selected-path validation contract lands in one file instead
of three. The refactor was verified to be behavior-preserving by
diffing the no-selected Markdown output and the selected Markdown and
HTML outputs against pre-refactor baselines; both
`scripts/verify_reports.py` and `scripts/verify_ui.py` remain green.
This module is deliberately a flat set of functions and constants —
not an export framework, not a plugin registry, not a stage
abstraction. Error-message prefixes (`selected_frames.json malformed:
…`, `chapter_candidates.json malformed: …`, `chapter_candidates.json
has no chapter with index … required by selected_frames.json`,
`missing candidate frame: candidate_frames/…`, `plain filename inside
candidate_frames/`) are load bearing because `scripts/verify_reports.py`
matches on them and must not change without updating the script in
lockstep.

## Running Phase 1 locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt

# full pipeline on a new job
.venv/bin/python -m recap run --source path/to/recording.mp4 --model small

# per-stage / resume
.venv/bin/python -m recap ingest     --source recording.mp4
.venv/bin/python -m recap normalize  --job jobs/<job_id>
.venv/bin/python -m recap transcribe --job jobs/<job_id> --model small
.venv/bin/python -m recap scenes     --job jobs/<job_id>
.venv/bin/python -m recap dedupe     --job jobs/<job_id>
.venv/bin/python -m recap window     --job jobs/<job_id>
.venv/bin/python -m recap similarity --job jobs/<job_id>
.venv/bin/python -m recap chapters   --job jobs/<job_id>
.venv/bin/python -m recap rank       --job jobs/<job_id>
.venv/bin/python -m recap shortlist  --job jobs/<job_id>
.venv/bin/python -m recap verify     --job jobs/<job_id> [--provider {mock,gemini}]
.venv/bin/python -m recap assemble   --job jobs/<job_id>
.venv/bin/python -m recap status     --job jobs/<job_id>
```

CLI flags that apply to most subcommands: `--job <path>` to target an
existing job directory, `--jobs-root <path>` to change where new jobs are
created (default `./jobs`), `--force` to recompute a stage even when its
artifacts already exist. `recap run` and `recap transcribe` also accept
`--model` (default `small`).

Unexpected misuse (missing source, missing `ffmpeg`/`ffprobe`, re-ingest
with a different source without `--force`) prints a one-line
`error: ...` message to stderr and exits with code 2 instead of a Python
traceback.

Local sample recordings for development and validation runs live in
`sample_videos/`. They are fixtures only — the pipeline does not read the
directory itself, it reads whatever path you pass via `--source`. A full
Phase 1 run against a sample:

```bash
.venv/bin/python -m recap run \
  --source "sample_videos/Cap Upload - 24 February 2026.mp4" \
  --model small
```

## Dependencies and environment assumptions

- **Python**: 3.10, 3.11, 3.12, or 3.13. Python 3.14 is not supported
  because `faster-whisper`'s `ctranslate2` dependency has no 3.14 wheels
  yet and source builds typically fail. The README recommends 3.12.
- **System binaries**: both `ffmpeg` and `ffprobe` must be on `PATH`
  (`brew install ffmpeg` on macOS, `apt-get install ffmpeg` on
  Debian/Ubuntu). `recap dedupe` additionally requires `tesseract`
  (`brew install tesseract` on macOS, `apt-get install tesseract-ocr`
  on Debian/Ubuntu). The stages resolve these via `shutil.which` and
  raise a clear install hint if any is missing.
- **Python packages**: `faster-whisper>=1.0.3`,
  `scenedetect[opencv]>=0.6.4`, `ImageHash>=4.3.1`, `Pillow>=10.0.0`,
  `scikit-image>=0.22`, `pytesseract>=0.3.10`, `open_clip_torch>=2.24`,
  and `torch>=2.1` (all pinned in `requirements.txt` and
  `pyproject.toml`). First transcription downloads the requested
  Whisper model (default `small`) from the internet; subsequent runs
  use the local cache. PySceneDetect ships its own opencv-python wheel
  via the `[opencv]` extra and runs entirely offline. ImageHash pulls
  in Pillow, NumPy, SciPy, and PyWavelets; scikit-image pulls in
  imageio, tifffile, networkx, and lazy-loader; pytesseract is a thin
  wrapper around the system `tesseract` binary. `open_clip_torch` +
  `torch` are required only for `recap similarity`; on its first run
  the stage downloads the OpenCLIP `ViT-B-32` OpenAI weights
  (~350 MB) into the local cache and subsequent runs are offline. All
  run locally.
- **Compute**: the stage instantiates `WhisperModel(model, device="cpu",
  compute_type="int8")`. No GPU configuration is wired up.

## Artifacts produced per job

Every successful Phase 1 job produces the following files inside its job
directory:

- `original.<ext>` — the ingested source file (extension preserved).
- `job.json` — job identity (`job_id`, `source_path`,
  `original_filename`, `created_at`), per-stage status
  (`pending`/`running`/`completed`/`failed` with `started_at`,
  `finished_at`, and `error` when applicable), and a rolled-up top-level
  `status` and `error`. The top-level rollup is driven only by the four
  Phase 1 stages (`ingest`, `normalize`, `transcribe`, `assemble`) so a
  Phase-1-only `recap run` reaches `completed`.
- `metadata.json` — raw `ffprobe -show_format -show_streams` JSON of the
  original.
- `analysis.mp4` — normalized H.264 + AAC video.
- `audio.wav` — 16 kHz mono PCM `s16le`.
- `transcript.json` — normalized transcript (shape below).
- `transcript.srt` — SubRip captions generated from the same segments.
- `report.md` — basic Markdown report built from `job.json`,
  `metadata.json`, and `transcript.json`. `report.md` does not yet
  embed scene data.

Running `recap scenes --job <path>` adds the Stage 5 outputs:

- `scenes.json` — `video`, `detector`, `threshold`, `fallback`,
  `scene_count`, `frames_dir`, and a `scenes` list. Each scene entry
  has `index` (1-based), `start_seconds`, `end_seconds`, `start_frame`,
  `end_frame`, `midpoint_seconds`, and `frame_file`.
- `candidate_frames/scene-NNN.jpg` — one representative JPEG per scene.

Running `recap window --job <path>` adds the first Phase 3 slice
output:

- `frame_windows.json` — top-level `video`, `transcript_source`,
  `scenes_source`, `window_seconds` (`6.0`), `frame_count`,
  `frames_with_text_count`, and a `frames` list with one entry per
  scene: `scene_index`, `frame_file`, `midpoint_seconds`,
  `window_start` (`max(0.0, midpoint_seconds - window_seconds)`),
  `window_end` (`midpoint_seconds + window_seconds`, clamped to
  `transcript.duration` when present), `segment_ids` (ordered list of
  transcript segment ids that overlap the window), and `window_text`
  (whitespace-normalized concatenation of the overlapping segments'
  text joined with single spaces).

Running `recap similarity --job <path>` adds the second Phase 3 slice
output:

- `frame_similarities.json` — top-level `video`, `frames_dir`
  (`candidate_frames`), `windows_source` (`frame_windows.json`),
  `scenes_source` (`scenes.json`), `model` (`ViT-B-32`), `pretrained`
  (`openai`), `device` (`cpu`), `image_preprocess`
  (`open_clip.default`), `frame_count`,
  `frames_with_window_text_count`, `frames_scored_count`, and a
  `frames` list with one entry per scene: `scene_index`, `frame_file`,
  `midpoint_seconds`, `window_start`, `window_end`, `window_text`,
  `has_window_text` (bool), and `clip_similarity` (plain Python
  float in `[-1.0, 1.0]` when `has_window_text` is true; `null`
  otherwise).

Running `recap chapters --job <path>` adds the chaptering slice
output:

- `chapter_candidates.json` — top-level `video`,
  `transcript_source` (`transcript.json`), `source_signal` ∈
  {`"pauses"`, `"pauses+speakers"`, `"pauses+scenes"`,
  `"pauses+speakers+scenes"`}, `pause_seconds` (`2.0`),
  `min_chapter_seconds` (`30.0`), `chapter_count`, and a
  `chapters` list with one entry per chapter: `index` (1-based),
  `start_seconds` (`0.0` for the first chapter, else the first
  contained segment's `start`), `end_seconds`
  (`transcript.duration` for the last chapter, else the next
  chapter's `start_seconds` — i.e., the pause gap between a
  chapter and its successor is counted as part of the earlier
  chapter, so the emitted timeline is contiguous:
  `chapters[i].end_seconds == chapters[i+1].start_seconds` for
  every adjacent pair, the first chapter's `start_seconds` is
  `0.0`, and the last chapter's `end_seconds` is
  `transcript.duration`), `first_segment_id`, `last_segment_id`,
  `segment_ids` (ordered list of contained transcript segment ids,
  covering every transcript segment exactly once), `text`
  (whitespace-normalized concatenation of the contained segments'
  text joined with single spaces), and `trigger` ∈ {`"start"` for
  the first chapter; `"pause"`, `"speaker"`, `"scene"`,
  `"pause+speaker"`, `"pause+scene"`, `"speaker+scene"`, or
  `"pause+speaker+scene"` for any chapter created by a boundary —
  multi-signal triggers are always joined in the fixed order
  pause, speaker, scene}. In speaker-aware mode
  (`source_signal` contains `"speakers"`), the top-level also
  includes `speaker_change_count`, an integer count of pre-merge
  boundaries whose source included a speaker change. In
  scenes-aware mode (`source_signal` contains `"scenes"`), the
  top-level also includes `scenes_source` (the basename of the
  scenes artifact, `scenes.json`) and `scene_change_count`, an
  integer count of pre-merge boundaries whose source included a
  scene change (counting adjacent segment pairs on which the scene
  signal fired, not raw scene rows — multiple scene cuts mapping
  to the same segment id count once). Both counts are deliberately
  pre-merge, so they record the raw signal even after short
  speaker-only or scene-only groups have been merged away by the
  `MIN_CHAPTER_SECONDS` merge. On faster-whisper transcripts
  without a usable `scenes.json` the artifact is byte-identical to
  the pre-scene-fusion (pause-only) version of this stage:
  `source_signal = "pauses"`, trigger vocabulary
  `{"start", "pause"}`, no `speaker_change_count`, no
  `scenes_source`, no `scene_change_count`.

Running `recap rank --job <path>` adds the per-chapter ranking
fusion output:

- `frame_ranks.json` — top-level `video`, `scenes_source`
  (`scenes.json`), `chapters_source` (`chapter_candidates.json`),
  `scores_source` (`frame_scores.json`), `windows_source`
  (`frame_windows.json`), `similarities_source`
  (`frame_similarities.json`), `weights` (dict with
  `clip_similarity`, `text_novelty`, `duplicate_penalty`),
  `missing_similarity_value` (`0.0`), `missing_novelty_value`
  (`0.0`), `source_signals` (`phash+ssim+ocr+clip`),
  `input_fingerprints` (dict mapping each input artifact filename
  to its SHA-256 hex digest over canonical JSON — used by the skip
  contract so drift in any of the five input artifacts triggers a
  recompute), `chapter_count`, `frame_count`, and a `chapters` list
  with one
  entry per chapter: `chapter_index` (1-based), `start_seconds`,
  `end_seconds`, `frame_count`, and a `frames` list sorted by
  composite score descending (tie-break on `scene_index`
  ascending). Each frame entry has `rank` (1-based per chapter),
  `scene_index`, `frame_file`, `midpoint_seconds`,
  `clip_similarity` (original value, possibly null),
  `text_novelty` (original value, possibly null), `duplicate_of`
  (original value, possibly null), and `composite_score` (plain
  Python float).

Running `recap shortlist --job <path>` adds the keep/reject
pre-VLM shortlist output:

- `frame_shortlist.json` — top-level `video`, `ranks_source`
  (`frame_ranks.json`), `thresholds` (dict with
  `clip_keep_threshold` `0.30` and `ocr_novelty_threshold`
  `0.25`), `budget` (dict with `hero_per_chapter` `1`,
  `supporting_per_chapter` `2`, `total_per_chapter` `3`),
  `policy_version` (`keep_reject_v1`), `input_fingerprints` (dict
  with one entry keyed `frame_ranks.json`, value is a 64-char
  SHA-256 hex digest over canonical JSON), `chapter_count`,
  `frame_count` (all input frames), `kept_count` (hero +
  supporting), `rejected_count` (rejected_duplicate +
  rejected_weak_signal), `dropped_over_budget_count`, and a
  `chapters` list with one entry per chapter:
  `chapter_index` (1-based), `start_seconds`, `end_seconds`,
  `frame_count`, `kept_count`, `hero_scene_index` (int or null),
  `supporting_scene_indices` (list of ints, possibly empty), and
  a `frames` list emitted in rank-ascending order (same order as
  `frame_ranks.json`). Each frame entry has `rank`, `scene_index`,
  `frame_file`, `midpoint_seconds`, `composite_score`,
  `clip_similarity` (original, possibly null), `text_novelty`
  (original, possibly null), `duplicate_of` (original, possibly
  null), `decision` (one of `hero`, `supporting`,
  `rejected_duplicate`, `rejected_weak_signal`,
  `dropped_over_budget`), and `reasons` (ordered list drawn from
  the closed vocabulary `duplicate_of_predecessor`,
  `clip_similarity_below_threshold`,
  `text_novelty_below_threshold`, `kept_as_hero`,
  `kept_as_supporting`, `exceeds_total_per_chapter`).
  `selected_frames.json` is **not** written by this stage; it is
  reserved for Phase 4 post-VLM finalists.

Running `recap dedupe --job <path>` adds the pHash + SSIM + OCR slice
output:

- `frame_scores.json` — top-level `video`, `scenes_source`,
  `frames_dir`, `metric` (`phash+ssim+ocr`), `hash_size`,
  `duplicate_threshold`, `ssim_distance_band_max`,
  `ssim_duplicate_threshold`, `ocr_engine` (`tesseract`),
  `frame_count`, `duplicate_count`, `ssim_computed_count`,
  `ocr_frames_with_text_count`, and a `frames` list with one entry per
  scene: `scene_index`, `frame_file`, `phash`,
  `hamming_distance` (null for the first frame, integer otherwise),
  `ssim` (float when SSIM was computed for that pair, else null),
  `ocr_text` (whitespace-normalized string, possibly `""`),
  `text_novelty` (null for the first frame, else
  `1.0 - difflib.SequenceMatcher(None, prev_text, curr_text).ratio()`),
  and `duplicate_of` (predecessor `scene_index` when `hamming_distance`
  is at or below the pHash threshold, or when `ssim` reaches
  `ssim_duplicate_threshold`; else null). OCR does not influence
  `duplicate_of`.

The `stages.scenes`, `stages.dedupe`, `stages.window`,
`stages.similarity`, `stages.chapters`, `stages.rank`, and
`stages.shortlist` entries on `job.json`
appear the first time each stage runs (they are intentionally not
pre-populated for new jobs, so the rollup is not held back by unmet
Phase 2 or Phase 3 obligations).

Job directories are created under `./jobs/` by default (the directory is
in `.gitignore`). Job IDs have the form `YYYYMMDD-HHMMSS-<8hex>`.

`report.md` deliberately does not claim chapters, screenshots, or VLM
verification. It contains only a media summary and a timestamped list of
transcript segments — whatever is actually on disk.

## Restart and resume behavior

- Each stage checks for its own outputs before running. If the expected
  artifacts exist and `--force` is not set, the stage short-circuits and
  marks itself `completed` (with `skipped: true` where relevant). Re-running
  `recap run --job <existing>` against a fully-completed job finishes in
  well under a second.
- `--force` recomputes the target stage. For `normalize`, each sub-output
  (`metadata.json`, `analysis.mp4`, `audio.wav`) is checked individually.
- **Ingest safety.** If `recap ingest` is invoked against an existing job
  with a `--source` path different from the one recorded in `job.json`, it
  refuses and exits 2 with a message naming both sources. Re-running with
  `--force` replaces the original and invalidates the downstream artifacts
  (`metadata.json`, `analysis.mp4`, `audio.wav`, `transcript.json`,
  `transcript.srt`, `scenes.json`, `frame_scores.json`,
  `frame_windows.json`, `frame_similarities.json`,
  `chapter_candidates.json`, `frame_ranks.json`,
  `frame_shortlist.json`, `selected_frames.json`, `report.md`, and
  the `candidate_frames/` directory) and resets the `normalize`,
  `transcribe`, `scenes`, `dedupe`, `window`, `similarity`,
  `chapters`, `rank`, `shortlist`, `verify`, and `assemble` stage
  entries to `pending`, so the next `recap run` (plus an explicit
  `recap scenes`, `recap dedupe`, `recap window`,
  `recap similarity`, `recap chapters`, `recap rank`,
  `recap shortlist`, and `recap verify` if those slices were in
  use) regenerates them cleanly from the new source.
- **Stage 5 restart.** `recap scenes` skips when `scenes.json` is
  present and every `frame_file` it lists is on disk; otherwise it
  recomputes. `recap scenes --force` removes `scenes.json` and the
  `candidate_frames/` directory in full before re-running.
- **`recap window` restart.** `recap window` skips when
  `frame_windows.json` already matches the current `transcript.json`
  and `scenes.json` — same `transcript_source`, same `scenes_source`,
  same `window_seconds` (`6.0`), and the same ordered
  `(scene_index, frame_file, midpoint_seconds)` triples as the current
  `scenes.json`. Any drift triggers a recompute. `recap window --force`
  removes `frame_windows.json` before recomputing. Missing
  `transcript.json`, missing `scenes.json`, malformed JSON in either
  file, a missing `segments` list on the transcript, a missing or empty
  `scenes` list, or a scene entry missing `index`, `frame_file`, or
  `midpoint_seconds` exits 2 with a one-line `error: ...` message.
- **`recap similarity` restart.** `recap similarity` skips when
  `frame_similarities.json` already matches the current `scenes.json`
  and `frame_windows.json` — same `model` (`ViT-B-32`), `pretrained`
  (`openai`), `device` (`cpu`), `image_preprocess`
  (`open_clip.default`), `windows_source` (`frame_windows.json`),
  `scenes_source` (`scenes.json`), the same ordered
  `(scene_index, frame_file, midpoint_seconds)` triples as the
  current `scenes.json`, and — for every frame — the same
  `window_start`, `window_end`, `window_text`, and
  `has_window_text == bool(window_text)` as the current
  `frame_windows.json`. Any drift in those per-frame window fields
  (not just the scene triples) triggers a recompute.
  `recap similarity --force` removes `frame_similarities.json`
  before recomputing. Missing `scenes.json`, missing
  `frame_windows.json`, missing `candidate_frames/`, malformed JSON
  in either input, any scene whose `frame_file` is absent from disk,
  empty `scenes`, a duplicate `scene_index` in `frame_windows.json`,
  a `frame_windows.json` entry missing `window_start`, `window_end`,
  or `window_text`, a non-string `window_text`, or a
  `frame_windows.json` entry whose `frame_file` or
  `midpoint_seconds` disagrees with `scenes.json` for the same
  `scene_index` exits 2 with a one-line `error: ...` message and
  does not leave a partial `frame_similarities.json` on disk.
- **`recap chapters` restart.** `recap chapters` skips when
  `chapter_candidates.json` already matches a fresh recomputation
  from the current `transcript.json` and (when present)
  `scenes.json` — same `transcript_source` (`transcript.json`),
  `source_signal` ∈ {`"pauses"`, `"pauses+speakers"`,
  `"pauses+scenes"`, `"pauses+speakers+scenes"`}, `pause_seconds`
  (`2.0`), `min_chapter_seconds` (`30.0`), `chapter_count`, and
  every per-chapter `index`, `start_seconds`, `end_seconds`,
  `first_segment_id`, `last_segment_id`, `segment_ids`, `text`, and
  `trigger`. The `speaker_change_count` key is present only in
  speaker-aware mode and is compared when present; absence in a
  stored non-speaker-aware artifact and presence in a
  freshly-computed speaker-aware one are treated as distinct and
  trigger recompute. The `scenes_source` and `scene_change_count`
  keys are present only in scenes-aware mode and follow the same
  presence-parity rule — adding, removing, or toggling a usable
  `scenes.json` triggers recompute, as does any drift in the set of
  segment ids onto which scene cuts map (via a change in scene
  `start_seconds` or a transcript re-segmentation that shifts which
  segment a given scene cut lands on). Any drift in the transcript
  segments or utterances (text edits, timing edits, added/removed
  segments, added/removed/flipped utterance speakers, adding or
  removing the `utterances` key entirely, or any other change that
  moves a chapter boundary, changes a trigger, or alters chapter
  text) triggers a recompute. `recap chapters --force` removes
  `chapter_candidates.json` before recomputing. Missing
  `transcript.json`, malformed JSON, a missing or empty `segments`
  list, a non-object segment, a segment missing `start`, `end`, or
  `text`, a segment with non-numeric `start` or `end`, a segment
  with non-string `text`, a segment with `end < start`, a
  non-numeric `duration`, `utterances` present but not a list, a
  non-object utterance, an utterance missing `id` or `speaker`, a
  non-integer `id`, a `speaker` that is not `int | null`, or a
  duplicate utterance `id` exits 2 with a one-line `error: ...`
  message and does not leave a partial `chapter_candidates.json` on
  disk. Missing `scenes.json` is treated as a fallback (no error)
  and yields non-scenes-aware output. A `scenes.json` that is not a
  JSON object, is missing `fallback` or has non-bool `fallback`, is
  missing `scenes` or has a non-list `scenes`, or contains a scene
  entry that is not an object, is missing `start_seconds`, or has
  non-numeric `start_seconds` exits 2 with a one-line
  `error: scenes.json ...` message and does not leave a partial
  `chapter_candidates.json{,.tmp}` on disk.
- **`recap rank` restart.** `recap rank` skips when
  `frame_ranks.json` already matches a fresh recomputation from
  the current `scenes.json`, `chapter_candidates.json`,
  `frame_scores.json`, `frame_windows.json`, and
  `frame_similarities.json` — same sources, same weights, same
  `input_fingerprints` (SHA-256 over canonical JSON for each of
  the five input artifacts), same `chapter_count`, `frame_count`,
  and every per-chapter and per-frame field. Any drift in any of
  the five input artifacts — including changes to
  `frame_windows.json` fields not directly used in ranking —
  triggers a recompute via fingerprint mismatch.
  `recap rank --force` removes `frame_ranks.json` before
  recomputing. Missing any input artifact, malformed JSON, empty
  `scenes` or `chapters` lists, non-contiguous chapter intervals,
  a `scene_index` mismatch across inputs, or a scene whose
  `midpoint_seconds` falls outside all chapters exits 2 with a
  one-line `error: ...` message and does not leave a partial
  `frame_ranks.json` on disk.
- **`recap shortlist` restart.** `recap shortlist` skips when
  `frame_shortlist.json` already matches a fresh recomputation
  from the current `frame_ranks.json` — same `ranks_source`,
  `thresholds`, `budget`, `policy_version`, `input_fingerprints`
  (SHA-256 hex over canonical JSON of `frame_ranks.json`),
  counts, ordered chapters, and every per-frame field. Any drift
  in `frame_ranks.json` (including drift that propagated into it
  from `scenes.json`, `chapter_candidates.json`,
  `frame_scores.json`, `frame_windows.json`, or
  `frame_similarities.json` via the rank stage's own
  fingerprint chain) triggers a recompute.
  `recap shortlist --force` removes `frame_shortlist.json`
  before recomputing. Missing `frame_ranks.json`, malformed
  JSON, an empty `chapters` list, a chapter missing required
  fields, a chapter whose `rank` sequence is not `1..N` in
  ascending order, a frame missing any required field, a
  non-integer `rank` or `scene_index`, a non-numeric
  `composite_score`, `midpoint_seconds`, `clip_similarity`, or
  `text_novelty`, or a duplicate `scene_index` across the whole
  input exits 2 with a one-line `error: ...` message and does
  not leave a partial `frame_shortlist.json` on disk.
- **`recap dedupe` restart.** `recap dedupe` skips when
  `frame_scores.json` already matches the current `scenes.json` and
  `candidate_frames/` — same metric (`phash+ssim+ocr`), hash size,
  pHash threshold, SSIM band, SSIM threshold, and `ocr_engine`, same
  scene indices and frame files, every frame file still on disk, and
  every entry carries an `ocr_text` string and a `text_novelty` key.
  Any drift (including a pre-OCR `metric=phash+ssim` or even earlier
  `metric=phash` file written by an earlier version) triggers a
  recompute. `recap dedupe --force` removes `frame_scores.json`
  before recomputing. Missing `scenes.json`, missing
  `candidate_frames/`, any scene whose `frame_file` is absent from
  disk, a malformed `scenes.json`, or a missing `tesseract` binary
  (only on the recompute path) exits 2 with a one-line `error: ...`
  message.
- Failures are recorded on the failing stage with `status: failed` and an
  `error` string, and surfaced as the top-level `status`/`error` on
  `job.json`. Re-running the command (or a specific subcommand) retries
  from that stage.

## Transcription behavior and the swap seam

The default engine is `faster-whisper`. `recap run` and
`recap transcribe` both accept `--engine {faster-whisper,deepgram}`
(default `faster-whisper`). The faster-whisper `transcript.json`
shape is unchanged:

```json
{
  "engine": "faster-whisper",
  "provider": null,
  "model": "small",
  "language": "en",
  "language_probability": 0.99,
  "duration": 123.45,
  "segments": [
    {"id": 0, "start": 0.0, "end": 3.08, "text": "..."}
  ]
}
```

`engine`, `provider`, `model`, `duration`, and `segments` are the
stable contract read by downstream code. `provider` is `null` for
local engines and `"deepgram"` for the Deepgram path.

**Deepgram sibling is implemented and optional.** Opt in with
`--engine deepgram`. Request parameters sent to
`POST {base_url}/v1/listen` are pinned in
`recap/stages/transcribe.py` for this slice: `smart_format=true`,
`punctuate=true`, `utterances=true`, `diarize=true`,
`detect_language=true`. `DEEPGRAM_DEFAULT_MODEL = "nova-3"`,
`DEEPGRAM_DEFAULT_BASE_URL = "https://api.deepgram.com"`,
`DEEPGRAM_TIMEOUT_SECONDS = 300`, and
`DEEPGRAM_PROVIDER_VERSION = "deepgram_v1"` are fixed code-level
constants. A retune of any of them must bump
`DEEPGRAM_PROVIDER_VERSION`. The engine reads three environment
variables: `DEEPGRAM_API_KEY` (required only when a recompute is
needed; a skip path that already matches the requested engine and
model does NOT require the key), `DEEPGRAM_MODEL` (optional
override of the pinned default), and `DEEPGRAM_BASE_URL` (optional
override of the pinned default). No new Python dependency is
introduced — the HTTP call uses stdlib `urllib.request` only.

**Deepgram transcript additive shape.** When `engine == "deepgram"`,
`transcript.json` keeps every required field at the same names and
types, and adds four optional fields:

```json
{
  "engine": "deepgram",
  "provider": "deepgram",
  "model": "nova-3",
  "language": "en",
  "language_probability": 0.93,
  "duration": 42.0,
  "segments": [{"id": 0, "start": 0.5, "end": 3.2, "text": "..."}],
  "utterances": [
    {"id": 0, "start": 0.5, "end": 3.2, "text": "...",
     "speaker": 0, "confidence": 0.98}
  ],
  "speakers": [
    {"id": 0, "utterance_count": 12, "total_seconds": 93.4,
     "first_seen_seconds": 0.0, "last_seen_seconds": 221.8}
  ],
  "words": [
    {"start": 0.5, "end": 0.9, "word": "hello",
     "confidence": 0.99, "speaker": 0}
  ],
  "provider_metadata": {
    "provider_version": "deepgram_v1",
    "model": "nova-3",
    "diarize": true,
    "smart_format": true,
    "punctuate": true,
    "detect_language": true,
    "base_url": "https://api.deepgram.com",
    "request_params": { "model": "nova-3", "smart_format": "true", "...": "..." }
  }
}
```

- `segments` are derived from Deepgram utterances (speaker /
  confidence stripped) so every current downstream stage reads the
  same shape it did before. If Deepgram returns no utterances,
  `segments` falls back to a single entry built from
  `results.channels[0].alternatives[0].transcript`; if that is also
  empty the stage exits 2 with `error: deepgram returned no
  transcript`.
- `utterances` carry the integer cluster `speaker` and float
  `confidence` returned by Deepgram. Empty-text utterances are
  dropped.
- `speakers` is deterministically derived from `utterances` sorted
  by `speaker` ascending; per entry: `utterance_count`,
  `total_seconds` (summed `end - start`), `first_seen_seconds`,
  `last_seen_seconds`.
- `words` is present whenever Deepgram returned words; per entry:
  `start`, `end`, `word` (prefers `punctuated_word`), `confidence`,
  `speaker`. Empty list otherwise.
- `provider_metadata` records the pinned request parameters and the
  resolved `base_url` and `model`. No request id, no raw response
  dump, no API key.

`faster-whisper` output is **unchanged on disk**: `utterances`,
`speakers`, `words`, and `provider_metadata` are NOT emitted for
the faster-whisper path. Every existing downstream stage
(`recap window`, `recap chapters`, `recap rank`, `recap shortlist`,
`recap assemble`) reads only `segments` and `duration`; they are
unaware of the new Deepgram-only fields and continue to work
unchanged over either engine's transcript. `recap run` stays
Phase-1-only in stage composition (`ingest → normalize →
transcribe → assemble`); the only change is that it forwards the
`--engine` flag to `transcribe.run()`.

**Atomic writes.** Both `transcript.json` and `transcript.srt` are
written via `.json.tmp` / `.srt.tmp` + `replace()`. On failure the
temp files are removed so no half-written artifact remains on disk.

**Skip contract.** A job whose stored `transcript.json` already has
the requested `engine` and `model` (with both `transcript.json` and
`transcript.srt` present) short-circuits with `skipped: true`. Any
mismatch on `engine` or `model` triggers a recompute.

**Error paths (all exit 2 with a single-line `error: ...`, no
traceback, no partial `transcript.json{,.tmp}` or
`transcript.srt{,.tmp}` on disk):** missing `DEEPGRAM_API_KEY` on
recompute, HTTP 401/403 (`deepgram authentication failed`), other
non-2xx (`deepgram request failed`), timeout, network failure,
invalid JSON, and empty-transcript responses.

**Swap seam (narrow, one `if/elif`, no registry).** The stage is a
function-level strategy: `recap/stages/transcribe.py` contains
`_transcribe_faster_whisper(audio, model_name)` and
`_transcribe_deepgram(audio, model_name, base_url, api_key)` as
siblings; `run()` dispatches on the `engine` argument. To add a
future engine (Groq, OpenRouter-hosted Whisper, Nvidia-hosted,
Gemma, WhisperX, etc.), add another sibling returning the same
shape and extend the `if/elif`. No registry, ABC, plugin system,
config file, or env-var indirection is in place or planned.

**Still deferred.** Groq, WhisperX, pyannote, speaker
recognition / manual labels, UI, captions, report screenshot
embedding, `selected_frames.json`, and DOCX/HTML/Notion/PDF
exports.

## Known limitations and assumptions

- **Two engines.** `faster-whisper` (default, local) and `deepgram`
  (optional cloud, opt-in via `--engine deepgram`) are implemented.
  `WhisperX`, `pyannote`, and Groq are still not wired up; they are
  listed in `TASKS.md` or noted as deferred and plug into the same
  function-level swap seam when explicitly approved.
- **CPU-only transcription.** The model is instantiated on CPU with
  `int8` quantization; no GPU or batched-pipeline configuration is
  exposed.
- **Empty-speech handling.** Videos with no speech produce a valid
  `transcript.json` with `segments: []` and an empty `transcript.srt`.
  The report honestly reports `Segments: 0`.
- **Metadata comes from `original.*`, not `analysis.mp4`.** This matches
  the brief's Stage 1 definition; values such as audio sample rate in
  `report.md` reflect the original container.
- **Model download on first run.** First transcription requires network
  access to fetch the Whisper weights into the local cache.
- **Local-first, single-process.** No queue, worker pool, remote
  orchestration, plugin system, or service layer. Everything runs in the
  calling process and writes directly into the job directory.

## Explicitly deferred to Phase 2 and later

Per `AGENTS.md`, `DECISIONS.md`, and `TASKS.md`, the following belong to
later phases and are **not** present in the current codebase:

- Phase 3: **full** chapter proposal from transcript/scene fusion
  (topic shifts, speaker changes, scene boundaries, and LLM
  titling). The chaptering slice — pause proposal plus
  speaker-change fusion when Deepgram utterances are present plus
  scene-boundary fusion when a usable `scenes.json` is present — is
  implemented (see above). Topic-shift detection, speaker
  recognition / manual labels, and chapter titling remain deferred.
  Per-chapter ranking fusion is implemented (see above). The
  deterministic pre-VLM keep/reject shortlist is implemented (see
  above); blur / low-information detection and the VLM-dependent
  "shows code / diagrams / settings / dashboards" keep rule remain
  deferred. Transcript-window alignment and OpenCLIP frame/text
  similarity — the first two Phase 3 slices — are implemented (see
  above). Groq, WhisperX, pyannote, VLM, UI, captions, report
  screenshot embedding, `selected_frames.json`, and exports remain
  deferred.
- Phase 4: optional VLM verification on finalists only
  (`selected_frames.json`), caption generation, chapter-aware Markdown
  assembly with embedded screenshots, and optional DOCX / HTML / Notion /
  PDF export.
- WhisperX as an optional word-level precision path.

These names are preserved in the binding docs and the artifact layout
section of `ARCHITECTURE.md`, but no code, interface, stub, or
configuration for any of them exists in the repo.

## Phase 1 closeout (+ Phase 2 checklist complete, + first five Phase 3 slices)

Phase 1 is complete, audited, hardened, and validated end-to-end on a
real speech sample. The required artifacts are produced, the pipeline
is restartable from disk, `job.json` reflects per-stage and overall
state, and the output remains Markdown-first. Two opt-in Phase 2 entry
points are implemented: Stage 5 candidate frame extraction
(`recap scenes` → `scenes.json` + `candidate_frames/`) and the combined
pHash + SSIM duplicate marking with Tesseract OCR novelty scoring
(`recap dedupe` → `frame_scores.json`). Every item in the `TASKS.md`
Phase 2 checklist is now ticked. Five Phase 3 slices are also
implemented: transcript-window alignment per candidate frame
(`recap window` → `frame_windows.json`), a deterministic ±6 second
window around each scene midpoint with the overlapping transcript
segment ids and their concatenated text; OpenCLIP frame/text
cosine similarity (`recap similarity` → `frame_similarities.json`)
using a pinned `ViT-B-32 / openai` model on CPU with the model's
shipped preprocessing; a chaptering slice
(`recap chapters` → `chapter_candidates.json`) that proposes
chapters from transcript pause gaps (`PAUSE_SECONDS = 2.0`,
`MIN_CHAPTER_SECONDS = 30.0`), fuses speaker-change boundaries when
the transcript carries Deepgram utterances (adds `"speakers"` to
`source_signal` and emits a pre-merge `speaker_change_count`), and
fuses scene-cut boundaries when a non-fallback `scenes.json` with
at least one scene cut mapping to a segment boundary is present
(adds `"scenes"` to `source_signal` and emits top-level
`scenes_source` plus a pre-merge `scene_change_count`);
per-chapter deterministic ranking
fusion (`recap rank` → `frame_ranks.json`) that scores and ranks
candidate frames within each chapter using OpenCLIP similarity, OCR
text novelty, and a duplicate penalty with fixed code-level weights;
and a deterministic pre-VLM keep/reject shortlist
(`recap shortlist` → `frame_shortlist.json`) that labels each frame
as hero / supporting / rejected_duplicate / rejected_weak_signal /
dropped_over_budget under fixed thresholds
(`CLIP_KEEP_THRESHOLD = 0.30`, `OCR_NOVELTY_THRESHOLD = 0.25`) and
a `1 + 2` per-chapter budget that matches Stage 7's "top 1 to 3
candidate frames per chapter" VLM verification step. The chapters
slice is explicitly not full Stage 4 chaptering — topic-shift
detection, speaker recognition / manual labels, and chapter titling
remain deferred. The ranking slice is marking-only
— it does not apply keep/reject thresholds, enforce a screenshot
budget, write `selected_frames.json`, or modify `report.md`. The
shortlist slice is marking-only and pre-VLM — it does not write
`selected_frames.json` (that filename is reserved for Phase 4
post-VLM finalists), invoke any VLM, generate captions, embed
screenshots, export documents, add UI, or do any speaker
diarization / recognition / separation work; blur /
low-information detection and the VLM-dependent "shows code /
diagrams / settings / dashboards" keep rule remain deferred. All
seven opt-in entry points have been validated against a
multi-scene sample, including skip-on-rerun, `--force` recompute
(byte-identical on re-run on the same machine), and clean
`error: ... / exit 2` paths for missing or malformed inputs. No
other Phase 3+ scaffolding has been introduced. Further work should
begin a separate, explicitly approved Phase 3 chunk.
