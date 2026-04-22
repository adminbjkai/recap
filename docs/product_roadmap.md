# Product roadmap

Recap is a local-first, privacy-respecting video-to-documentation tool.
You drop in a video, Recap gives you back a polished transcript
workspace and a report that is actually useful as documentation. The
roadmap below is **ordered**: each slice builds on the previous one and
is scoped small enough to land cleanly without flag days.

Slices marked **done** have already shipped on `main`.

## Defaults and priority cloud providers

- **Frontend:** React / Vite under `/app/` is the primary surface. The
  legacy stdlib HTML dashboard at `/` remains live as a fallback while
  the React migration continues — deleting or regressing a legacy route
  requires an explicit user green-light.
- **Transcription:** `faster-whisper` is the default (offline). When a
  user opts into a cloud engine, **Deepgram** is the priority provider
  (`--engine deepgram`, diarized utterances). `DEEPGRAM_API_KEY` +
  `DEEPGRAM_MODEL` + `DEEPGRAM_BASE_URL` control it.
- **Structured insights:** the `mock` provider is the default (offline,
  deterministic). When a user opts into a cloud LLM, **Groq** is the
  priority provider (`recap insights --provider groq`, strict JSON
  mode). `GROQ_API_KEY` + `GROQ_MODEL` + `GROQ_BASE_URL` control it.
- **Exporters:** `recap assemble` / `export-html` / `export-docx`
  consume `insights.json` when present and stay byte-compatible with
  earlier output when it is absent.
- **Opt-in stages stay opt-in.** `insights`, `verify`, and every Phase
  2/3 stage are entries inside `job.json#stages` but never inside
  `recap/job.py::STAGES` or `recap run` composition. That is a hard
  invariant; `scripts/verify_reports.py` has a static check for it.

## 1. React app shell + transcript workspace — **done**

**Shipped in:**
- `fda924c Add React transcript workspace and JSON API`

**What it gives users:**
- `/app/` route served by the stdlib Python server from `web/dist`.
- `/app/job/<id>/transcript` with native video, active-row sync,
  speaker-colored rows, and speaker rename persisted to
  `speaker_names.json`.
- JSON API: `/api/csrf`, `/api/jobs/<id>`, `/api/jobs/<id>/transcript`,
  `/api/jobs/<id>/speaker-names` (GET/POST).

## 2. React UI polish, transcript search, speaker filters — **done**

**Shipped in:**
- `1b9663b Add React jobs index`
- `5f63939 Polish React app UI and transcript interactions`

**What it gives users:**
- `/app/` jobs index with hero + stats and polished job cards.
- Client-side transcript search (highlight, count, prev/next cycling,
  scroll active match into view).
- Speaker filter chips on the legend (show/hide rows).
- `GET /api/jobs` listing endpoint with malformed-entry skip.
- Visual system in `web/src/index.css` with tokens, typography scale,
  elevation, focus ring, and `prefers-reduced-motion`.

## 3. Groq structured insights + export integration — **done**

**Shipped in:**
- `1532f16 Add structured insights for reports`
- `e32b6d9 Harden insights and align project guidance`

**Goal:** make the three existing exports (Markdown / HTML / DOCX)
carry real, useful information, not just a transcript dump.

**Deliverables:**
- `recap insights --job <path> --provider mock|groq [--force]`.
- New artifact `jobs/<id>/insights.json` with overview, per-chapter
  title/summary/bullets/action items, and a flat action-items list.
- Mock provider: deterministic, offline, derived from transcript +
  chapter_candidates + speaker_names + selected_frames.
- Groq provider: `GROQ_API_KEY` / `GROQ_MODEL` env, stdlib HTTP, strict
  JSON validation, fail cleanly on missing key.
- `recap assemble` / `export-html` / `export-docx` read `insights.json`
  when present and render overview + quick bullets + action items +
  chapter summaries. Reports stay compatible when insights is absent.
- `GET /api/jobs` / `GET /api/jobs/<id>` expose `insights_json`
  artifact flag and URL; React `JobCard` shows an Insights chip.
- `insights` stage is **opt-in**: not in `job.STAGES`, not in
  `recap run` composition.

**Non-goals:**
- No new Python runtime dependencies.
- No full React insights UI yet; a chip is enough for now.
- No prompt customization beyond env.

## 4. React job detail + rich-report progress — **done**

**Shipped in:**
- `e709673 Add React job detail dashboard` (4a: dashboard landing)
- `Add React rich-report progress + action endpoints` (4b: action
  endpoints + polling)

