# AGENTS.md

This file tells an implementation agent how to work on Recap today.

## Sources of truth

- **Pipeline philosophy** — [MASTER_BRIEF.md](MASTER_BRIEF.md) is the
  long-form description of the staged cascade: cheap deterministic
  filters first, semantic alignment on a reduced set, expensive AI only
  on a small shortlist, Markdown-first outputs. It is background
  reading and still the north star for how stages behave.
- **Active roadmap** — [docs/product_roadmap.md](docs/product_roadmap.md)
  is the ordered list of slices in flight or planned. When a task maps
  to a slice, use that number; when it does not, be honest about it.
- **UX inspiration** — [docs/ux_inspiration.md](docs/ux_inspiration.md)
  names the external repos (Cap5, CapSoftware/Cap, steipete/summarize)
  whose product patterns we borrow and the "borrow patterns, not code"
  rule. Do not vendor third-party code.

If any document here conflicts with the user's most recent instruction
in the conversation, the user's instruction wins. If the agent-level
docs conflict with each other, the order above is authoritative.

## Status (current on `main`)

Recap has moved well past the original "Phase 1 only" posture — the
full opt-in stage chain (`scenes` → `dedupe` → `window` →
`similarity` → `chapters` → `rank` → `shortlist` → `verify`),
structured insights, and the React SPA are all live. The Phase
numbers in the original [MASTER_BRIEF.md](MASTER_BRIEF.md) are kept as
*pipeline-design* vocabulary; they are **not** a description of what
`recap run` does today.

- **Phase-1 core (`recap run` = ingest → normalize → transcribe →
  assemble)** is implemented, audited, and frozen. `recap/cli.py`
  `cmd_run` composition and `recap/job.py::STAGES` are statically
  pinned by `scripts/verify_reports.py`.
- **Opt-in visual/semantic/VLM stages live:** `recap scenes`,
  `recap dedupe`, `recap window`, `recap similarity`, `recap
  chapters`, `recap rank`, `recap shortlist`, `recap verify`.
- **Opt-in insights live:** `recap insights --provider mock|groq`
  writes `insights.json`; `recap assemble` / `export-html` /
  `export-docx` render an `## Overview` section and per-chapter
  enrichments when present. `insights` is **not** in `STAGES` and
  **not** invoked by `recap run`.
- **Optional reports live:** `recap export-html` → `report.html`,
  `recap export-docx` → `report.docx`.
- **Modern web app (React 18 + Vite + TypeScript + plain CSS) is
  live** at `/app/*`. Routes: `/app/` (jobs index), `/app/new`
  (start a job — sources pick, **Record screen** via
  `getDisplayMedia` + `MediaRecorder`, absolute-path fallback, engine
  selector), `/app/job/<id>` (dashboard), `/app/job/<id>/transcript`
  (transcript workspace with speaker colors, filter chips, search,
  rename). The legacy HTML dashboard at `/`, `/new`, and
  `/job/<id>/` remains live as a fallback.
- **JSON API** (Host-pinned, CSRF-guarded): `/api/csrf`,
  `/api/sources`, `/api/engines`, `/api/jobs`, `/api/jobs/<id>`,
  `/api/jobs/<id>/transcript`, `/api/jobs/<id>/insights`,
  `/api/jobs/<id>/speaker-names` (GET/POST), `/api/jobs/start`
  (POST), `/api/recordings` (POST, 2 GiB stream-to-disk upload).
- **Priority cloud providers:** Deepgram for diarized transcription
  (`--engine deepgram`, `DEEPGRAM_API_KEY`) and Groq for structured
  insights (`recap insights --provider groq`, `GROQ_API_KEY`). Both
  fail cleanly with no key and have offline counterparts.

`recap run` composition and `recap/job.py STAGES` are frozen. Neither
may change without an explicit green-light from the user.

## Priority cloud providers

Recap is local-first. When a slice needs a cloud provider, start with
these:

- **Deepgram** (`--engine deepgram`) for diarized transcription.
  Reads `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL`, `DEEPGRAM_BASE_URL`.
- **Groq** (`recap insights --provider groq`) for structured
  summaries. Reads `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_BASE_URL`.

Both providers must fail cleanly when their key is missing, must not
be required for offline work (mock providers exist), and must not be
called by automated tests.

## What an implementation agent should do

1. **Work one slice at a time.** Pick the smallest scope that
   completes a task from `docs/product_roadmap.md` or a direct user
   request. Bundling multiple slices into one commit is not allowed.
2. **Keep Phase 1 invariants intact.** `recap run` composition and
   `job.STAGES` are frozen. Opt-in stages add themselves as entries
   inside `state["stages"]` (via `update_stage`) but must never be
   added to `STAGES` or to `cmd_run`.
3. **Preserve legacy HTML routes while the React migration continues.**
   Deleting or regressing a legacy route requires an explicit user
   green-light. Cross-reference `docs/product_roadmap.md` before any
   such change.
4. **Write artifacts to disk after each stage.** No in-memory-only
   pipelines. Use an atomic `<file>.tmp` → replace write. Validate
   the artifact shape on load.
5. **Prefer direct code over abstractions.** No plugin registries, no
   generic workflow frameworks, no interface hierarchies for
   hypothetical future providers. If three similar cases appear,
   refactor then; not before.
6. **Keep data structures explicit and inspectable.** Plain JSON for
   artifacts. No opaque binary state.
