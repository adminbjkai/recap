# Architecture

This document describes Recap as it exists on `main` today. For the
long-form pipeline philosophy and the original 8-stage target vision,
see [MASTER_BRIEF.md](MASTER_BRIEF.md) — it is the north star for stage
shape, not a description of what currently runs in `recap run`. For the
ordered list of current/future product slices, see
[docs/product_roadmap.md](docs/product_roadmap.md).

## 1. Product shape

Recap is a **local-first, self-hosted** workspace that turns screen
recordings into structured documentation. It runs as one process on a
user's own machine (or a trusted server) and never sends media to a
third-party service unless the user explicitly opts into a cloud
provider (`--engine deepgram`, `recap insights --provider groq`).

The product surface has three layers stacked on a single file tree:

- **CLI** (`python -m recap ...`) — the canonical way to run stages.
  `recap run` is the Phase-1 golden path. Every opt-in stage is its own
  CLI verb (`recap scenes`, `recap dedupe`, `recap window`,
  `recap similarity`, `recap chapters`, `recap rank`, `recap shortlist`,
  `recap verify`, `recap insights`, `recap assemble`,
  `recap export-html`, `recap export-docx`).
- **Local HTTP server** (`recap ui`) — a single stdlib
  `ThreadingHTTPServer` process that serves the legacy HTML dashboard
  at `/`, the JSON API at `/api/*`, the built React SPA under
  `/app/*`, and whitelisted static artifacts under `/job/<id>/*`. No
  Flask, no Django, no external web framework.
- **Modern web app** — a React 18 / Vite / TypeScript SPA built into
  `web/dist/` and served by the same Python process. Talks to the
  stdlib server over the JSON API. See §4.

Every job is a **directory of artifacts** under `jobs/<job_id>/`. There
is no database, no queue, no worker pool, no object store.
Restartability comes from reading artifacts off disk and re-entering
the stage that owns them. See §3 for the artifact list and §6 for the
local-first invariants.

```
┌────────────────────┐        ┌──────────────────────────────────────┐
│ CLI: python -m     │        │ HTTP: recap ui (stdlib only)         │
│  recap ...         │        │                                      │
│                    │        │  /                legacy HTML        │
│  recap run         │        │  /new             legacy start form  │
│  recap insights    │        │  /job/<id>/*      legacy pages +     │
│  recap scenes …    │        │                   static artifacts   │
│  recap export-*    │        │  /api/*           JSON API           │
│                    │        │  /app/*           React SPA (dist)   │
└─────────┬──────────┘        └───────────────┬──────────────────────┘
          │                                   │
          ▼                                   ▼
       ┌──────────────────────────────────────────────┐
       │ jobs/<job_id>/  (file-per-job workspace)     │
       │   job.json, original.*, analysis.mp4,        │
       │   audio.wav, transcript.json/srt,            │
       │   scenes.json, candidate_frames/*,           │
       │   frame_* intermediate artifacts,            │
       │   chapter_candidates.json,                   │
       │   selected_frames.json,                      │
       │   speaker_names.json   (overlay)             │
       │   insights.json        (overlay, opt-in)     │
       │   report.md / report.html / report.docx      │
       └──────────────────────────────────────────────┘
```

## 2. Core invariants (do not regress)

These are the hard rails. Every slice must preserve them.

- **`recap run` composition is frozen** as `ingest → normalize →
  transcribe → assemble`. `recap/cli.py::cmd_run` calls those four
  stages and nothing else.
- **`recap/job.py::STAGES`** remains
  `("ingest", "normalize", "transcribe", "assemble")`. It is also what
  `scripts/verify_reports.py` statically pins.
- **Opt-in stages stay opt-in.** `scenes`, `dedupe`, `window`,
  `similarity`, `chapters`, `rank`, `shortlist`, `verify`, `insights`,
  `export-html`, `export-docx` are CLI-invokable or dashboard-rerun
  only. They may record entries inside `state["stages"]` via
  `update_stage`, but they are never added to `STAGES` or to `cmd_run`.
