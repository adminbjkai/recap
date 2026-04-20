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

## 8. Screenshot / frame review UI

- React surface on the job dashboard (or transcript workspace) that
  renders `selected_frames.json` hero/supporting choices side-by-side
  with their chapter excerpt and any VLM-provided caption.
- Inline keep/reject overrides written as a small overlay file so
  `selected_frames.json` itself stays immutable and re-runnable.
- Respect the existing screenshot policy (1 hero per chapter, up to
  3 supporting, no fixed-interval capture).

## 9. Exports honor overlays fully

- `recap assemble` / `export-html` / `export-docx` render
  `speaker_names.json` labels (not fallback `Speaker N`), chapter-
  title overlay titles (not `chapter_candidates.json#title`), and
  any frame-review overlay from slice 8.
- Static check in `scripts/verify_reports.py` proves exports stay
  byte-compatible when no overlay is present.
- Exports still run from both the CLI and the legacy rich-report
  form; no new runtime dep.

## 10. Selected-speaker playback

- Toggle on the transcript workspace: "play only segments where
  Speaker N speaks."
- Driven entirely client-side from the existing transcript + speaker
  overlay. No API changes.

## 11. Transcript correction / notes overlay

- Per-segment note / correction field stored as a new overlay file
  next to `speaker_names.json`.
- Exports optionally include the corrected text (gated on slice 9
  landing).

## 12. Folders / projects / archive

- Rename a job (edit `original_filename` + visible title).
- Move a job between folders / projects.
- Archive a job (hide from the default index, never delete).
- Keep `jobs/<id>/` directory layout stable; organization lives in a
  sidecar index file at the jobs-root level.

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