Shipped in this slice:

- `/app/job/:id` route backed by `GET /api/jobs/:id` plus a new
  read-only `GET /api/jobs/:id/insights` endpoint.
- Hero header with title, status badge, created/updated, engine and
  segment-count chips, and primary/secondary CTAs (Open transcript,
  Legacy detail, Open report in each format).
- Stage timeline rendered from `job.json#stages` covering ingest,
  normalize, transcribe, assemble, plus optional stages present in
  the job record (scenes, insights, export_html, export_docx, etc.).
  Failed stages surface their error text; completed / running /
  pending stages carry explicit badges.
- Artifact grid for transcript, analysis video, report.md/html/docx,
  insights.json, chapter_candidates.json, selected_frames.json, and
  speaker_names.json with open/download links when present and a
  "not generated yet" affordance otherwise.
- Insights preview: when `insights.json` exists it is fetched from
  the API and rendered inline (overview title, short summary, quick
  bullets, action items, chapter count). When absent, a strong empty
  state explains the CLI commands to run. Malformed files surface a
  clear error state.
- Jobs index `JobCard` primary click now opens `/app/job/:id`, with
  a secondary "Transcript" action routing to
  `/app/job/:id/transcript`.
- Legacy HTML detail page at `/job/:id/` remains live as a fallback.

**4b. React rich-report progress + action endpoints — shipped:**

- New `POST /api/jobs/<id>/runs/insights` (JSON body
  `{provider, force}`; provider allowlist `{mock, groq}`; Groq
  requires `GROQ_API_KEY`) kicks off `recap insights` under the same
  subprocess boundary as the CLI.
- New `POST /api/jobs/<id>/runs/rich-report` reuses the legacy
  `_background_rich_report` worker and the shared
  `(job_id, "rich-report")` `_last_run` entry, so a React-dispatched
  chain and a legacy-HTML-dispatched chain are indistinguishable
  from a status consumer's point of view.
- New `GET /api/jobs/<id>/runs/insights/last` and
  `GET /api/jobs/<id>/runs/rich-report/last` return a JSON status
  payload with `no-run` / `in-progress` / `success` / `failure`,
  timestamps, elapsed, truncated stdout/stderr, and (for
  rich-report) the ordered stage list with per-stage status and
  stderr.
- React `RunActionsPanel` on `/app/job/:id` renders the generate /
  regenerate insights action (with provider select + force
  checkbox), the rich-report action, a pending/running/completed/
  failed pill + colored dot (status is never color-only), a 2.5 s
  polling loop that only runs while something is in flight,
  auto-refresh of the parent job summary + insights preview on
  completion, and a fallback link to the legacy
  `/job/<id>/run/rich-report/last` page.
- Both dispatch endpoints share the existing safety model: Host
  pinning, `X-Recap-Token` CSRF, 8 KiB body cap, the global
  `_run_slot` semaphore, and a per-job lock transferred to the
  worker thread.
- Neither endpoint adds any stage to `_RUNNABLE_STAGES` /
  `_LAST_RESULT_STAGES`. `recap run` composition and `job.STAGES`
  are unchanged. The legacy `/job/<id>/run/rich-report`,
  `/job/<id>/run/rich-report/last`, exporter rerun routes, and the
  `/new` / `POST /run` form remain live as fallbacks.

**Still deferred:** SSE / WebSocket transport for progress (slice 13
owns that work). Polling is sufficient while run budgets stay below
a handful of minutes.

## 5. React `/app/new` start flow — **done (start subset)**

**Shipped in:**
- `07212c5 Add React new job flow`

**What it gives users:**
- `/app/new` React page with hero, source picker (lists videos under
  `--sources-root` via `GET /api/sources`), absolute-path fallback,
  engine selector (faster-whisper default / Deepgram opt-in when
  `DEEPGRAM_API_KEY` is present via `GET /api/engines`), "what
  happens next" panel, empty / loading / error / success states,
  keyboard-accessible controls, and visible focus.
- `POST /api/jobs/start` dispatch endpoint that reuses the legacy
  `POST /run` safety primitives and the shared ingest + background-
  run implementation, returning 202 with
  `{job_id, engine, react_detail, legacy_detail, started_at}` and
  JSON `{error, reason}` on failure. The React page redirects to
  `/app/job/<id>` on success.
- AppShell "New job" CTA points at `/app/new`. Legacy `/new` form
  and `POST /run` remain live as fallbacks.