- **Legacy HTML routes remain live** while the React migration is in
  progress. `/`, `/new`, `/job/<id>/`, `POST /run`, the exporter-rerun
  POST surface, and the rich-report chain are all fallbacks for users
  who can't or don't want to run the SPA. Regressing a legacy route
  requires an explicit user green-light.
- **File-per-job.** No shared database, no shared object store. Every
  writer goes `<file>.tmp` → `os.replace`. Every reader validates shape
  before use.
- **No new Python runtime dependency** without explicit approval.
  `requirements.txt` and `pyproject.toml` do not change on a normal
  slice.
- **Secrets discipline.** API keys, prompt bodies, transcript text, and
  request bodies are never logged, written to `job.json`, or included
  in exception messages. Error messages may carry HTTP status codes
  and short (<= 200 byte) response snippets.

## 3. Stages and artifacts

Recap keeps the original 8-stage mental model from
[MASTER_BRIEF.md](MASTER_BRIEF.md), split across a frozen Phase-1 core
and opt-in stages.

### Phase-1 core (`recap run`)

1. **Ingest** — accept a video path or browser recording, create
   `jobs/<id>/`, copy it in as `original.<ext>`, write `metadata.json`
   from `ffprobe`, initialize `job.json`.
2. **Normalize** — transcode with `ffmpeg` to `analysis.mp4`
   (H.264 / AAC / `yuv420p` / `+faststart`) and extract `audio.wav`
   (16 kHz mono PCM s16le).
3. **Transcribe** — run the selected engine against `audio.wav`. Write
   `transcript.json` and `transcript.srt`. Engine choices:
   - **`faster-whisper`** (default, local, offline).
   - **`deepgram`** (cloud, diarized utterances). Requires
     `DEEPGRAM_API_KEY` + optional `DEEPGRAM_MODEL` /
     `DEEPGRAM_BASE_URL`. Adds optional `utterances`, `speakers`,
     `words`, and `provider_metadata` fields to `transcript.json`.
4. **Assemble** — read `transcript.json` + optional insights/chapter
   artifacts and write `report.md` atomically via `report.md.tmp`.

Every Phase-1 stage is restartable from its predecessor's artifact.

### Opt-in stages

- **`recap scenes`** → `scenes.json` + `candidate_frames/`
  (PySceneDetect ContentDetector; single-scene fallback).
- **`recap dedupe`** → `frame_scores.json` (pHash + SSIM + Tesseract
  OCR text novelty).
- **`recap window`** → `frame_windows.json` (±5–7 s transcript window
  per candidate).
- **`recap similarity`** → `frame_similarities.json` (OpenCLIP
  frame↔text cosine).
- **`recap chapters`** → `chapter_candidates.json` fusing transcript
  pauses with speaker changes (when Deepgram utterances are present)
  and scene-cut boundaries (when `scenes.json` is usable). Falls back
  to pause-only. `source_signal` records which signals were used.
- **`recap rank`** → `frame_ranks.json` (per-chapter deterministic
  fusion of dedupe + OCR novelty + similarity).
- **`recap shortlist`** → `frame_shortlist.json` (deterministic
  keep/reject, pre-VLM).
- **`recap verify`** → `selected_frames.json` (optional VLM pass over
  the shortlist; `mock` default or `gemini` opt-in).
- **`recap insights`** → `insights.json` (overview / per-chapter
  titles / summaries / bullets / action items). Providers: `mock`
  (deterministic, offline) and `groq` (cloud, stdlib HTTP, strict JSON
  mode, fails cleanly on missing `GROQ_API_KEY`).
- **`recap export-html`** → `report.html`.
- **`recap export-docx`** → `report.docx` (via `python-docx`).

### Overlays

Some artifacts are **overlays** that never mutate the underlying
artifact they annotate:

- **`speaker_names.json`** — `{version, updated_at, speakers: {id:
  label}}`. Maps speaker ids (integer strings for Deepgram) to
  editable human labels. Mutated only via
  `POST /api/jobs/<id>/speaker-names`. The React transcript workspace
  uses it immediately; exporters currently still render fallback
  `Speaker N` (see Future roadmap: "Exporters honor overlays fully").