7. **Never vendor third-party source.** Borrow product patterns from
   the repos listed in `docs/ux_inspiration.md`; do not copy code,
   icons, fonts, or prompts.
8. **Secrets discipline.** API keys, prompt bodies, transcript text,
   and request bodies must never be logged, written to `job.json`,
   or included in exception messages. Error messages may carry HTTP
   status codes and short (<= 200 byte) response snippets only.

## Validation every slice must pass

Before committing:

- `git diff --check` must be clean.
- `.venv/bin/python -m compileall -q recap`
- `.venv/bin/python scripts/verify_reports.py` (twice, to catch
  idempotency bugs)
- `.venv/bin/python scripts/verify_ui.py` (twice)
- `.venv/bin/python scripts/verify_api.py` (twice)
- `cd web && npm run build` (typecheck + Vite bundle)
- `cd web && npm test -- --run`
- `cd web && npm audit --audit-level=moderate` must report 0
  vulnerabilities.
- `scripts/fixtures/*` must be byte-identical afterwards.
- `git diff requirements.txt pyproject.toml` must be empty.
- A secret scan over the changed source and docs (excluding
  `web/node_modules`, `web/dist`, `web/package-lock.json`) must be
  clean.

## Artifact layout

A completed job directory (`jobs/<job_id>/`) may contain any subset of:

- `original.ext`, `metadata.json`, `job.json`
- `analysis.mp4`, `audio.wav`
- `transcript.json`, `transcript.srt`
- `scenes.json`, `candidate_frames/`
- `frame_scores.json`, `frame_windows.json`,
  `frame_similarities.json`, `frame_ranks.json`,
  `frame_shortlist.json`
- `chapter_candidates.json`, `selected_frames.json`
- `speaker_names.json` (overlay; mutates only via
  `POST /api/jobs/<id>/speaker-names`)
- `insights.json` (opt-in overlay)
- `report.md`, `report.html`, `report.docx`

Each file's writer lives in `recap/stages/<stage>.py` or `recap/ui.py`.
Readers must validate shape before use. Overlays (`speaker_names.json`,
`insights.json`) never mutate `transcript.json` or any other upstream
artifact.

**Browser recordings** live outside the per-job directory: they are
stored directly under `<--sources-root>/recording-<UTC>-<hex>.<ext>`
so they appear in `GET /api/sources` and can be consumed by
`POST /api/jobs/start` without inventing a new source kind. The
browser-supplied filename is never trusted.

## Stop conditions

Stop and ask before continuing when:

- A request would change `job.STAGES` or `cmd_run` composition.
- A request would add a new Python runtime dependency
  (`requirements.txt` / `pyproject.toml` change).
- A request would delete a legacy HTML route while the React migration
  is still in progress.
- A request would touch `scripts/fixtures/*` or any real job under
  `jobs/*`.
- A request would bypass the verifier suite or weaken a contract check.

## Anti-patterns

- Do not capture screenshots at fixed time intervals.
- Do not feed entire raw videos to a VLM.
- Do not build a vision-only system that ignores transcript context,
  or a transcript-only system that ignores the visual stages.
- Do not add a new LLM provider without a matching `mock` provider
  that works offline.
- Do not introduce speculative abstractions for future slices. Land
  one slice, then refactor if the next slice demands it.
- Do not swallow errors silently. Opt-in stages fail cleanly with a
  short one-line message and leave no `.tmp` files behind.

## Future slice order (at the time of this doc)

The authoritative, versioned list lives in
[docs/product_roadmap.md](docs/product_roadmap.md). At the time of
this writing the next slices — in order — are:

1. **Screenshot / frame review UI** (slice 8). Inline review of
   `selected_frames.json` hero/supporting choices with keep/reject
   overrides written as an overlay.
2. **Exporters honor overlays fully** (slice 9). `recap assemble` /
   `export-html` / `export-docx` render `speaker_names.json` labels
   and any `chapter_titles.json` overlay titles, not the fallback
   `Speaker N` / upstream chapter title.
3. **Folders / projects / archive** (slice 12). Rename / move /
   archive jobs via a sidecar index file; `jobs/<id>/` layout stays
   stable.
4. **Live progress (SSE / polling) + webhooks** (slice 13). Upgrade
   the 4b polling loop to a push transport when run budgets grow
   past a few minutes.
5. **Linux self-host / deploy hardening** (slice 14). End-to-end
   host docs, a `systemd` unit, reverse-proxy notes covering Host
   pinning + CSRF, TLS guidance.
6. **Single-user / reverse-proxy auth** (slice 15). Minimal auth
   surface so Recap can safely bind beyond `127.0.0.1`. Gated on
   slice 14.

Slices that are explicitly **not next** until the list above moves:
drag-and-drop upload of pre-existing files, dark mode, Playwright
coverage, multi-tenant accounts, cloud-sync targets, native-app
wrappers.

## Enforcement summary

Treat [MASTER_BRIEF.md](MASTER_BRIEF.md) as the pipeline philosophy
(historical north star),
[docs/product_roadmap.md](docs/product_roadmap.md) as the live
roadmap, [ARCHITECTURE.md](ARCHITECTURE.md) as the current system
shape, [PRD.md](PRD.md) as the current product target,
[DECISIONS.md](DECISIONS.md) as the accepted-decisions log, and
[docs/ux_inspiration.md](docs/ux_inspiration.md) as the UX map. Pick
one roadmap slice, land it with artifacts + validators + docs
updates, and stop.