- Verifier (`scripts/verify_api.py`) grew with cases for
  `/api/sources`, `/api/engines`, and `/api/jobs/start` — using a
  test-only `RECAP_API_STUB_JOB_START=1` shim that is off outside
  the verifier.

**Deferred to slice 5b:** streaming / polling progress UI while
`recap run` executes (see slice 4b for the related dashboard work).

## 6. Browser screen recording via MediaRecorder — **done**

**Shipped in:**
- `e88bb52 Add browser recording import flow`

**What it gives users:**
- A **Record screen** tab on `/app/new` that uses
  `navigator.mediaDevices.getDisplayMedia` + `MediaRecorder` to
  capture screen video + optional microphone audio locally. Clear
  unsupported state in non-capable browsers.
- Local preview after stop, with a separate **Save to sources**
  action — transcription never starts automatically.
- New `POST /api/recordings` endpoint that accepts a raw
  `video/webm` or `video/mp4` body, picks the filename server-side
  (`recording-<UTC>-<hex>.<ext>`), streams to
  `<sources-root>/<name>.tmp` in 256 KiB chunks with a 2 GiB cap,
  and `os.replace`-s into place. Host pinning and `X-Recap-Token`
  CSRF apply. Browser filenames are ignored entirely.
- Saved recording appears automatically in `GET /api/sources`, so
  `POST /api/jobs/start` can start a run from it using the
  existing `sources-root` source kind.
- Local-first: no third-party upload targets, no auth, no remote
  sync. All bytes stay on the machine running `recap ui`.

**Deferred:**
- Drag-and-drop or file-picker upload of pre-existing local video
  files (a separate slice from live recording).
- Rich recording controls: pause/resume, region selection beyond
  the browser picker, countdown, webcam PIP.
- Streaming / polling progress UI while `recap run` executes (still
  tracked as slice 4b).

## 7. Chapter sidebar + editable chapter titles — **done**

**Shipped in:**
- `Add editable chapter navigation`

**What it gives users:**
- A chapter sidebar on `/app/job/<id>/transcript` (left rail) that
  lists chapters with index, display title, timestamp range, and
  (when insights are present) summary / bullets / action items.
  Clicking a row seeks `analysis.mp4` to `start_seconds` and
  resumes playback. Active chapter highlights as the video plays
  via the existing `timeupdate` / `seeking` / `play` listeners, with
  both an accent border and `aria-current="true"` so the cue is not
  color-only.
- Inline chapter-title editing with Enter-saves, Escape-cancels,
  empty-clears. Custom titles persist to a new
  `chapter_titles.json` overlay next to `speaker_names.json`.
- Compact chapters card on `/app/job/<id>` showing the first few
  titles, a custom-title count, and a link to the workspace.
- New `GET /api/jobs/<id>/chapters` merged view (candidates +
  insights + overlay), `GET /api/jobs/<id>/chapter-titles`, and
  `POST /api/jobs/<id>/chapter-titles`. POST reuses Host pinning +
  CSRF + body cap + per-job lock + atomic write from the speaker-
  names overlay pattern.
- `display_title = custom_title || fallback_title`; `fallback_title`
  prefers the insights-provided chapter title, then the first
  sentence of `chapter_candidates.text`, then `"Chapter N"`.

**Deferred to slice 9 (already tracked):** exporters
(`recap assemble` / `export-html` / `export-docx`) reading
`chapter_titles.json`. Today the overlay only affects the React
surface; exports still render the upstream / fallback title. This
is kept separate to avoid report byte-compat regressions.

## 8. Screenshot / frame review UI — **done**

**Shipped in:**
- `Add screenshot review workspace`

**What it gives users:**
- `/app/job/<id>/frames` React route that renders every image in
  `candidate_frames/` as a card with the algorithm's output
  (hero / supporting / VLM-rejected, shortlist decision, rank,
  composite score, CLIP similarity, text novelty, VLM relevance +
  caption, OCR text) beside the image, plus the chapter context
  pulled from the existing chapters merger.
- Inline `keep` / `reject` / `unset` controls with a 300-char note
  per frame. Changes batch locally; a toolbar shows the unsaved
  count; a single **Save review** POST persists the whole batch to
  a new `frame_review.json` overlay via atomic
  `<file>.tmp` → `os.replace`. **Discard changes** reverts.
  Filter tabs narrow the grid by shortlist / selected / reviewed.