- **`insights.json`** — structured summaries. `recap assemble` /
  `export-html` / `export-docx` consume it when present and render
  `## Overview` + per-chapter enrichments; when absent, output stays
  byte-compatible with the Phase-1 baseline.

### Browser recordings

Recordings made in the React `/app/new` "Record screen" tab are
stored **under the server's `--sources-root`** (not inside any
`jobs/<id>/`). The server picks a safe name
`recording-<UTC>-<hex>.<ext>` and ignores the browser-supplied
filename entirely. The resulting file then appears in
`GET /api/sources` alongside existing local videos, so
`POST /api/jobs/start` can consume it with the existing
`sources-root` source kind. No new source kind, no new storage
concept; the ingest step onwards is unchanged.

## 4. Frontend: React SPA + legacy HTML fallback

Recap serves **two** UIs from the same Python process:

### React SPA under `/app/*`

Built from `web/` (React 18 + Vite + TypeScript + Vitest + plain CSS
with custom-property tokens). The stdlib server serves `web/dist/`
assets at `/app/*` with a SPA fallback that returns
`web/dist/index.html` for unmatched routes. React Router owns:

- `/app/` — jobs index (hero + stats + job cards, search + status
  filter, backed by `GET /api/jobs`).
- `/app/new` — start a recap job. Three tabs inside the source card:
  **Sources root** (pick from `GET /api/sources`), **Record screen**
  (browser `getDisplayMedia` + `MediaRecorder` → `POST /api/recordings`
  → appears in sources), **Absolute path**. Engine selector
  (`GET /api/engines`: faster-whisper always available, Deepgram only
  when `DEEPGRAM_API_KEY` is set), "what happens next" panel, single
  Start button → `POST /api/jobs/start`, redirect to `/app/job/<id>`.
- `/app/job/<id>` — job dashboard. Hero, stage timeline from
  `job.json#stages`, artifact grid, insights preview via
  `GET /api/jobs/<id>/insights`.
- `/app/job/<id>/transcript` — transcript workspace. Native video
  from `analysis.mp4`, speaker-colored rows with legend that doubles
  as filter chips, transcript search with match highlight + prev/next,
  inline speaker rename persisted through
  `POST /api/jobs/<id>/speaker-names`.

All four pages are wrapped in an `AppShell` sticky top bar with
navigation to the legacy HTML dashboard and to `/app/new`.

### Legacy HTML routes

The original stdlib server-rendered pages remain live:

- `GET /` — jobs index.
- `GET /new` — HTML form to start a run.
- `GET /job/<id>/` — job detail, stage table, errors surface,
  chapters & selected-frames summary when both artifacts are present,
  and rerun-action forms for `assemble` / `export-html` /
  `export-docx` plus the rich-report chain.
- `GET /job/<id>/transcript` — server-rendered transcript viewer with
  inline video + active-row sync.
- `GET /job/<id>/<whitelisted-artifact>` — direct artifact download.
- `POST /run`, `POST /job/<id>/run/<stage>`, `POST /job/<id>/
  rich-report` — all Host-pinned + CSRF-guarded.

These routes are deliberately preserved so users can work without
JavaScript and so a React slice can always roll back to its legacy
counterpart.

## 5. JSON API

The JSON API is the contract between the SPA and the Python server.
Every response carries `Cache-Control: no-store`. State-changing
`POST`s require `X-Recap-Token` CSRF and a valid `Host` header.

```text
GET  /api/csrf                       token for state-changing POSTs
GET  /api/sources                    video files under --sources-root
GET  /api/engines                    engine availability (no key value)
GET  /api/jobs                       jobs index listing
GET  /api/jobs/<id>                  single-job summary
GET  /api/jobs/<id>/transcript       raw transcript.json
GET  /api/jobs/<id>/insights         parsed insights.json (404 if absent)
GET  /api/jobs/<id>/speaker-names    current speaker-names overlay
POST /api/jobs/<id>/speaker-names    update overlay (CSRF, Host-pinned)
POST /api/jobs/start                 dispatch a new run (CSRF, Host-pinned)
POST /api/recordings                 browser-recorded clip upload (CSRF, Host-pinned)
```

Key safety model details:

