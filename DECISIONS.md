# Decisions

This file records accepted decisions, their rationale, and the
alternatives we explicitly rejected. Decisions from the original
pipeline design are preserved at the bottom under **Historical
pipeline decisions** — they are still load-bearing for how stages
behave; they just predate the web app and cloud-provider slices.

For the ordered product slices, see
[docs/product_roadmap.md](docs/product_roadmap.md). For current
architecture, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Current accepted decisions

### A1. Local-first file-per-job over Postgres/MinIO/worker queues

**Decision:** Persist all job state on the local filesystem under
`jobs/<job_id>/`. Every stage reads inputs from disk and writes outputs
as named artifacts (`<file>.tmp` → `os.replace`). No Postgres, no
MinIO/S3, no Celery/RQ/queue, no Redis, no Docker compose.

**Rationale:**
- Recap targets single-user / single-machine workloads. Introducing a
  database + object store + worker pool multiplies moving parts by an
  order of magnitude for zero immediate user benefit.
- Artifacts-on-disk are trivially inspectable (`cat transcript.json`)
  and rerunable (delete the file, rerun the stage).
- Atomic `<file>.tmp` + `os.replace` is simpler than transactional
  databases when each stage owns exactly one artifact.

**Rejected alternatives:**
- **Postgres-backed job state.** Would require migrations, a
  connection pool, and a second deployment step. Blocked on a real
  multi-user scenario.
- **MinIO / S3 for artifacts.** Adds a second authentication surface
  and a network round-trip for `ffmpeg`/`faster-whisper`/`OpenCLIP`
  to fetch inputs. Not worth it for one-box installs.
- **Celery / RQ worker pool.** The `_run_slot` semaphore plus
  per-job locks already serialize the two places that need it
  (`recap run`, the rich-report chain). A queue buys us nothing we
  don't already have.

**Revisit when:** a real multi-user or remote deployment becomes the
primary target. Today it's not.

### A2. React/Vite SPA alongside the legacy HTML dashboard

**Decision:** Ship a React 18 + Vite + TypeScript SPA at `/app/*`
while keeping the original stdlib-rendered HTML routes (`/`, `/new`,
`/job/<id>/`, `POST /run`, `/job/<id>/run/<stage>`, rich-report) live.

**Rationale:**
- Legacy routes are load-bearing: they work without JavaScript, are
  fully covered by `scripts/verify_ui.py`, and let us roll back any
  individual React slice without breaking users mid-run.
- A co-existing legacy surface also enforces discipline: anything the
  React app does must also be reachable some other way (CLI or HTML
  form).

**Rejected alternatives:**
- **"React-only, delete legacy"**. Blocked on (a) verifier coverage
  parity for every React screen and (b) an explicit user green-light.
  Regressing a legacy route requires that green-light today.
- **Server-rendered React (SSR/Next.js)**. Would introduce a Node
  runtime dependency and a second server process. Not worth it for a
  local-first tool.

**Revisit when:** the React surface covers every legacy route *and*
users stop relying on the no-JS fallback.

### A3. Deepgram + Groq as priority cloud providers

**Decision:** When a user opts into a cloud engine, Recap speaks to
**Deepgram** for diarized transcription (`--engine deepgram`,
`DEEPGRAM_API_KEY` + `DEEPGRAM_MODEL` + `DEEPGRAM_BASE_URL`) and to
**Groq** for structured insights (`recap insights --provider groq`,
`GROQ_API_KEY` + `GROQ_MODEL` + `GROQ_BASE_URL`). Both integrations
speak stdlib HTTP, validate JSON strictly, and fail cleanly on a
missing key.

**Rationale:**
- Both services have low latency, reasonable pricing, and JSON-mode
  outputs that avoid long prompt-engineering tails.
- `faster-whisper` (default, local) and the `mock` insights provider
  (deterministic, offline) cover the offline path completely. Neither
  cloud provider is *required* for Recap to produce a useful report.
- Stdlib HTTP keeps `requirements.txt` unchanged — no new vendor SDK
  on the critical path.

**Rejected alternatives:**
- **OpenAI / Anthropic / Gemini as the default insights provider.**
  Groq's JSON mode and latency profile were the clearest fit for the
  first slice. Additional providers can be added behind the same
  `load_provider(name)` seam; they are not on the current roadmap.