- New `GET /api/jobs/<id>/frames` merged view,
  `GET /api/jobs/<id>/frame-review` overlay read, and
  `POST /api/jobs/<id>/frame-review` overlay write. Write endpoint
  reuses Host pinning, `X-Recap-Token` CSRF, 8 KiB body cap,
  per-job lock, and atomic replace. Keys must pass
  `is_safe_frame_file` **and** carry a whitelisted image extension.
- Respects the existing screenshot policy — scoring and selection
  stages in `recap/stages/*` are untouched. The overlay never
  mutates `selected_frames.json` or `frame_scores.json`; it captures
  user intent for a future exporter-overlay slice.

**Deferred to slice 9:** exporters honoring `frame_review.json`
(kept separate to avoid report byte-compat regressions).

## 9b. React product polish — **done**

**Shipped in:**
- `Polish React product experience`

**What it gives users:**
- A coherent product feel across every React surface — the
  `/app/`, `/app/new`, `/app/job/:id`, `/app/job/:id/transcript`,
  and `/app/job/:id/frames` pages now share one consistent
  hierarchy (single primary CTA per surface, one subline of
  status + meta, low-priority detail behind disclosures).
- Job library cards lost the noisy artifact-chip strip in favour
  of a single "Report ready · Insights · …" readiness sentence.
- Job dashboard hero is one tight action strip (Open transcript,
  Review screenshots, quiet `Open report` text links, small
  Legacy fallback). Stage timeline + artifact grid still
  available, just visually demoted.
- Frame review groups frames by chapter so the surface feels
  editorial, not diagnostic. Per-frame raw scoring is one click
  away under "Scoring details".
- Single soft warm gradient background — no triple radial wash,
  no AI-purple gradient, no dark-mode-only solution.
- No backend changes; legacy HTML routes still render unchanged;
  no new dependencies (no Tailwind, Tabler, TW Elements, icon
  libraries, or UI kits).

## 9. Exports honor overlays fully — **done**

**Shipped in:**
- `Make exports honor review overlays`

**What it gives users:**
- `recap assemble` / `recap export-html` / `recap export-docx` now
  render custom speaker labels from `speaker_names.json`, custom
  chapter headings from `chapter_titles.json`, and filter / promote
  frames according to `frame_review.json` — the React workspaces
  and the exported report finally stay in sync.
- Precedence: `chapter_titles > insights title > Chapter N` for
  headings; `frame_review reject` suppresses a hero or supporting
  frame; `frame_review keep` on a `vlm_rejected` frame promotes it
  into the supporting list (sorted by `scene_index`);
  `speaker_names` substitutes the `Speaker N` prefix when the
  transcript carries `utterances[]`.
- Segments-only transcripts (the faster-whisper fixture path) stay
  byte-compatible with prior output — the overlay layer is a
  read-only pure-function layer sitting on top of the existing
  render path.
- Missing or malformed overlays degrade to empty overlays with no
  behavior; no exception leaks, no log spam, and the export byte
  output matches the no-overlay baseline.
- `scripts/verify_reports.py` grows from 29 → 48 checks covering
  every overlay × exporter combination plus byte-compat, malformed-
  overlay graceful fallback, and the "frame_review wins over
  selected_frames" contract.
- No runtime dependency changes; `recap run` composition and
  `recap/job.py STAGES` are untouched.

## 10. Selected-speaker playback

- Toggle on the transcript workspace: "play only segments where
  Speaker N speaks."
- Driven entirely client-side from the existing transcript + speaker
  overlay. No API changes.

## 11. Transcript correction / notes overlay — **done**

**Shipped in:**
- `Add transcript notes overlay`

**What it gives users:**
- Per-row correction + private note directly from the transcript
  workspace. Hovering a row reveals a small **Note** button; the
  inline editor opens beneath the row with a correction textarea
  (≤ 2000 chars), a private note (≤ 1000 chars), and a reminder
  that the canonical `transcript.json` stays untouched.
- A `Show corrections` toggle in the transcript card header flips
  rendered rows between the corrected overlay text and the
  canonical transcript. Reviewed rows carry an `edited` or `note`
  badge; any saved note shows up as a small preview paragraph.
- New `transcript_notes.json` overlay keyed by stable row ids
  (`utt-<n>` / `seg-<n>`). Empty fields clear just that field;
  clearing both fields drops the mapping. Merge-on-server
  semantics so single-row saves don't disturb other rows.