- **Host pinning** — the `Host` header must match the bound
  `host:port` or a loopback alias, compared via
  `secrets.compare_digest`. Blocks DNS-rebinding attacks.
- **Body caps** — `/api/jobs/<id>/speaker-names` and
  `/api/jobs/start` cap the body at 8 KiB; `/api/recordings` caps at
  2 GiB streamed to disk in 256 KiB chunks (never held in memory).
- **CSRF** — a per-process `secrets.token_urlsafe(32)` token served by
  `GET /api/csrf` and sent on every mutating request as
  `X-Recap-Token`. Same token is embedded in the legacy HTML forms.
- **Run-slot semaphore** — a single `threading.Semaphore(1)` named
  `_run_slot` caps concurrent `recap run` dispatches. Both the legacy
  `POST /run` and `POST /api/jobs/start` share it.
- **Test-only shim** — `RECAP_API_STUB_JOB_START=1` (opted into only
  by `scripts/verify_api.py`) lets the verifier prove `POST
  /api/jobs/start` routing without spawning a real `recap ingest` +
  `recap run`. The flag is intentionally undocumented in
  product-facing surfaces.
- **Recording uploads** are stored under `<--sources-root>/recording-
  <UTC>-<hex>.<ext>` with server-picked names, never browser-picked.
  Traversal-style `Content-Disposition` headers are ignored.

## 6. Local-first invariants

- **Single process, single machine.** No queues, no workers, no
  message buses. The HTTP server and the subprocess stages run in the
  same process tree.
- **Default bind is `127.0.0.1`.** Remote binding is deferred to the
  "Linux self-host + reverse proxy" roadmap slice. There is no
  authentication layer today; access control is "localhost only."
- **Cloud providers are always opt-in.** Default transcription is
  offline (`faster-whisper`), default insights are deterministic
  (`mock`). Every cloud path fails cleanly when its env key is missing
  and has an offline counterpart.
- **No vendored third-party source.** UX patterns from Cap5,
  CapSoftware/Cap, and steipete/summarize are re-implemented in
  Recap's own stack. See [docs/ux_inspiration.md](docs/ux_inspiration.md).
- **Automated tests never call a real cloud provider.** Deepgram /
  Groq / Gemini interactions are exercised against mocks or static
  assertions; CI runs entirely offline.

## 7. Validation harness

Three stdlib validators guard the contract on every commit. They live
under `scripts/` and run offline:

- **`scripts/verify_reports.py`** — exercises `recap assemble`,
  `recap export-html`, and `recap export-docx` against
  `scripts/fixtures/minimal_job/` plus negative / malformed cases and
  a static pin on `recap run` composition and `job.STAGES`.
- **`scripts/verify_ui.py`** — spawns `recap ui` against a temp copy
  of the fixture and walks the legacy HTML routes + whitelisted
  static artifacts + POST surfaces.
- **`scripts/verify_api.py`** — spawns `recap ui` and exercises the
  JSON API end-to-end, including `/api/sources`, `/api/engines`,
  `/api/jobs/start` (with the test-only shim),
  `/api/jobs/<id>/speaker-names`, `/api/jobs/<id>/insights`, and
  `/api/recordings` (missing CSRF → 403, bad type → 415, oversized
  Content-Length → 413, happy-path round-trip into `/api/sources`,
  ignored traversal filename, short body → 400).

The Vitest suite under `web/` exercises every React surface (cards,
legend, search, transcript table, jobs index, new-job page, recording
panel). Vitest never calls the real network.

## 8. Out of scope for now

The following are intentionally **not** built yet. They live in
[docs/product_roadmap.md](docs/product_roadmap.md) with rationale:

- Postgres / MinIO / worker queues / Docker compose.
- Authentication, account model, or multi-tenancy.
- Remote binding beyond `127.0.0.1`.
- Drag-and-drop upload of pre-existing video files (separate from
  live recording).
- Streaming progress (SSE / WebSocket) during `recap run`.
- Playwright end-to-end coverage.
- Tailwind, TW Elements, Tabler, icon libraries, or any CSS/JS UI kit
  as a runtime dependency — those repos are referenced only as
  inspiration.
