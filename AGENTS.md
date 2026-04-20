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

## Status

- **Phase 1 (Reliable Core) is complete and shipped on `main`.** Every
  Phase 1 stage (ingest / normalize / transcribe / assemble) runs,
  persists artifacts, and is restartable.
- **Phase 2 (Smart Visuals v1) is complete:** `recap scenes`, `recap
  dedupe`, and all associated artifacts are live and covered by
  `scripts/verify_reports.py` / `scripts/verify_ui.py`.
- **Phase 3 (Semantic Alignment) slices are live:** `recap window`,
  `recap similarity`, `recap chapters`, `recap rank`, and `recap
  shortlist`.
- **Phase 4 (Precision Polish) slices are live:** `recap verify`,
  `recap export-html`, `recap export-docx`.
- **Modern web app is live:** a React/Vite frontend under `/app/`
  (polished visual system + transcript workspace + jobs index +
  transcript search + speaker filter chips), plus a JSON API
  (`/api/csrf`, `/api/jobs`, `/api/jobs/<id>`, `/api/jobs/<id>/
  transcript`, `/api/jobs/<id>/speaker-names`). The legacy HTML
  dashboard at `/` remains live as a fallback.
- **Structured insights is live (opt-in):** `recap insights --provider
  mock|groq` writes `insights.json`; `recap assemble` / `export-html` /
  `export-docx` render an `## Overview` section and per-chapter
  enrichments when it is present. `insights` is NOT in `job.STAGES`
  and NOT invoked by `recap run`.

`recap run` composition remains `ingest → normalize → transcribe →
assemble` and `recap/job.py STAGES` remains `("ingest", "normalize",
"transcribe", "assemble")`. Neither may change without an explicit
green-light from the user.

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

A completed job may contain any subset of:

- `original.ext`, `metadata.json`, `job.json`
- `analysis.mp4`, `audio.wav`
- `transcript.json`, `transcript.srt`
- `scenes.json`, `candidate_frames/`
- `frame_scores.json`, `frame_windows.json`,
  `frame_similarities.json`, `frame_ranks.json`,
  `frame_shortlist.json`
- `chapter_candidates.json`, `selected_frames.json`
- `speaker_names.json` (overlay; mutates only via
  `POST /api/jobs/<id>/speaker-names` or a future editor)
- `insights.json` (opt-in)
- `report.md`, `report.html`, `report.docx`

Each file's writer lives in `recap/stages/<stage>.py` or `recap/ui.py`.
Readers must validate shape before use.

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

## Enforcement summary

Treat `MASTER_BRIEF.md` as the pipeline philosophy, `docs/
product_roadmap.md` as the live roadmap, and
`docs/ux_inspiration.md` as the UX map. Pick one roadmap slice, land
it with artifacts + validators + docs updates, and stop.