- New `GET /api/jobs/:id/transcript-notes` and
  `POST /api/jobs/:id/transcript-notes` endpoints reuse the shared
  overlay safety model (Host pinning, `X-Recap-Token` CSRF,
  per-job lock, atomic `<file>.tmp` → `os.replace`, malformed-on-
  read degrades to empty). Dedicated 64 KiB body cap so batched
  saves stay within bounds.
- Dashboard meta line carries a `Transcript notes` chip when the
  overlay file is present.

**Follow-up slice 9b — done.** Exporter integration for
`transcript_notes.json` shipped in `Make exports honor transcript
notes`. `recap assemble` / `export-html` / `export-docx` now read
the overlay at render time, swap in corrections with an
`*(edited)*` / `(edited)` marker, render reviewer notes as an
italic `Note:` block subordinate to the transcript row, and fall
back to byte-identical no-overlay output when the file is missing
or malformed. `scripts/verify_reports.py` grew with five
regression cases covering segment correction, note-only,
utterance correction via speaker label, malformed-overlay graceful
fallback, and empty-overlay byte-compat.

## 12. Folders / projects / archive — **done**

**Shipped in:**
- `Add job library organization`

**What it gives users:**
- A real personal library instead of a flat pile of job IDs.
  Users can rename jobs, assign them to projects, and archive the
  ones they don't want cluttering the Active view — all from the
  React jobs index and job dashboard.
- New `<jobs-root>/.recap_library.json` sidecar captures
  `{job_id: {title?, project?, archived?}}` with atomic
  `<file>.tmp` → `os.replace` writes. The job directory on disk
  is never moved, renamed, or deleted — organization is
  metadata-only, preserving the file-per-job invariant.
- New API surfaces: `GET /api/library` (project rollups + active /
  archived counts), `GET /api/jobs?include_archived=1` (opt-in),
  and `POST /api/jobs/:id/metadata` (partial PATCH-style update
  with Host pinning + CSRF + body cap).
- Every job summary now carries `display_title`, `custom_title`,
  `project`, `archived`.
- React library view has Active / Archived tabs, project dropdown
  filter, and inline Edit / Archive / Unarchive affordances per
  job card. The dashboard hero has a "Rename / Project" panel and
  matching Archive toggle. Archived jobs stay reachable by direct
  URL.
- Missing / malformed sidecar degrades silently to an empty
  library; the React surface still works, the user just sees no
  custom titles or projects.
- `scripts/verify_api.py` grew from 85 → 102 checks covering every
  validation path, partial PATCHes, archive filter, and malformed
  sidecar graceful fallback.

**Deferred (separate slice):** destructive delete of a job from
the UI. This slice covers the non-destructive half — archive hides
a job without touching the filesystem.

## 12e. Live job progress UX with safer polling — **done**

**Shipped in:**
- `Improve live job progress UX`

**Why:** the normalize hardening slice (`957ed44`) started
emitting rich heartbeat fields (`command_mode`, `phase`,
`percent`, `elapsed_seconds`, `output_bytes`,
`input_duration_seconds`) every ~2 s on a running job, and the
screenshot audit slice (`06d2aac`) made the UI read cleanly —
but long jobs still felt opaque. The user could not see what
the server was doing. And the dashboard was still re-fetching
every endpoint on mount with no live refresh, so a running job
looked stuck even when it wasn't.

**What it gives users:**
- A `JobProgressPanel` card on `/app/job/:id` that shows the
  current stage name + a pulsing dot, a `N / M done` counter,
  a progress bar when `normalize.percent` is present, and a
  small meta grid with Elapsed, Mode (remux / reencode),
  Progress (% of input duration), Output bytes, and Phase.
- Per-stage pill row that highlights the running stage, so the
  user can see at a glance how far through the chain a
  rich-report run has progressed.
- Clean failure banner naming the failed stage and surfacing
  the one-line error produced by the normalize hardening slice.
- Compact single-line completed summary once the job terminates.
- A running chip on `JobCard` in the library (`Normalize · 42%`
  with a pulsing dot) so the library view no longer just says
  "running" for a 20-minute job.

**Polling behavior (the "safer" half):**
- `JobDetailPage` polls `GET /api/jobs/:id` every **2.5 s**
  while the job is running; the interval is torn down the
  moment the snapshot lands as `completed` or `failed`. No
  background traffic after termination until the user navigates
  away and back.
- `JobsIndexPage` polls `GET /api/jobs` + `GET /api/library`
  every **5 s** only when at least one running job is on
  screen; zero cost on an idle library.
