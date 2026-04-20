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

## 3. Groq structured insights + export integration — **this slice**

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

## 4. React job detail + rich-report progress

Replace the HTML `/job/<id>/` detail page with a React surface that:

- Shows stage-by-stage status, last error per stage, and artifact
  presence at a glance.
- Streams / polls progress while `recap run` or the rich-report chain
  is executing.
- Surfaces insights summary inline (overview + quick bullets) once
  `insights.json` is present.
- Keeps the legacy HTML detail page live as a fallback.

## 5. React `/app/new` upload and start flow

Replace the HTML `/new` form with a React surface that:

- Lists sources under `--sources-root`.
- Offers engine selection (`faster-whisper` vs. `deepgram`).
- Provides progress UI while `recap run` executes.
- Lets the user jump to the transcript workspace as soon as it is
  ready without waiting for the full chain.

## 6. Browser screen recording via MediaRecorder

- Record screen + audio directly in the browser.
- Upload the resulting MP4 and start a job in one flow.
- Stay local-first: no third-party upload targets, no remote auth.

## 7. Folder / project / job organization

- Rename a job (edit `original_filename` + visible title).
- Move a job between folders / projects.
- Archive a job (hide from the default index, never delete).
- Keep `jobs/<id>/` directory layout stable; organization lives in a
  sidecar index file.

## 8. Chapter sidebar + editable chapter titles

- Sidebar that lists chapters + active-chapter highlight.
- Inline edit of chapter titles (persisted next to insights).
- Jump-to-chapter in the player.

## 9. Selected-speaker playback

- Toggle: "play only segments where Speaker N speaks."
- Driven entirely client-side from the existing transcript + speaker
  overlay.

## 10. Transcript correction / notes overlay

- Per-segment note / correction field stored alongside
  `speaker_names.json` in a new overlay file.
- Exports can optionally include the corrected text.

## 11. Webhooks / streaming progress / SSE

- Server-Sent Events channel for job progress.
- Optional outbound webhook on stage transitions for self-hosted
  automations.

## 12. Linux hosting docs / systemd / reverse proxy

- End-to-end doc for running Recap on a Linux box.
- Sample `systemd` unit.
- Reverse-proxy notes covering Host pinning and CSRF.
- TLS guidance.

## 13. Playwright browser coverage

- Headless Playwright tests exercising the full React surface against
  a real `recap ui` process.
- Smoke-run the golden path end to end on every CI build.

---

Slices after this point will be triaged once the first seven are in.
Candidate follow-ups include: exporter integration for transcript
notes (slice 10 → reports), multi-voice voiceover on export, and
pluggable LLM providers beyond Groq.