- **Vendor SDKs (`deepgram-sdk`, `groq`, etc.).** Adds a runtime
  dependency and ties Recap to each vendor's release cadence.
- **AssemblyAI / Rev.ai.** Not currently selected; may be reconsidered
  once Deepgram integration ships diarization-quality overrides.

### A4. Browser recording via MediaRecorder, stored under `--sources-root`

**Decision:** The "Record screen" tab on `/app/new` uses
`navigator.mediaDevices.getDisplayMedia` + the browser's
`MediaRecorder`. `POST /api/recordings` accepts a raw `video/webm` or
`video/mp4` body bounded at 2 GiB, streams it to
`<sources-root>/recording-<UTC>-<hex>.<ext>` in 256 KiB chunks under a
server-picked filename, and returns JSON the React client already
understands as a `sources-root` source.

**Rationale:**
- Reusing the sources root means zero new plumbing: the recording
  appears in `GET /api/sources` and `POST /api/jobs/start` consumes
  it via the existing `{"source": {"kind": "sources-root", "name":
  "..."}}` shape.
- Server-picked names mean the browser cannot choose a colliding or
  traversing filename via `Content-Disposition` tricks.
- Streaming to disk in 256 KiB chunks keeps memory use flat on a
  2 GiB upload.

**Rejected alternatives:**
- **Native app / Tauri wrapper.** Out of scope. Recap is a browser
  workspace, not a native recorder.
- **A separate `recordings/` source kind.** Would duplicate source
  discovery without buying anything.
- **`multipart/form-data` with Python's stdlib.** The stdlib multipart
  parser is fragile for 2 GiB bodies; a raw body is simpler and safer.
- **Third-party upload target (S3 presigned URL, etc.).** Breaks the
  local-first invariant. No bytes leave the user's machine.

### A5. `recap run` stays Phase-1 only; rich stages stay opt-in

**Decision:** `recap run` remains `ingest → normalize → transcribe →
assemble`. `recap/job.py::STAGES` remains `("ingest", "normalize",
"transcribe", "assemble")`. Every opt-in stage (`scenes`, `dedupe`,
`window`, `similarity`, `chapters`, `rank`, `shortlist`, `verify`,
`insights`, `export-html`, `export-docx`) is invoked on its own via
the CLI or the dashboard rich-report chain.

**Rationale:**
- A reliable 4-stage core means `recap run` is the same command on
  every machine, fast on any input, and diagnosable from four
  artifacts.
- Opt-in stages can change, break, or be replaced without affecting
  the Phase-1 guarantee.
- `scripts/verify_reports.py` statically pins both `STAGES` and the
  `cmd_run` composition, so accidental regressions fail CI.

**Rejected alternatives:**
- **Auto-run the full 11-stage chain on every `recap run`.** Would
  make the golden path depend on OpenCLIP, Tesseract, PySceneDetect,
  optional VLM access, etc. Any missing dep would break ingest for
  everyone. Not worth it.
- **Move `insights` into `STAGES`.** Blocked on export-consumer
  completeness: exports still render fallback `Speaker N` even when
  the overlay names are set. Until overlays are fully honored by
  exports, pushing insights into the core would lie about the output.

### A6. No CSS/UI-kit runtime dependencies (Tailwind, Tabler, TW Elements)

**Decision:** Recap ships plain CSS with custom-property tokens in
`web/src/index.css`. No Tailwind, no TW Elements, no Tabler, no
Bootstrap, no icon library, no UI kit. The repos listed in
[docs/ux_inspiration.md](docs/ux_inspiration.md) are reference-only.

**Rationale:**
- The full CSS budget today is small enough to hold in one file with
  custom properties for surfaces / ink / lines / brand / accent /
  status / elevation / radii / typography / focus ring, plus a
  `prefers-reduced-motion` guard.
- Tailwind would drag in a build step beyond Vite's existing
  pipeline and bloat the single CSS bundle.
- TW Elements and Tabler pull in JS/CSS bundles that would need to be
  audited, versioned, and shipped alongside `web/dist/`.