- Static endpoints — `/api/csrf`, `/api/engines`,
  `/api/sources`, `/api/library` (library detail) — are never
  re-fetched during polling. Only the summary endpoints that
  actually change.
- Transcript / insights / chapters are fetched once on mount
  and again when a run completes via `handleRunCompleted` —
  they don't change while a job is running and don't need
  polling.

**No API changes.** The existing `/api/jobs/:id` response
already returned the full `stages` dict including every heartbeat
field, so this slice is frontend-only.

**Invariants preserved:**
- `recap/job.py STAGES` and `recap/cli.py cmd_run` composition
  unchanged.
- No SSE / webhook / worker / queue / Docker / external service.
- No new Python or npm runtime deps.
- Host pinning, no-store JSON, CSRF unchanged (no new routes).
- Legacy HTML routes unchanged.

**Tests:** Vitest grows from 79 → 91 specs:
- `progress.test.ts` — pure-function matrix over stage
  ordering, running snapshot, failed-over-running, completed
  terminal state, `isJobActive`, running-summary formatting.
- `JobProgressPanel.test.tsx` — running card with normalize
  extras + progress bar + elapsed timer (injected clock);
  compact completed card; failed banner; pending fallback.
- `JobDetailPagePolling.test.tsx` — with `vi.useFakeTimers()`,
  proves a completed job never re-fetches the summary after
  mount; proves a running job ticks at 2.5 s and tears down
  the interval as soon as the snapshot becomes completed.

## 12d. UI audit from real screenshots — **done**

**Shipped in:**
- `Refine React UI from screenshot audit`

**Why:** the premium redesign pass of `12c` was written from
theory. Running `.venv/bin/python -m recap ui` against real jobs
and capturing every React route at 1440 × 900 plus 390 × 844 via
Playwright surfaced five concrete problems that the previous pass
had missed:

1. `StageTimeline` right rail on `/app/job/:id` rendered every
   stage's full `extras` dictionary inline — 50–80 admin-console
   rows on a rich-report job.
2. `JobCard` carried seven competing UI items per card on the
   library, turning the grid into a data table.
3. Detail-page hero mixed a primary button, a ghost button, a
   chip group, and a text link on the same row — no hierarchy.
4. Transcript workspace sidebar rendered chapter summary /
   bullets / action_items inline so the rail read as
   documentation instead of navigation.
5. Frame-review cards double-scaffolded the decision control
   alongside a full note textarea on first paint.

**What it gives users:**
- Right rail on the detail page collapses ~50 % vertically on a
  rich-report job; each stage is a one-line summary with the
  previous raw artifact dump behind `Details N ▾`.
- Library cards are readable at a glance: three small T / R / I
  readiness dots replace the readiness sentence, the grid
  stretches to `minmax(440 px, 1fr)`, and each card has one
  primary button + a quiet action row.
- Detail-page hero has one obvious primary CTA (`Open
  transcript workspace`) with reports / legacy demoted to
  secondary rows.
- Chapter sidebar reads as nav: titles + timestamps always
  visible, editorial outline behind a per-row disclosure.
- Frame gallery tightened via CSS only — uniform 16 : 9 image
  aspect, segmented-pill decision control, compact fieldset.
- `source-root-chip` no longer clips long absolute paths.

**Invariants preserved:**
- No new runtime deps (Python or npm).
- `recap/job.py STAGES` and `recap/cli.py cmd_run` composition
  unchanged.
- All 79 Vitest specs stay green — test-critical accessible
  names (`Keep`, `Reject`, `Unset`, `Save review (n)`, `Legacy
  detail page`, `Open job dashboard`, status radio labels) are
  unchanged.
- One small scoped CSS block reusing existing tokens — no new
  palette, shadow, or elevation tokens.
- Legacy HTML routes unchanged.

**Process:** the audit itself is recorded in
[CONTINUATION.md](../CONTINUATION.md) under "UI audit —
2026-04-21 screenshot pass" with before screenshot paths at
`/tmp/recap_ui_audit/before/` and after screenshot paths at
`/tmp/recap_ui_audit/after/` (10 files each, 5 routes × 2
viewports). Future UI passes should follow the same
screenshot-first approach.

## 12c. Premium React UI redesign — **done**

**Shipped in:**
- `Redesign React product experience`

**Why:** the React app had all the right functionality after the
library-organization slice but still felt like a dense admin
dashboard. The ask for this slice was a cohesive editorial /
premium feel — calmer surfaces, clearer hierarchy, one obvious CTA
per view — without rewriting the component surface.

