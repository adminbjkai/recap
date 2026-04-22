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
- Editable chapter titles / sidebar: **slice 7**.
- Transcript correction / notes overlay: **slice 11**.

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
- React upload / start flow: **done** (slice 5).
- Browser screen recording: **done** (slice 6).
- Webhooks / streaming progress surface: **slice 13**.

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

- Groq structured insights + report integration: **done** (slice 3).
- React rich-report progress: **slice 4b** (next active slice).
- Chapter sidebar + editable chapter titles: **slice 7**.
- Screenshot / frame review UI: **slice 8**.
- Webhooks / streaming progress / SSE: **slice 13**.

## Design-system references

The surfaces below are *reference-only*. Recap's stack is intentionally
small: stdlib Python HTTP server, React 18 / Vite / TypeScript, plain
CSS with custom-property tokens in `web/src/index.css`. None of the
libraries below are installed, imported, or vendored. We borrow
patterns — spacing, hierarchy, badge/card shapes, form copy,
information density — not code.

- **[Tabler](https://tabler.io/)** — dashboard layouts, card stacks,
  stat tiles, status badges, table density, toolbar patterns, form
  field metadata. Use as visual inspiration for dashboard-style pages
  like `/app/job/:id`. Do **not** install Tabler, Bootstrap, or any
  Tabler-adjacent JS/CSS bundle.
- **[ui-ux-pro-max](https://github.com/claude-skills/ui-ux-pro-max)** —
  design-system / accessibility / anti-pattern checklist. Treat as a
  prompting reference when a slice needs a hierarchy / spacing /
  state-coverage pass. Do **not** vendor the skill; re-derive the
  guidance into Recap's own CSS and copy.
- **[Nord](https://www.nordtheme.com/)** — calm technical palette.
  May inform a small accent-neutral choice but must not turn Recap
  into a generic blue-gray clone. The primary palette stays warm
  (ink / brand / accent tokens in `web/src/index.css`).
- **[TW Elements](https://tw-elements.com/)** — deferred. Only
  consider once Tailwind is formally adopted; right now Recap ships
  plain CSS and TW Elements would be dead weight.
- **[ClaudeSkills leaderboard](https://claude-skills.github.io/)** —
  skill-discovery source for implementation agents (which skill to
  reach for when). Not a product dependency and never embedded.

Practical guardrails when pulling from any of the above:

- Borrow shapes, not code. If a Tabler card has a clean header / body
  / footer rhythm, re-implement it with Recap's tokens.
- Keep accessibility real: visible focus ring, semantic buttons /
  links, readable contrast, no color-only status communication, and
  `prefers-reduced-motion` honored (we already ship the guard).
- Responsive by default: every new dashboard page must work on
  desktop and mobile without horizontal scroll.
- No dark-mode-only design. A dark-mode slice, when it lands, ships
  both themes.

## Rule of thumb

When pulling a pattern from any of the above, write one sentence in the
slice PR description that names which inspiration you borrowed and
why. That paper trail keeps this document honest.

## Patterns borrowed in the 2026-04-21 premium redesign pass

These are the concrete decisions taken when tightening the React
product (commit **Redesign React product experience**). Each item
maps the visual / hierarchy change back to the inspiration source.

- **Single subtle warm background** (linear wash only, no competing
  radial gradients). *Source:* Cap5's editorial workspace chrome;
  Nord's calm-palette restraint. *Where:* `body` override in
  `web/src/index.css`.
- **Flat brand mark, no gradient, no drop shadow.** *Source:*
  CapSoftware/Cap top-bar treatment. *Where:* `.recap-brand-mark`
  override.
- **One primary CTA per view, ink-strong button instead of warm
  gradient.** *Source:* steipete/summarize's single-action surface;
  Tabler's primary/ghost/text hierarchy. *Where:* `.primary-button`
  override + hero action strips across `/app/`, `/app/new`,
  `/app/job/:id`.
- **Library hero = title + subline + one CTA.** The stats grid was
  duplicated info (the same totals live in the Active/Archived tabs
  and the "Showing N of M" subtitle). Removed. *Source:* Cap5's
  quiet library screen; CapSoftware's "sell the next action" empty
  state. *Where:* `pages/JobsIndexPage.tsx`.
- **Job card state communicated as a 3 px accent stripe on the
  left edge** (completed green, running terracotta, failed red),
  not a colored fill. State word remains in the status chip so
  nothing is color-only. *Source:* Tabler status stripes; Nord
  restrained state accents. *Where:* `.job-card::before` override.
- **Compact neutral chip for metadata, colored badges reserved for
  status.** Engine / model / segments / project all render as flat
  neutral chips; status carries the only colored badge. *Source:*
  Tabler metadata rows, Cap5's compact meta line. *Where:*
  `.detail-chip`, `.status-badge`, `.status-pill`.
- **Detail-page hero split into a primary action strip + a quieter
  organize strip** (Rename, Archive) on its own line. Report links
  consolidated into a single labeled chip group instead of scattered
  text links. *Source:* steipete/summarize's document header;
  CapSoftware's "obvious primary action, quieter secondary" shape.
  *Where:* `pages/JobDetailPage.tsx` + `.detail-hero-meta-actions`,
  `.detail-hero-reports`.
- **"What happens next" collapsed behind a summary** on `/app/new`.
  The 4-step pipeline explanation was blocking the start button on
  mobile. *Source:* CapSoftware's unobtrusive docs link. *Where:*
  `<details className="next-steps-disclosure">` +
  `.next-steps-disclosure`.
- **Artifacts-on-disk disclosure** on the detail page keeps the
  `ArtifactGrid` reachable but demoted below insights / chapters /
  run actions. *Source:* Tabler's advanced-drawer pattern.
  *Where:* `<details className="detail-disclosure">`.
- **Segmented source-mode toggle** on `/app/new` ("Sources root" /
  "Record screen" / "Absolute path") as a single pill control
  instead of three full-width tabs. *Source:* CapSoftware's
  recording-mode switcher. *Where:* `.mode-toggle` + `.mode-tab`.
- **Transcript workspace header chips for engine / model / duration**
  instead of a run-on meta sentence. *Source:* Cap5's metadata
  chip row. *Where:* `pages/TranscriptWorkspacePage.tsx` +
  `.workspace-meta-parts`.
- **Frame review header chips for totals** instead of a dot-separated
  string. Chapter-grouped cards keep their editorial `Chapter N —
  display_title` heading. *Source:* steipete/summarize's chapter
  cards. *Where:* `pages/FrameReviewPage.tsx`.
- **Stronger focus ring** (3 px brand-tinted ring on every focusable
  element) and responsive collapses at 960 / 640 px so layouts never
  scroll horizontally. *Source:* ui-ux-pro-max accessibility pass;
  Tabler responsive patterns. *Where:* `:focus-visible` override +
  `@media (max-width: 960/640)` blocks.