**Rejected alternatives:**
- **Adopt Tailwind now.** Blocked on a demonstrated need (currently
  none).
- **Inline SVG icon set (lucide/feather/etc.).** Blocked on zero-dep
  discipline; we can always add per-page inline SVGs when a slice
  actually needs one.

**Revisit when:** a slice genuinely needs a component we can't build
with the existing tokens in under ~50 lines of CSS, *and* the slice
owner has justified the tax.

### A7. Validation is enforced by three stdlib scripts

**Decision:** `scripts/verify_reports.py`, `scripts/verify_ui.py`, and
`scripts/verify_api.py` are the source of truth for "the contract is
intact." They are stdlib-only, offline, and run twice in a row to
catch idempotency regressions.

**Rationale:**
- Stdlib-only keeps the validator matrix cheap to run on any machine
  with Python 3.12 + `python-docx`.
- Running twice surfaces stage rerun bugs that a single pass would
  miss.
- The validators pin the things that hurt if they regress: composition
  of `cmd_run`, the contents of `STAGES`, every JSON-API route shape,
  every legacy HTML route, the speaker-names overlay atomicity, the
  recording-upload safety model.

**Rejected alternatives:**
- **Headless browser (Playwright) validators in the same slice.**
  Deferred to the dedicated "Playwright coverage" roadmap slice so it
  can own the CI-time cost.
- **pytest.** The three stdlib scripts are simpler to reason about
  for end-to-end black-box checks and avoid a new runtime dependency.

---

## Historical pipeline decisions

These are the original design decisions from the pre-web-app era. They
still apply — the stages they govern are the same stages Recap ships
today — they just predate the React, API, and cloud-provider work.

### H1. Use a staged cascade instead of end-to-end multimodal processing

**Decision:** Build the system as a staged pipeline that progressively
reduces data before applying more expensive analysis.

**Rationale:** Keeps cost and latency bounded, makes intermediate
outputs inspectable, and avoids sending entire videos to expensive
models.

### H2. Markdown is the primary document format

**Decision:** Use Markdown as the assembly target; DOCX and HTML are
downstream conversions that mirror the Markdown structure.

**Rationale:** Markdown is practical for inspection, versioning, and
pipeline handoff. `report.md` is byte-compatible with the no-insights
path and grows an `## Overview` + per-chapter enrichments only when
`insights.json` is present.

### H3. Phase 1 is intentionally narrow

**Decision:** Ship ingest, normalization, transcription, and basic
Markdown output as the reliable Phase-1 core. Keep optional
visual/semantic/VLM stages opt-in.

**Rationale:** Prevents the golden path from depending on OpenCLIP,
Tesseract, PySceneDetect, or VLM access. Still the current posture
(see A5).

### H4. Visual selection is a later pipeline concern, not Phase 1

**Decision:** Keep screenshot extraction / selection out of `recap
run`. Preserve the architecture for the optional stages.

**Rationale:** The initial deliverable must be buildable without
vision tooling. The current opt-in chain (`scenes` → `dedupe` →
`window` → `similarity` → `chapters` → `rank` → `shortlist` →
`verify`) matches this decision.

### H5. Use transcript and visual evidence together

**Decision:** Score screenshots with both transcript context and
visual novelty instead of relying on a single signal source.

**Rationale:** Avoids transcript-only misses (no UI shift cue) and
vision-only misses (no spoken-intent cue). Still enforced by `recap
rank` + `recap verify` inputs.

### H6. VLM usage is finalists-only

**Decision:** VLM verification runs only on the top 1–3 candidate
frames per chapter.

**Rationale:** Preserves the cost-controlled, open-source-first
posture. `recap verify` reads `frame_shortlist.json` and only
verifies frames with `decision in {"hero","supporting"}`.

### H7. Persist explicit per-job artifacts

**Decision:** Every stage writes a named artifact. Intermediate files
are not ephemeral.

**Rationale:** Inspectability, restartability, and a trivial mental
model. The validation harness depends on this.

### H8. Reject fixed-interval screenshot capture

**Decision:** Do not sample screenshots at regular time intervals.

**Rationale:** Produces redundant low-context results and misses
semantically important moments. Still a hard anti-pattern in
[AGENTS.md](AGENTS.md).