**What it gives users:**
- **Cohesive visual system** layered on top of the existing CSS:
  calmer warm palette, flatter single-gradient background, tighter
  radii, softer single-layer shadows, brand-tinted 3 px focus ring,
  ink-strong primary button instead of a terracotta gradient.
- **One primary CTA per view.** Library hero drops its stats grid;
  detail-page hero now has a single primary action strip plus a
  quieter organize strip for Rename / Archive; `/app/new` launch
  bar keeps "Start job" primary and demotes "Use legacy /new" to a
  small text link.
- **Dense metadata moves behind disclosures.** The `/app/new`
  "What happens next" explainer and the detail page's raw
  artifacts-on-disk grid are now `<details>` disclosures.
- **Status is never color-only.** `JobCard` gains a 3 px left-edge
  accent stripe, but every card also renders the status word in a
  neutral chip. Metadata chips are flat neutral; colored badges are
  reserved for status.
- **Segmented source-mode toggle** on `/app/new` replaces three
  full-width tabs with a single pill control.
- **Transcript workspace** renders engine / model / duration as a
  chip row and demotes the "Back to dashboard" affordance to a
  quiet text link.
- **Frame review** header exposes `N candidates · N shortlist · N
  selected · N reviewed` as chips and demotes the
  dashboard/transcript nav links to text links.
- **Responsive collapses at 960 / 640 px** — the detail grid, the
  workspace grid, and the new-job grid all drop to a single column
  on narrow viewports; action strips stack on mobile so the primary
  button is always reachable and nothing scrolls horizontally.

**Invariants preserved:**
- No API or backend changes; `recap/job.py STAGES` and
  `recap/cli.py cmd_run` composition unchanged.
- No new runtime deps (Python or npm).
- Every Vitest expectation (79 specs / 17 files) stays green —
  critical button and chip text such as `Open job dashboard`,
  `Transcript`, `Save review (n)`, `Legacy detail page`, the radio
  labels `Completed / Running / Failed / Pending`, and the chips
  `Engine · deepgram` / `42 segments` were all preserved.
- Legacy HTML routes remain live.

**Tests:** no new test files. Existing tests exercise the refreshed
markup because all depended text and ARIA roles stayed put.

**Docs:** [docs/ux_inspiration.md](docs/ux_inspiration.md) gains a
"Patterns borrowed in the 2026-04-21 premium redesign pass" section
mapping each visual change back to Cap5 / CapSoftware/Cap /
steipete/summarize / Tabler / Nord / ui-ux-pro-max.

## 12b. Normalize reliability + MP4 fast path — **done**

**Shipped in:**
- `Harden normalize and add MP4 fast path`

**Why:** a real job for a ~56-minute 4K MP4 hung during `recap
normalize`. FFmpeg sat pinned at 100% CPU, `analysis.mp4` never grew
past a partial tmp, `job.json` stayed at `normalize=running`, and the
half-written output on disk was unreadable ("moov atom not found"). A
restart couldn't tell whether normalize had succeeded or failed.

**What it gives users:**
- **Atomic outputs.** Every normalize output — `metadata.json`,
  `analysis.mp4`, `audio.wav` — is written to `<target>.tmp` and
  promoted with `os.replace` **only after** FFmpeg exits cleanly and a
  follow-up `ffprobe` validates the tmp. A hung/killed/corrupt run
  never leaves a bad file at the final path.
- **Fast path for compatible MP4.** A new pure helper
  `_decide_normalize_mode(probe)` inspects the ffprobe JSON and returns
  `"remux"` when the source is MP4/MOV with H.264 + yuv420p video and
  AAC (or no) audio, else `"reencode"`. The remux branch runs
  `ffmpeg -c copy -map 0 -movflags +faststart`, so an already-compatible
  56-minute recording finishes in seconds instead of re-encoding. The
  re-encode branch keeps the existing `libx264 veryfast crf=23` +
  `aac 128k` + `yuv420p` + `+faststart` profile.
- **Stall guard + wall-clock timeout.** New
  `_run_ffmpeg_streaming` drives FFmpeg via `subprocess.Popen` with a
  dedicated stderr-drain thread. Every 500 ms the main thread samples
  the tmp file size plus the last-stderr timestamp; if neither moves
  for `RECAP_NORMALIZE_STALL` seconds (default 90) the process is
  killed and the stage fails with `ffmpeg stalled: ...`. A hard
  wall-clock cap `RECAP_NORMALIZE_TIMEOUT` (default 2 hours) fires
  `ffmpeg wall-clock timeout after ...`.
