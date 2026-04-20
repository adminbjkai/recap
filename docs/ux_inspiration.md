# UX inspiration

Recap borrows product patterns from a small number of adjacent projects.
None of their code is vendored into Recap: every pattern listed here must
be re-implemented inside this repo, using Recap's own stack (stdlib
Python HTTP server + React 18 / Vite / TypeScript / plain CSS). If in
doubt about a given snippet, assume it is **not** safe to copy
verbatim.

This file exists so each future slice can check "which inspiration does
this map to?" and so we don't silently drift.

## Scope of this document

This file is about **UX / product patterns**. The concrete platform
decisions (React/Vite under `/app/`, legacy HTML routes kept as
fallback, **Deepgram** as the priority cloud transcription engine,
**Groq** as the priority cloud insights provider, `insights.json`
opt-in and consumed by exporters) live in
[product_roadmap.md](product_roadmap.md). When a borrowed UX pattern
depends on one of those, check the roadmap before implementing.

## Licensing posture

- **Borrow product patterns, not code.** Layout ideas, interaction
  patterns, data shapes, and names are fair game. Code, SVG icons,
  fonts, and copy are not.
- Before pulling anything from an external repo, confirm its license is
  compatible with a permissive local-first tool. If unsure, treat the
  inspiration as read-only.
- Never commit third-party asset binaries (fonts, icons, videos, audio)
  from these repos. Always regenerate or source from a permissively
  licensed origin.
- Do not copy prompts or LLM instructions verbatim. Recap's Groq
  prompts must be written for Recap's schema.

## [Cap5](https://github.com/adminbjkai/cap5)

A local-first transcript workspace that already pairs video with a
diarized, editable transcript.

### Borrow

- Transcript-first workspace: video in a rail, transcript as the
  primary reading surface, active-row sync with the player.
- Speaker rename + show/hide filter as two separate affordances on the
  same legend.
- Chapter navigation that jumps the player and highlights the active
  chapter.
- Notes / editable annotation overlay that lives beside the transcript
  instead of on top of it.

### Do not copy

- Component library, CSS variables, icons, or fonts as-is.
- Storage layout or database schemas — Recap is file-per-job with
  `speaker_names.json` etc., not a shared database.
- Any shipped auth / account concepts.

### Maps to Recap slices

- Transcript workspace polish: **done** (slice 2 in the roadmap).
- Editable chapter titles / sidebar: **slice 8**.
- Transcript correction / notes overlay: **slice 10**.

## [CapSoftware/Cap](https://github.com/CapSoftware/Cap)

A polished screen-recording product with a clean self-hosted mental
model. Useful as a reference for the "feels like a real product"
surface and for the recording flow.

### Borrow

- Top-bar product identity: one mark, one short tagline, primary CTA
  on the right.
- Empty states that sell the next action instead of showing a
  placeholder wall.
- Clear recording mental model: one click to start, a clear stop
  affordance, a clear "what just happened" destination.
- Self-hosted framing: local-first first, optional cloud later.

### Do not copy

- Native app chrome / Tauri integrations — Recap is a browser workspace.
- Cap's billing / team concepts.
- Any Stripe, Clerk, or analytics wiring.

### Maps to Recap slices

- Jobs-index hero + stats: **done** (slice 2).
- Browser screen recording: **slice 6**.
- React upload / start flow: **slice 5**.
- Webhooks / streaming progress surface: **slice 11**.

## [steipete/summarize](https://github.com/steipete/summarize)

A video-summarization CLI/workbench with very strong transcript-first
media flow. It also has a robust pattern for streaming progress and
cache-aware reuse of expensive artifacts.

### Borrow

- Transcript-first intermediate artifacts: Recap already writes
  `transcript.json` + `chapter_candidates.json` + `selected_frames.json`;
  mirror this philosophy for insights (`insights.json`).
- Slide/frame "cards" alongside transcript lines: each chapter has its
  hero frame, its summary, its action items. A card is one chapter.
- Streaming progress + cached artifact reuse: if a stage already ran,
  reuse it; otherwise stream progress to the UI while it runs.
- Extract/report modes: separate the "pull structured data out" step
  from the "render a report" step. Recap already has this split
  (`recap insights` vs. `recap assemble` / `export-html` / `export-docx`).
- Lightweight metrics/diagnostics: every stage writes `started_at`,
  `finished_at`, and any relevant counters.

### Do not copy

- The exact prompts used against any LLM vendor.
- The exact cost/perf metrics dashboards (if any) — Recap does not need
  this yet.
- Any proprietary CLI flags or environment variables beyond Recap's
  own namespace.

### Maps to Recap slices

- Groq structured insights + report integration: **slice 3 (this
  slice)**.
- React rich-report progress: **slice 4**.
- Chapter sidebar + editable chapter titles: **slice 8**.
- Webhooks / streaming progress / SSE: **slice 11**.

## Rule of thumb

When pulling a pattern from any of the above, write one sentence in the
slice PR description that names which inspiration you borrowed and
why. That paper trail keeps this document honest.