- **Progress heartbeats.** Roughly every 2 seconds the runner calls
  `update_stage(paths, "normalize", RUNNING, extra=...)` with
  `command_mode` (`"remux"` or `"reencode"`), `elapsed_seconds`,
  `output_bytes`, `phase` (`"analysis"` / `"audio"`), and — when
  ffprobe knew the input duration — `percent` + `input_duration_seconds`.
  `write_job()` bumps `updated_at`, so the React UI sees motion during
  long runs.
- **Clean failure.** Any exception (FFmpeg nonzero, stall, timeout,
  ffprobe validation) unlinks every `*.tmp` in a `finally` block and
  marks the stage FAILED with a short one-line error. No stale
  `analysis.mp4` is left for a subsequent `transcribe` to choke on.
- **Env escapes:** `RECAP_NORMALIZE_TIMEOUT`, `RECAP_NORMALIZE_STALL`,
  and `RECAP_NORMALIZE_NO_FASTPATH=1` (force full re-encode even on a
  perfect input, for debugging).

**Tests:** `scripts/verify_reports.py` grew by four regression checks
for 60 → 64 total:
- `normalize-mode-decision` — pure-function matrix over MP4/MOV +
  H.264/HEVC + yuv420p/yuv444p + AAC/Opus/no-audio + WebM +
  malformed-probe cases, plus the `RECAP_NORMALIZE_NO_FASTPATH` env
  escape.
- `normalize-failure-cleans-tmp` — monkey-patches
  `_run_ffmpeg_streaming` to write a partial tmp then raise
  `NormalizeError`, asserts `stages.normalize.status == "failed"`,
  the error mentions "stalled", `analysis.mp4` was **not** promoted,
  and `analysis.mp4.tmp` / `audio.wav.tmp` / `metadata.json.tmp` are
  all gone.
- `normalize-invalid-output-not-promoted` — monkey-patches the runner
  to exit cleanly with garbage in the tmp, patches
  `_validate_analysis` to reject it, asserts the stage ends FAILED
  with a "validation" error, `analysis.mp4` is not promoted, and
  `analysis.mp4.tmp` is unlinked.
- `normalize-stages-and-cmd-run-unchanged` — static pin that
  `recap.job.STAGES == ("ingest", "normalize", "transcribe",
  "assemble")` and `cmd_run` in `recap/cli.py` calls
  `normalize.run` / `transcribe.run` / `assemble.run` and no opt-in
  stage.

**Invariants preserved:** no new Python runtime deps; `recap/job.py
STAGES` unchanged; `recap/cli.py cmd_run` composition unchanged;
`recap run` remains Phase-1-only; legacy HTML routes unchanged; no
fixture bytes changed.

## 13. Live progress (SSE / polling) + webhooks

- Server-Sent Events channel or long-poll endpoint for job progress
  (picked in slice 4b's follow-up).
- Optional outbound webhook on stage transitions for self-hosted
  automations. Webhooks are opt-in, URL whitelisted, and never carry
  transcript text or API keys.

## 14. Linux self-host / deploy hardening

- End-to-end doc for running Recap on a Linux box.
- Sample `systemd` unit with least-privileged user, read-only paths.
- Reverse-proxy notes covering Host pinning and CSRF with
  nginx/Caddy/Traefik examples.
- TLS guidance (Let's Encrypt via the proxy, never in the stdlib
  server).

## 15. Single-user auth / reverse-proxy auth

- Ship a minimal authentication surface so Recap can safely bind
  beyond `127.0.0.1`.
- Primary: reverse-proxy auth integration (`X-Remote-User` header
  trust when the proxy is configured; disabled by default).
- Secondary: optional built-in single-user login backed by a hashed
  password + session cookie. Still single-user — not multi-tenant.
- Gated on slice 14 landing so the deploy docs and the auth model
  ship together.

## 16. Playwright browser coverage

- Headless Playwright tests exercising the full React surface against
  a real `recap ui` process.
- Smoke-run the golden path end to end on every CI build.

---

Slices after this point will be triaged once the first nine above are
in. Candidate follow-ups include: drag-and-drop upload of pre-
existing local video files (separate from live recording), pluggable
LLM providers beyond Groq, and multi-voice voiceover on export.
Multi-user accounts, native-app wrappers, and cloud-sync targets are
**not** currently on the roadmap.
