"""Local web dashboard for Recap jobs.

Served via `recap ui --host 127.0.0.1 --port 8765 --jobs-root jobs
[--sources-root sample_videos]`. Local-first and stdlib-based:
`http.server.ThreadingHTTPServer` plus a custom
`BaseHTTPRequestHandler`, no new runtime dependencies, no external
CSS/JS, no network calls.

GET routes are strictly read-only. They render the jobs index and
per-job detail pages, serve whitelisted artifacts (report.md /
report.html / report.docx, job.json, transcript.*, the
selected/chapter JSONs, and `candidate_frames/*.{jpg,jpeg,png}`)
directly from disk, render a "start new job" page at `/new`, and
render last-run result pages at `/job/<id>/run/<stage>/last` for
stages in `_LAST_RESULT_STAGES`. Non-whitelisted filenames and any
URL containing a `..` segment or resolving outside the jobs root
return 404.

Two narrow POST surfaces exist, both CSRF-protected and
Host-pinned:

1. `POST /job/<id>/run/<stage>` re-runs exactly one of three
   exporters — `assemble`, `export-html`, `export-docx` — via
   `subprocess.run([sys.executable, "-m", "recap", stage, "--job",
   <dir>, "--force"], ...)`. Per-job `threading.Lock`, 60 s
   subprocess timeout, 8 KiB UTF-8 stdout/stderr truncation.

2. `POST /run` starts a new `recap run` from a video path under the
   configured `sources_root`. The handler synchronously invokes
   `python -m recap ingest` (120 s timeout), parses the new job
   directory from its stdout, then spawns a daemon thread that
   runs `python -m recap run --job <dir>` via `subprocess.Popen`
   under a 1-hour `communicate(timeout=3600)` cap. A global
   `threading.Semaphore(1)` caps concurrent runs at one across the
   whole server. Results are cached in memory at
   `_last_run[(job_id, "run")]`. On success the handler 303
   redirects to the new job's detail page.

Every POST is validated in this order: Host header equal to the
bound `host:port` via `secrets.compare_digest`, Content-Length
required and ≤ 4096 bytes, CSRF token matched with
`secrets.compare_digest`, then path- and semantic-specific
validation. Rejected POSTs log one short reason to the server's
log stream; the form body, CSRF token, env vars, and captured
subprocess output are never logged.

`recap run` composition and `job.STAGES` are unchanged. This module
imports no stage `run()` function — the module-under-test boundary
stays at the CLI. `run` appears in `_LAST_RESULT_STAGES` for the
read-only results route but is NOT in `_RUNNABLE_STAGES`, so there
is no per-job POST surface for `recap run` beyond the single
`POST /run` entry.
"""

from __future__ import annotations

import html
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import IO

from .stages.report_helpers import (
    collapse_whitespace,
    format_ts,
    is_safe_frame_file,
    validate_chapter_candidates,
    validate_selected_frames,
)


REPO_ROOT = Path(__file__).resolve().parent.parent

# The only stages that can be executed via a POST from the dashboard.
# Any path outside this allowlist returns 404 and never spawns a
# subprocess. `recap run` and every opt-in pipeline stage (`scenes`,
# `dedupe`, `window`, `similarity`, `chapters`, `rank`, `shortlist`,
# `verify`) remain CLI-only by design.
_RUNNABLE_STAGES: frozenset[str] = frozenset({
    "assemble", "export-html", "export-docx",
})

# Stages whose `/job/<id>/run/<stage>/last` last-result page is
# serveable. `run` is included so the background `recap run` thread
# started via `POST /run` has a visible results page, but it is NOT
# in `_RUNNABLE_STAGES` — users cannot POST to `/job/<id>/run/run`.
_LAST_RESULT_STAGES: frozenset[str] = _RUNNABLE_STAGES | frozenset({"run"})

# Video file extensions accepted by `POST /run` for a browser-started
# `recap run`. Enforced after the source path has been resolved under
# `sources_root`.
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".m4v",
})

_POST_BODY_MAX = 4096            # bytes
_OUTPUT_TRUNCATE_BYTES = 8192    # stdout/stderr cap, UTF-8 bytes
_SUBPROCESS_TIMEOUT = 60.0       # seconds (per-stage rerun)
_LOCK_ACQUIRE_TIMEOUT = 2.0      # seconds (per-job rerun lock)
_INGEST_TIMEOUT = 120.0          # seconds (synchronous ingest)
_FULL_RUN_TIMEOUT = 3600.0       # seconds (background `recap run`)

# One concurrent `recap run` across the whole server. Acquired at POST
# time via `_run_slot.acquire(blocking=False)` and released by the
# background thread when the subprocess ends.
_run_slot = threading.Semaphore(1)

# Chunk size used when streaming ranged video responses.
_RANGE_CHUNK_BYTES = 64 * 1024


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single-range `Range: bytes=<spec>` header.

    Returns a `(start, end)` inclusive pair within `[0, size - 1]` when
    the header specifies a single satisfiable range. Returns None when
    the header is absent, malformed, multi-range, or not `bytes=` —
    the caller should fall back to a 200 full-body response.

    Raises `ValueError` with ``"unsatisfiable"`` when the header is a
    valid single-range syntax but cannot be served against `size`;
    the caller should respond with `416 Range Not Satisfiable`.
    """
    if not header:
        return None
    header = header.strip()
    if not header.lower().startswith("bytes="):
        return None
    spec = header[len("bytes="):].strip()
    if not spec or "," in spec:
        return None
    if "-" not in spec:
        return None
    lo_str, _, hi_str = spec.partition("-")
    lo_str = lo_str.strip()
    hi_str = hi_str.strip()
    if size <= 0:
        # Nothing to serve ranged from a zero-byte file; fall back.
        return None
    try:
        if lo_str == "" and hi_str != "":
            # Suffix range: bytes=-n → last n bytes.
            n = int(hi_str)
            if n <= 0:
                return None
            start = max(0, size - n)
            end = size - 1
        elif lo_str != "" and hi_str == "":
            # Prefix range: bytes=a-
            start = int(lo_str)
            if start < 0:
                return None
            if start >= size:
                raise ValueError("unsatisfiable")
            end = size - 1
        elif lo_str != "" and hi_str != "":
            start = int(lo_str)
            end = int(hi_str)
            if start < 0 or end < 0 or start > end:
                return None
            if start >= size:
                raise ValueError("unsatisfiable")
            if end >= size:
                end = size - 1
        else:
            return None
    except ValueError as e:
        if str(e) == "unsatisfiable":
            raise
        return None
    return start, end

# Per-job execution locks so two POSTs to the same job serialize while
# different jobs still run in parallel. All shared state is guarded by
# `_job_locks_guard`.
_job_locks: dict[str, threading.Lock] = {}
_job_locks_guard = threading.Lock()
_last_run: dict[tuple[str, str], dict] = {}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _truncate_output(s: str, limit: int = _OUTPUT_TRUNCATE_BYTES) -> str:
    if not s:
        return s
    data = s.encode("utf-8")
    if len(data) <= limit:
        return s
    head = data[:limit].decode("utf-8", errors="ignore")
    omitted = len(data) - limit
    return head + f"\n…truncated ({omitted} bytes omitted)\n"


def _get_job_lock(job_id: str) -> threading.Lock:
    with _job_locks_guard:
        lock = _job_locks.get(job_id)
        if lock is None:
            lock = threading.Lock()
            _job_locks[job_id] = lock
        return lock


def _set_in_progress(job_id: str, stage: str, started_at: str) -> None:
    with _job_locks_guard:
        _last_run[(job_id, stage)] = {
            "started_at": started_at,
            "finished_at": None,
            "exit_code": None,
            "status": "in-progress",
            "stdout": "",
            "stderr": "",
        }


def _set_final(job_id: str, stage: str, entry: dict) -> None:
    with _job_locks_guard:
        _last_run[(job_id, stage)] = entry


def _get_last(job_id: str, stage: str) -> dict | None:
    with _job_locks_guard:
        return _last_run.get((job_id, stage))


def _background_run(job_id: str, job_dir: Path) -> None:
    """Run `python -m recap run --job <job_dir>` and store the result.

    Always releases the global `_run_slot` in the finally block.
    stdout/stderr are truncated to `_OUTPUT_TRUNCATE_BYTES`.
    """
    started_at = _now_iso()
    t0 = time.monotonic()
    try:
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "recap", "run", "--job", str(job_dir)],
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as e:
            _set_final(job_id, "run", {
                "started_at": started_at,
                "finished_at": _now_iso(),
                "exit_code": None,
                "status": "failure",
                "stdout": "",
                "stderr": _truncate_output(
                    f"failed to spawn recap run: {type(e).__name__}: {e}"
                ),
                "elapsed": time.monotonic() - t0,
            })
            return
        try:
            stdout, stderr = proc.communicate(timeout=_FULL_RUN_TIMEOUT)
            exit_code = proc.returncode
            status = "success" if exit_code == 0 else "failure"
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            exit_code = None
            status = "failure"
            stderr = (stderr or "") + (
                f"\ntimeout after {int(_FULL_RUN_TIMEOUT)}s\n"
            )
        _set_final(job_id, "run", {
            "started_at": started_at,
            "finished_at": _now_iso(),
            "exit_code": exit_code,
            "status": status,
            "stdout": _truncate_output(stdout or ""),
            "stderr": _truncate_output(stderr or ""),
            "elapsed": time.monotonic() - t0,
        })
    finally:
        _run_slot.release()


def _any_stage_running(job_data: dict) -> bool:
    if (job_data.get("status") or "") == "running":
        return True
    stages = job_data.get("stages") or {}
    if not isinstance(stages, dict):
        return False
    for entry in stages.values():
        if isinstance(entry, dict) and entry.get("status") == "running":
            return True
    return False


def _run_stage(stage: str, job_dir: Path) -> dict:
    """Invoke `recap <stage> --job <job_dir> --force` in a subprocess.

    Always returns a result dict; never raises. stdout/stderr are
    truncated to `_OUTPUT_TRUNCATE_BYTES`.
    """
    started_at = _now_iso()
    t0 = time.monotonic()
    args = [
        sys.executable, "-m", "recap", stage,
        "--job", str(job_dir), "--force",
    ]
    try:
        result = subprocess.run(
            args,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
        exit_code = result.returncode
        stdout = _truncate_output(result.stdout or "")
        stderr = _truncate_output(result.stderr or "")
        status = "success" if exit_code == 0 else "failure"
    except subprocess.TimeoutExpired as e:
        exit_code = None
        stdout = _truncate_output((e.stdout or b"").decode("utf-8", "ignore")
                                   if isinstance(e.stdout, (bytes, bytearray))
                                   else (e.stdout or ""))
        stderr = _truncate_output(
            f"timeout after {int(_SUBPROCESS_TIMEOUT)}s"
        )
        status = "failure"
    return {
        "started_at": started_at,
        "finished_at": _now_iso(),
        "exit_code": exit_code,
        "status": status,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed": time.monotonic() - t0,
    }


# Whitelisted filenames directly under a job directory. Nothing else is
# served by the static route.
_JOB_ROOT_FILES: frozenset[str] = frozenset({
    "report.md",
    "report.html",
    "report.docx",
    "metadata.json",
    "transcript.json",
    "transcript.srt",
    "job.json",
    "selected_frames.json",
    "chapter_candidates.json",
    "frame_shortlist.json",
    "frame_ranks.json",
    "frame_similarities.json",
    "frame_windows.json",
    "frame_scores.json",
    "scenes.json",
    "analysis.mp4",
})

_CANDIDATE_FRAME_EXTS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})

_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".srt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
    ".mp4": "video/mp4",
}

# Canonical ordering for the stage table. Unknown stages fall through
# and are appended alphabetically.
_STAGE_ORDER: tuple[str, ...] = (
    "ingest",
    "normalize",
    "transcribe",
    "assemble",
    "scenes",
    "dedupe",
    "window",
    "similarity",
    "chapters",
    "rank",
    "shortlist",
    "verify",
    "export_html",
    "export_docx",
)

# Short human labels shown in the artifacts section of the job page.
_ARTIFACT_LABELS: dict[str, str] = {
    "report.md": "Markdown report",
    "report.html": "HTML report",
    "report.docx": "DOCX report",
    "job.json": "Job state",
    "metadata.json": "Source metadata",
    "transcript.json": "Transcript (JSON)",
    "transcript.srt": "Transcript (SRT)",
    "selected_frames.json": "Selected frames",
    "chapter_candidates.json": "Chapter candidates",
    "frame_shortlist.json": "Frame shortlist",
    "frame_ranks.json": "Frame ranks",
    "frame_similarities.json": "Frame similarities",
    "frame_windows.json": "Frame windows",
    "frame_scores.json": "Frame scores",
    "scenes.json": "Scene boundaries",
}


_INLINE_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 1000px; margin: 2rem auto; padding: 0 1rem;
       line-height: 1.5; color: #1a1a1a; }
h1 { border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
h2 { margin-top: 2rem; border-bottom: 1px solid #eee; padding-bottom: 0.2rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee;
         vertical-align: top; }
th { background: #f7f7f7; font-weight: 600; }
code { background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 3px;
       font-size: 0.9em; }
.secondary { color: #666; font-size: 0.85em; display: block; margin-top: 0.15rem; }
.badge { display: inline-block; padding: 0.1rem 0.45rem; border-radius: 3px;
         font-size: 0.85em; font-weight: 600; }
.status-completed { background: #e6f4ea; color: #137333; }
.status-running { background: #fff4e5; color: #b06000; }
.status-failed { background: #fce8e6; color: #a50e0e; }
.status-pending { background: #eee; color: #555; }
.status-unknown { background: #eee; color: #555; }
.check { color: #137333; font-weight: 600; }
.dash { color: #aaa; }
.empty { margin: 2rem 0; color: #555; }
ul.errors { list-style: none; padding: 0; margin: 0.5rem 0; }
ul.errors li { background: #fce8e6; color: #a50e0e;
               padding: 0.5rem 0.75rem; border-radius: 3px;
               margin-bottom: 0.4rem; }
ul.errors li code { background: #fdd; color: #a50e0e; }
section.chapter-summary { margin: 1rem 0 2rem; }
section.chapter-summary h3 { margin-top: 1.5rem; }
section.chapter-summary p.snippet { color: #333; margin: 0.4rem 0 0.8rem; }
ul.thumbs { list-style: none; padding: 0;
            display: flex; flex-wrap: wrap; gap: 0.75rem;
            margin: 0.5rem 0; }
ul.thumbs li { display: inline-flex; flex-direction: column;
               align-items: center; }
img.thumb { max-width: 200px; max-height: 120px; object-fit: cover;
            border: 1px solid #ddd; border-radius: 3px; display: block; }
.thumb-label { font-size: 0.75em; padding: 0.1rem 0.45rem;
               border-radius: 3px; margin-top: 0.2rem;
               font-weight: 600; }
.thumb-hero { background: #e6f4ea; color: #137333; }
.thumb-supporting { background: #eef4ff; color: #1a56db; }
ul.actions { list-style: none; padding: 0; margin: 0.5rem 0;
             display: flex; flex-wrap: wrap; gap: 0.5rem; }
ul.actions li { margin: 0; }
ul.actions form { margin: 0; display: inline; }
ul.actions button { font: inherit; cursor: pointer; padding: 0.3rem 0.6rem;
                    border: 1px solid #bbb; border-radius: 3px;
                    background: #f7f7f7; }
ul.actions button:hover { background: #eee; }
pre.output { background: #f4f4f4; padding: 0.75rem; border-radius: 3px;
             white-space: pre-wrap; word-break: break-word;
             font-size: 0.85em; max-height: 20rem; overflow: auto; }
div.banner { padding: 0.6rem 0.8rem; border-radius: 3px;
             margin: 1rem 0; font-weight: 500; }
div.banner.running { background: #fff4e5; color: #7a4a00;
                     border: 1px solid #f5c97d; }
div.banner.error { background: #fce8e6; color: #a50e0e;
                   border: 1px solid #f2b4ae; }
a.start-new { display: inline-block; margin: 0.5rem 0;
              padding: 0.4rem 0.8rem; background: #1a56db;
              color: white; border-radius: 3px; text-decoration: none;
              font-weight: 600; }
a.start-new:hover { background: #144cc3; }
form.new-job label { display: inline-block; margin: 0.35rem 0; }
form.new-job input[type=text] { font: inherit; padding: 0.3rem; }
form.new-job select { font: inherit; padding: 0.3rem; }
table.transcript { table-layout: fixed; }
table.transcript td:first-child { width: 5em; white-space: nowrap; }
table.transcript td { vertical-align: top; }
button.ts { background: transparent; border: none; padding: 0;
            cursor: pointer; color: inherit; font: inherit; }
button.ts:hover code { background: #e8f0fe; }
tr.active { background: #fff7e0; }
tr.active td:first-child { border-left: 3px solid #f5a623;
                           padding-left: 0.45rem; }
""".strip()


# ---- helpers -------------------------------------------------------------


def _e(value: object) -> str:
    """Escape any value for safe HTML text/attribute use."""
    return html.escape("" if value is None else str(value), quote=True)


def _status_badge(status: object) -> str:
    s = status if isinstance(status, str) else "unknown"
    cls = f"status-{s}" if s in ("completed", "running", "failed", "pending") else "status-unknown"
    return f'<span class="badge {cls}">{_e(s)}</span>'


def _truncate(value: str, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _read_job_json(job_dir: Path) -> dict | None:
    try:
        with open(job_dir / "job.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _list_jobs(jobs_root: Path) -> list[dict]:
    if not jobs_root.is_dir():
        return []
    out: list[dict] = []
    for entry in sorted(jobs_root.iterdir()):
        if not entry.is_dir():
            continue
        data = _read_job_json(entry)
        if data is None:
            continue
        out.append({
            "dir": entry,
            "job_id": data.get("job_id") or entry.name,
            "created_at": data.get("created_at") or "",
            "updated_at": data.get("updated_at") or "",
            "status": data.get("status") or "",
            "original_filename": data.get("original_filename") or "",
            "error": data.get("error"),
            "mtime": entry.stat().st_mtime,
            "data": data,
        })

    def sort_key(j):
        # created_at descending, fallback to mtime descending
        return (j["created_at"] or "", j["mtime"])

    out.sort(key=sort_key, reverse=True)
    return out


def _ordered_stage_entries(stages: dict) -> list[tuple[str, dict]]:
    known = [(name, stages[name]) for name in _STAGE_ORDER if name in stages]
    extras_names = sorted(set(stages) - set(_STAGE_ORDER))
    extras = [(n, stages[n]) for n in extras_names]
    return known + extras


def _extra_cell(entry: dict) -> str:
    skip = {"status", "started_at", "finished_at", "error"}
    parts: list[str] = []
    for k in sorted(entry):
        if k in skip:
            continue
        v = entry[k]
        if isinstance(v, (dict, list)):
            rendered = json.dumps(v, separators=(",", ":"), sort_keys=True)
        else:
            rendered = "" if v is None else str(v)
        parts.append(f"{k}: {_truncate(rendered)}")
    if not parts:
        return ""
    return f"<code>{_e(', '.join(parts))}</code>"


def _page(
    title: str, body_html: str, *, refresh_seconds: int | None = None
) -> bytes:
    refresh = (
        f'<meta http-equiv="refresh" content="{int(refresh_seconds)}">\n'
        if refresh_seconds
        else ""
    )
    doc = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        + refresh
        + f"<title>{_e(title)}</title>\n"
        f"<style>{_INLINE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        + body_html
        + "\n</body>\n</html>\n"
    )
    return doc.encode("utf-8")


# ---- page renderers ------------------------------------------------------


_THUMB_LABEL: dict[str, tuple[str, str]] = {
    "selected_hero": ("hero", "thumb-hero"),
    "selected_supporting": ("supporting", "thumb-supporting"),
}

_SNIPPET_CHARS = 200


def _errors_section(stages: dict) -> list[str]:
    """Return HTML lines for failed stages, or [] when none failed."""
    if not isinstance(stages, dict):
        return []
    failed: list[tuple[str, dict]] = []
    for name, entry in _ordered_stage_entries(stages):
        if isinstance(entry, dict) and entry.get("status") == "failed":
            failed.append((name, entry))
    if not failed:
        return []
    out = ["<h2>Errors</h2>", '<ul class="errors">']
    for name, entry in failed:
        err = entry.get("error") or "unknown error"
        out.append(f"<li><code>{_e(name)}</code> — {_e(err)}</li>")
    out.append("</ul>")
    return out


def _chapters_section(
    job_dir: Path, job_id: str, logger_stream: IO | None
) -> list[str]:
    """Return HTML lines for the Chapters & selected frames block.

    Silently returns [] when either artifact is missing. On invalid JSON
    or validation failure, returns [] and logs a single line — the page
    must still render.
    """
    selected_path = job_dir / "selected_frames.json"
    chapters_path = job_dir / "chapter_candidates.json"
    if not selected_path.is_file() or not chapters_path.is_file():
        return []

    try:
        with open(selected_path, "r", encoding="utf-8") as f:
            selected_raw = json.load(f)
        selected = validate_selected_frames(selected_raw)
        with open(chapters_path, "r", encoding="utf-8") as f:
            chapters_raw = json.load(f)
        chapter_text_by_index = validate_chapter_candidates(chapters_raw)
        # Every selected chapter must have a matching entry in
        # chapter_candidates.json; otherwise the combined artifact state
        # is invalid and we skip the section rather than render a
        # partial summary.
        for ch in selected["chapters"]:
            ch_idx = ch["chapter_index"]
            if ch_idx not in chapter_text_by_index:
                raise RuntimeError(
                    "chapter_candidates.json has no chapter with index "
                    f"{ch_idx} required by selected_frames.json"
                )
    except (OSError, ValueError, RuntimeError) as e:
        if logger_stream is not None:
            logger_stream.write(
                f"[recap-ui] chapters section skipped: {e}\n"
            )
            logger_stream.flush()
        return []

    sorted_chapters = sorted(
        selected["chapters"], key=lambda c: c["chapter_index"]
    )

    out: list[str] = ["<h2>Chapters &amp; selected frames</h2>"]
    for ch in sorted_chapters:
        ch_idx = ch["chapter_index"]
        start = format_ts(ch.get("start_seconds") or 0.0)
        end = format_ts(ch.get("end_seconds") or 0.0)
        out.append('<section class="chapter-summary">')
        out.append(
            f"<h3>Chapter {_e(ch_idx)} — [{_e(start)} – {_e(end)}]</h3>"
        )

        raw_text = chapter_text_by_index.get(ch_idx, "")
        collapsed = collapse_whitespace(raw_text)
        if collapsed:
            if len(collapsed) > _SNIPPET_CHARS:
                snippet = collapsed[:_SNIPPET_CHARS] + "…"
            else:
                snippet = collapsed
            out.append(f'<p class="snippet">{_e(snippet)}</p>')

        kept: list[dict] = [
            fr for fr in ch["frames"]
            if fr.get("decision") in _THUMB_LABEL
        ]
        if not kept:
            out.append(
                '<p class="empty">No selected frames in this chapter.</p>'
            )
            out.append("</section>")
            continue

        out.append('<ul class="thumbs">')
        for fr in kept:
            frame_file = fr["frame_file"]
            # Defense in depth — validators already enforce this.
            if not is_safe_frame_file(frame_file):
                continue
            label_text, label_cls = _THUMB_LABEL[fr["decision"]]
            src = (
                f"/job/{_e(job_id)}/candidate_frames/{_e(frame_file)}"
            )
            alt = f"Chapter {ch_idx} {label_text} {frame_file}"
            out.append(
                "<li>"
                f'<a href="{src}">'
                f'<img src="{src}" alt="{_e(alt)}" '
                'loading="lazy" class="thumb">'
                "</a>"
                f'<span class="thumb-label {label_cls}">'
                f"{_e(label_text)}</span>"
                "</li>"
            )
        out.append("</ul>")
        out.append("</section>")

    return out


def render_index(jobs_root: Path) -> bytes:
    jobs = _list_jobs(jobs_root)
    body: list[str] = []
    body.append(f"<h1>Recap · jobs</h1>")
    body.append(
        '<p><a class="start-new" href="/new">Start new job</a></p>'
    )
    body.append(
        f"<p>Scanning <code>{_e(jobs_root)}</code>.</p>"
    )
    if not jobs:
        body.append(
            '<div class="empty"><p>No jobs yet.</p>'
            "<p>Create one with:</p>"
            "<p><code>recap run --source path/to/recording.mp4</code></p></div>"
        )
        return _page("Recap · jobs", "\n".join(body))

    body.append("<table>")
    body.append(
        "<thead><tr>"
        "<th>Job</th><th>Created</th><th>Status</th>"
        "<th>Artifacts</th><th>Actions</th>"
        "</tr></thead>"
    )
    body.append("<tbody>")
    for j in jobs:
        job_id = j["job_id"]
        job_dir: Path = j["dir"]
        name_cell = (
            f'<a href="/job/{_e(job_id)}/"><code>{_e(job_id)}</code></a>'
        )
        if j["original_filename"]:
            name_cell += (
                f'<span class="secondary">{_e(j["original_filename"])}</span>'
            )
        md = (job_dir / "report.md").exists()
        htmlp = (job_dir / "report.html").exists()
        docx = (job_dir / "report.docx").exists()

        def flag(has: bool, label: str) -> str:
            if has:
                return f'<span class="check">✓ {_e(label)}</span>'
            return f'<span class="dash">— {_e(label)}</span>'

        artifacts = " ".join([
            flag(md, "md"),
            flag(htmlp, "html"),
            flag(docx, "docx"),
        ])

        if htmlp:
            actions = (
                f'<a href="/job/{_e(job_id)}/report.html">Open report.html</a>'
            )
        elif md:
            actions = f'<a href="/job/{_e(job_id)}/report.md">Open report.md</a>'
        else:
            actions = '<span class="dash">—</span>'

        body.append("<tr>")
        body.append(f"<td>{name_cell}</td>")
        body.append(f"<td>{_e(j['created_at'])}</td>")
        body.append(f"<td>{_status_badge(j['status'])}</td>")
        body.append(f"<td>{artifacts}</td>")
        body.append(f"<td>{actions}</td>")
        body.append("</tr>")
    body.append("</tbody></table>")
    return _page("Recap · jobs", "\n".join(body))


def _actions_section(job_id: str, csrf_token: str) -> list[str]:
    out: list[str] = ["<h2>Actions</h2>"]
    out.append(
        '<p class="secondary">Re-run an exporter against this job. '
        "Uses <code>--force</code>; output replaces the existing report "
        "file on disk. Only these three exporters are runnable from the "
        "dashboard; every other stage stays CLI-only.</p>"
    )
    out.append('<ul class="actions">')
    for stage in ("assemble", "export-html", "export-docx"):
        out.append(
            "<li>"
            f'<form method="post" action="/job/{_e(job_id)}/run/{_e(stage)}">'
            f'<input type="hidden" name="_token" value="{_e(csrf_token)}">'
            f"<button>Rerun <code>recap {_e(stage)}</code></button>"
            "</form>"
            "</li>"
        )
    out.append("</ul>")
    links = []
    for stage in ("assemble", "export-html", "export-docx"):
        links.append(
            f'<a href="/job/{_e(job_id)}/run/{_e(stage)}/last">'
            f"{_e(stage)}</a>"
        )
    out.append(
        '<p class="secondary">Last results: ' + ", ".join(links) + "</p>"
    )
    return out


def render_job(
    jobs_root: Path,
    job_id: str,
    logger_stream: IO | None = None,
    csrf_token: str | None = None,
) -> bytes | None:
    job_dir = jobs_root / job_id
    if not job_dir.is_dir():
        return None
    data = _read_job_json(job_dir)
    if data is None:
        return None

    title = data.get("original_filename") or job_id
    is_running = _any_stage_running(data)
    body: list[str] = []
    body.append(f"<h1>Recap · {_e(title)}</h1>")

    if is_running:
        body.append(
            '<div class="banner running">'
            "Run in progress — this page refreshes every 10 s."
            "</div>"
        )

    body.extend(_errors_section(data.get("stages") or {}))

    body.append("<h2>Metadata</h2>")
    body.append("<ul>")
    body.append(f"<li>Job ID: <code>{_e(data.get('job_id') or job_id)}</code></li>")
    if data.get("original_filename"):
        body.append(
            f"<li>Source file: <code>{_e(data['original_filename'])}</code></li>"
        )
    if data.get("source_path"):
        body.append(
            f"<li>Source path: <code>{_e(data['source_path'])}</code></li>"
        )
    if data.get("created_at"):
        body.append(f"<li>Created: {_e(data['created_at'])}</li>")
    if data.get("updated_at"):
        body.append(f"<li>Updated: {_e(data['updated_at'])}</li>")
    body.append(f"<li>Status: {_status_badge(data.get('status'))}</li>")
    if data.get("error"):
        body.append(f"<li>Error: <code>{_e(data['error'])}</code></li>")
    body.append("</ul>")

    stages = data.get("stages") or {}
    if isinstance(stages, dict) and stages:
        body.append("<h2>Stages</h2>")
        body.append("<table>")
        body.append(
            "<thead><tr>"
            "<th>Stage</th><th>Status</th><th>Started</th>"
            "<th>Finished</th><th>Extra</th>"
            "</tr></thead>"
        )
        body.append("<tbody>")
        for name, entry in _ordered_stage_entries(stages):
            if not isinstance(entry, dict):
                continue
            body.append(
                "<tr>"
                f"<td><code>{_e(name)}</code></td>"
                f"<td>{_status_badge(entry.get('status'))}</td>"
                f"<td>{_e(entry.get('started_at') or '')}</td>"
                f"<td>{_e(entry.get('finished_at') or '')}</td>"
                f"<td>{_extra_cell(entry)}</td>"
                "</tr>"
            )
            if entry.get("error"):
                body.append(
                    "<tr>"
                    '<td></td><td colspan="4">'
                    f"<code>error: {_e(entry['error'])}</code>"
                    "</td></tr>"
                )
        body.append("</tbody></table>")

    if csrf_token is not None:
        body.extend(_actions_section(job_id, csrf_token))

    body.extend(_chapters_section(job_dir, job_id, logger_stream))

    if (job_dir / "transcript.json").is_file():
        body.append(
            f'<p><a href="/job/{_e(job_id)}/transcript">View transcript</a></p>'
        )

    body.append("<h2>Artifacts</h2>")
    present = [
        name for name in _JOB_ROOT_FILES if (job_dir / name).is_file()
    ]
    if not present:
        body.append('<p class="empty">No artifacts yet.</p>')
    else:
        # Put reports first in a stable order, then the rest.
        report_order = ("report.md", "report.html", "report.docx")
        primary = [n for n in report_order if n in present]
        secondary = sorted(n for n in present if n not in report_order)
        body.append("<ul>")
        for name in primary + secondary:
            size = (job_dir / name).stat().st_size
            label = _ARTIFACT_LABELS.get(name, name)
            body.append(
                f'<li><a href="/job/{_e(job_id)}/{_e(name)}">'
                f"<code>{_e(name)}</code></a> — {_e(label)} "
                f'<span class="secondary">({_e(size)} bytes)</span></li>'
            )
        body.append("</ul>")

    body.append('<p><a href="/">← Back to jobs</a></p>')
    return _page(
        f"Recap · {title}",
        "\n".join(body),
        refresh_seconds=10 if is_running else None,
    )


def render_new(
    sources_root: Path,
    csrf_token: str,
    error: str | None = None,
) -> bytes:
    body: list[str] = []
    body.append("<h1>Recap · start new job</h1>")
    if error:
        body.append(f'<div class="banner error">{_e(error)}</div>')
    body.append(f"<p>Sources root: <code>{_e(sources_root)}</code></p>")

    options: list[tuple[str, str]] = []
    dir_exists = sources_root.is_dir()
    if dir_exists:
        try:
            for entry in sorted(sources_root.iterdir()):
                if (
                    entry.is_file()
                    and entry.suffix.lower() in _VIDEO_EXTENSIONS
                ):
                    options.append((str(entry.resolve()), entry.name))
        except OSError:
            dir_exists = False

    body.append('<form class="new-job" method="post" action="/run">')
    body.append(
        f'<input type="hidden" name="_token" value="{_e(csrf_token)}">'
    )
    if options:
        body.append("<p><label>Pick a video: ")
        body.append('<select name="source">')
        body.append('<option value="">— choose a file —</option>')
        for abs_path, display in options:
            body.append(
                f'<option value="{_e(abs_path)}">{_e(display)}</option>'
            )
        body.append("</select></label></p>")
    elif dir_exists:
        exts = " ".join(sorted(_VIDEO_EXTENSIONS))
        body.append(
            f'<p class="empty">No video files under <code>'
            f"{_e(sources_root)}</code> with extension in {_e(exts)}. "
            "Drop a file there or type a full path below.</p>"
        )
    else:
        body.append(
            '<p class="empty">Sources root does not exist. Create it '
            f"with <code>mkdir -p {_e(sources_root)}</code> and drop "
            "video files into it, or type a full path below.</p>"
        )
    body.append(
        '<p><label>Or enter a path: '
        '<input type="text" name="source_path" size="70" '
        'placeholder="/absolute/path/to/video.mp4"></label></p>'
    )
    body.append('<p><button type="submit">Start</button></p>')
    body.append("</form>")
    body.append('<p><a href="/">← Back to jobs</a></p>')
    return _page("Recap · new job", "\n".join(body))


def render_run_last(job_id: str, stage: str) -> bytes:
    entry = _get_last(job_id, stage)
    body: list[str] = []
    body.append(f"<h1>Recap · {_e(job_id)} · {_e(stage)}</h1>")
    if entry is None:
        body.append('<p class="empty">No runs yet.</p>')
        body.append(f'<p><a href="/job/{_e(job_id)}/">← Back to job</a></p>')
        return _page(f"Recap · {job_id} · {stage}", "\n".join(body))

    status = entry.get("status", "unknown")
    refresh_seconds = 5 if status == "in-progress" else None

    body.append("<ul>")
    body.append(f"<li>Stage: <code>{_e(stage)}</code></li>")
    body.append(f"<li>Started: {_e(entry.get('started_at'))}</li>")
    if entry.get("finished_at"):
        body.append(f"<li>Finished: {_e(entry['finished_at'])}</li>")
    exit_code = entry.get("exit_code")
    body.append(
        f"<li>Exit: <code>{_e('' if exit_code is None else exit_code)}</code></li>"
    )
    body.append(f"<li>Status: {_status_badge(status)}</li>")
    body.append("</ul>")

    body.append("<h2>stdout</h2>")
    body.append(f'<pre class="output">{_e(entry.get("stdout") or "")}</pre>')
    body.append("<h2>stderr</h2>")
    body.append(f'<pre class="output">{_e(entry.get("stderr") or "")}</pre>')

    body.append(f'<p><a href="/job/{_e(job_id)}/">← Back to job</a></p>')
    return _page(
        f"Recap · {job_id} · {stage}",
        "\n".join(body),
        refresh_seconds=refresh_seconds,
    )


def _utterance_speaker_id_valid(speaker: object) -> bool:
    if isinstance(speaker, bool):
        return False
    if isinstance(speaker, int):
        return True
    if isinstance(speaker, str) and speaker:
        return True
    return False


def _format_speaker(speaker: object) -> str:
    if isinstance(speaker, bool) or speaker is None:
        return "—"
    if isinstance(speaker, int):
        return f"Speaker {speaker}"
    if isinstance(speaker, str) and speaker:
        return _e(speaker)
    return "—"


def _utterances_qualify(utts: object) -> bool:
    if not isinstance(utts, list) or not utts:
        return False
    has_speaker = False
    has_text = False
    for u in utts:
        if not isinstance(u, dict):
            continue
        if _utterance_speaker_id_valid(u.get("speaker")):
            has_speaker = True
        text = u.get("text")
        if isinstance(text, str) and text.strip():
            has_text = True
        if has_speaker and has_text:
            return True
    return has_speaker and has_text


def render_transcript(
    job_id: str, job_dir: Path, logger_stream: IO | None = None,
) -> bytes:
    transcript_path = job_dir / "transcript.json"
    # Resolve a display title the same way render_job does.
    job_data = _read_job_json(job_dir) or {}
    title = job_data.get("original_filename") or job_id
    back = f'<p><a href="/job/{_e(job_id)}/">← Back to job</a></p>'

    if not transcript_path.is_file():
        body = (
            f"<h1>Recap · {_e(title)}</h1>"
            '<p class="empty">No transcript available yet.</p>'
            f"{back}"
        )
        return _page(f"Recap · {title} · transcript", body)

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("transcript.json top-level is not an object")
    except (OSError, ValueError) as e:
        if logger_stream is not None:
            logger_stream.write(
                f"[recap-ui] transcript skipped: {e}\n"
            )
            logger_stream.flush()
        body = (
            f"<h1>Recap · {_e(title)}</h1>"
            '<div class="banner error">'
            "transcript.json could not be parsed."
            "</div>"
            f"{back}"
        )
        return _page(f"Recap · {title} · transcript", body)

    utts = data.get("utterances")
    use_utterances = _utterances_qualify(utts)

    if use_utterances:
        source_rows: list[dict] = [
            u for u in utts
            if isinstance(u, dict)
            and isinstance(u.get("text"), str)
            and u["text"].strip()
        ]
    else:
        segs = data.get("segments")
        if not isinstance(segs, list):
            segs = []
        source_rows = [
            s for s in segs
            if isinstance(s, dict)
            and isinstance(s.get("text"), str)
            and s["text"].strip()
        ]

    has_video = (job_dir / "analysis.mp4").is_file()

    lines: list[str] = [f"<h1>Recap · {_e(title)}</h1>"]

    if has_video:
        lines.append(
            f'<video id="player" controls preload="metadata" '
            f'src="/job/{_e(job_id)}/analysis.mp4" '
            f'style="width:100%;max-width:960px"></video>'
        )

    meta_bits: list[str] = []
    engine = data.get("engine")
    model = data.get("model")
    language = data.get("language")
    if engine:
        meta_bits.append(f"engine <code>{_e(engine)}</code>")
    if model:
        meta_bits.append(f"model <code>{_e(model)}</code>")
    if language:
        meta_bits.append(f"language <code>{_e(language)}</code>")
    meta_bits.append(f"{len(source_rows)} rows")
    speaker_count: int | None = None
    if use_utterances:
        distinct_speakers = {
            u.get("speaker") for u in source_rows
            if _utterance_speaker_id_valid(u.get("speaker"))
        }
        speaker_count = len(distinct_speakers)
        meta_bits.append(f"{speaker_count} speakers")
    lines.append(
        f'<p class="secondary">{", ".join(meta_bits)}</p>'
    )

    if not source_rows:
        lines.append('<p class="empty">Transcript has no rows.</p>')
        lines.append(back)
        return _page(
            f"Recap · {title} · transcript", "\n".join(lines)
        )

    lines.append('<table class="transcript">')
    if use_utterances:
        lines.append(
            "<thead><tr><th>Time</th><th>Speaker</th><th>Text</th>"
            "</tr></thead>"
        )
    else:
        lines.append(
            "<thead><tr><th>Time</th><th>Text</th></tr></thead>"
        )
    lines.append("<tbody>")
    for row in source_rows:
        raw_start = row.get("start")
        if isinstance(raw_start, (int, float)) and not isinstance(
            raw_start, bool
        ):
            start_value = float(raw_start)
        else:
            start_value = 0.0
        start = format_ts(start_value)
        text = (row.get("text") or "").strip()
        if has_video:
            time_cell = (
                f'<button type="button" class="ts" '
                f'data-start="{start_value}">'
                f"<code>{_e(start)}</code></button>"
            )
            row_open = f'<tr data-start="{start_value}">'
        else:
            time_cell = f"<code>{_e(start)}</code>"
            row_open = "<tr>"
        if use_utterances:
            spk_cell = _format_speaker(row.get("speaker"))
            lines.append(
                row_open
                + f"<td>{time_cell}</td>"
                + f"<td>{spk_cell}</td>"
                + f"<td>{_e(text)}</td>"
                + "</tr>"
            )
        else:
            lines.append(
                row_open
                + f"<td>{time_cell}</td>"
                + f"<td>{_e(text)}</td>"
                + "</tr>"
            )
    lines.append("</tbody></table>")

    if has_video:
        lines.append(
            "<script>\n"
            "(function(){\n"
            "  var player = document.getElementById('player');\n"
            "  if (!player) return;\n"
            "  document.querySelectorAll('button.ts').forEach(function(el){\n"
            "    el.addEventListener('click', function(){\n"
            "      var t = parseFloat(el.dataset.start);\n"
            "      if (!isFinite(t) || t < 0) t = 0;\n"
            "      player.currentTime = t;\n"
            "      if (player.paused) {\n"
            "        player.play().catch(function(){});\n"
            "      }\n"
            "    });\n"
            "  });\n"
            "  var rows = [];\n"
            "  document.querySelectorAll('tr[data-start]').forEach(function(tr){\n"
            "    var t = parseFloat(tr.dataset.start);\n"
            "    if (isFinite(t)) rows.push({row: tr, start: t});\n"
            "  });\n"
            "  rows.sort(function(a, b){ return a.start - b.start; });\n"
            "  if (!rows.length) return;\n"
            "  var activeRow = null;\n"
            "  var lastUserScroll = 0;\n"
            "  function markUserScroll(){ lastUserScroll = Date.now(); }\n"
            "  ['wheel', 'touchmove', 'scroll'].forEach(function(evt){\n"
            "    window.addEventListener(evt, markUserScroll,\n"
            "      {passive: true, capture: true});\n"
            "  });\n"
            "  window.addEventListener('keydown', function(e){\n"
            "    if (e.key === 'ArrowUp' || e.key === 'ArrowDown' ||\n"
            "        e.key === 'PageUp' || e.key === 'PageDown' ||\n"
            "        e.key === 'Home' || e.key === 'End') {\n"
            "      markUserScroll();\n"
            "    }\n"
            "  });\n"
            "  function findRow(t){\n"
            "    var lo = 0, hi = rows.length - 1, best = -1;\n"
            "    while (lo <= hi) {\n"
            "      var mid = (lo + hi) >> 1;\n"
            "      if (rows[mid].start <= t) { best = mid; lo = mid + 1; }\n"
            "      else { hi = mid - 1; }\n"
            "    }\n"
            "    return best >= 0 ? rows[best].row : null;\n"
            "  }\n"
            "  function update(){\n"
            "    var row = findRow(player.currentTime || 0);\n"
            "    if (row === activeRow) return;\n"
            "    if (activeRow) activeRow.classList.remove('active');\n"
            "    if (row) row.classList.add('active');\n"
            "    activeRow = row;\n"
            "    if (row && Date.now() - lastUserScroll > 3000) {\n"
            "      row.scrollIntoView({block: 'nearest', behavior: 'smooth'});\n"
            "    }\n"
            "  }\n"
            "  player.addEventListener('timeupdate', update);\n"
            "  player.addEventListener('seeking', update);\n"
            "  player.addEventListener('play', update);\n"
            "  update();\n"
            "})();\n"
            "</script>"
        )

    lines.append(back)
    return _page(f"Recap · {title} · transcript", "\n".join(lines))


def render_404(path: str) -> bytes:
    body = (
        "<h1>Recap · 404</h1>"
        f"<p>No handler for <code>{_e(path)}</code>.</p>"
        '<p><a href="/">← Back to jobs</a></p>'
    )
    return _page("Recap · 404", body)


# ---- request handler -----------------------------------------------------


def _split_path(path: str) -> list[str]:
    """Split URL path into non-empty segments, rejecting raw '..' segments."""
    raw = path.split("?", 1)[0].split("#", 1)[0]
    segments = [seg for seg in raw.split("/") if seg != ""]
    for seg in segments:
        if seg == "..":
            raise ValueError("path traversal rejected")
    return segments


def _safe_job_dir(jobs_root: Path, job_id: str) -> Path | None:
    """Resolve `jobs_root/<job_id>/` and ensure it is a direct child."""
    if job_id in ("", ".", "..") or "/" in job_id or "\\" in job_id:
        return None
    if Path(job_id).name != job_id:
        return None
    candidate = (jobs_root / job_id).resolve()
    try:
        candidate.relative_to(jobs_root.resolve())
    except ValueError:
        return None
    if not candidate.is_dir():
        return None
    # Must be a direct child.
    if candidate.parent != jobs_root.resolve():
        return None
    return candidate


def _safe_whitelisted(job_dir: Path, filename: str) -> Path | None:
    if filename not in _JOB_ROOT_FILES:
        return None
    if Path(filename).name != filename:
        return None
    target = (job_dir / filename).resolve()
    try:
        target.relative_to(job_dir.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def _safe_candidate_frame(job_dir: Path, filename: str) -> Path | None:
    if (
        not filename
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
    ):
        return None
    if Path(filename).name != filename:
        return None
    ext = Path(filename).suffix.lower()
    if ext not in _CANDIDATE_FRAME_EXTS:
        return None
    frames_dir = job_dir / "candidate_frames"
    target = (frames_dir / filename).resolve()
    try:
        target.relative_to(frames_dir.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def _content_type_for(path: Path) -> str:
    return _CONTENT_TYPES.get(
        path.suffix.lower(), "application/octet-stream"
    )


def _make_handler(jobs_root: Path, sources_root: Path):
    """Build a BaseHTTPRequestHandler subclass closed over the roots."""
    root_resolved = jobs_root.resolve()
    sources_resolved = sources_root.resolve() if sources_root else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "RecapUI/1"

        def log_message(self, fmt, *args):  # noqa: N802 - stdlib signature
            # Route through stderr like the default but prefix clearly.
            self.log_date_time_string()
            msg = fmt % args
            self.server.logger_stream.write(
                f"[recap-ui] {self.address_string()} - {msg}\n"
            )
            self.server.logger_stream.flush()

        def _send_html(self, status: HTTPStatus, body: bytes) -> None:
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(self, path: Path, content_type: str) -> None:
            try:
                data = path.read_bytes()
            except OSError:
                self._send_html(HTTPStatus.NOT_FOUND, render_404(self.path))
                return
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_ranged_file(
            self, path: Path, content_type: str,
        ) -> None:
            try:
                size = path.stat().st_size
            except OSError:
                self._send_html(HTTPStatus.NOT_FOUND, render_404(self.path))
                return

            range_header = self.headers.get("Range")
            try:
                parsed = _parse_range(range_header, size)
            except ValueError:
                # 416 — valid single-range syntax but unsatisfiable.
                self.send_response(
                    HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE.value
                )
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return

            if parsed is None:
                # Full body.
                self.send_response(HTTPStatus.OK.value)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self._stream_file(path, 0, size)
                return

            start, end = parsed
            length = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header(
                "Content-Range", f"bytes {start}-{end}/{size}"
            )
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self._stream_file(path, start, length)

        def _stream_file(
            self, path: Path, start: int, length: int,
        ) -> None:
            try:
                with open(path, "rb") as f:
                    if start:
                        f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(_RANGE_CHUNK_BYTES, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                # Browser aborted mid-transfer; no further action.
                return
            except OSError:
                return

        def _not_found(self) -> None:
            self._send_html(HTTPStatus.NOT_FOUND, render_404(self.path))

        def do_GET(self) -> None:  # noqa: N802 - stdlib signature
            try:
                segments = _split_path(self.path)
            except ValueError:
                self._not_found()
                return

            if not segments:
                body = render_index(root_resolved)
                self._send_html(HTTPStatus.OK, body)
                return

            if segments == ["new"]:
                token = getattr(self.server, "csrf_token", "") or ""
                body = render_new(sources_resolved, token)
                self._send_html(HTTPStatus.OK, body)
                return

            if segments[0] != "job" or len(segments) < 2:
                self._not_found()
                return

            job_id = segments[1]
            job_dir = _safe_job_dir(root_resolved, job_id)
            if job_dir is None:
                self._not_found()
                return

            if len(segments) == 2:
                # /job/<id>  — redirect-equivalent: serve the detail page.
                body = render_job(
                    root_resolved, job_id,
                    logger_stream=getattr(self.server, "logger_stream", None),
                    csrf_token=getattr(self.server, "csrf_token", None),
                )
                if body is None:
                    self._not_found()
                    return
                self._send_html(HTTPStatus.OK, body)
                return

            if len(segments) == 3 and segments[2] == "transcript":
                body = render_transcript(
                    job_id, job_dir,
                    logger_stream=getattr(self.server, "logger_stream", None),
                )
                self._send_html(HTTPStatus.OK, body)
                return

            if len(segments) == 3:
                filename = segments[2]
                target = _safe_whitelisted(job_dir, filename)
                if target is None:
                    self._not_found()
                    return
                content_type = _content_type_for(target)
                if content_type.startswith("video/"):
                    self._send_ranged_file(target, content_type)
                else:
                    self._send_bytes(target, content_type)
                return

            if (
                len(segments) == 4
                and segments[2] == "run"
                and segments[3] in _RUNNABLE_STAGES
            ):
                # GET on a POST-only route: explicitly 405.
                self.send_response(HTTPStatus.METHOD_NOT_ALLOWED.value)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if (
                len(segments) == 5
                and segments[2] == "run"
                and segments[3] in _LAST_RESULT_STAGES
                and segments[4] == "last"
            ):
                body = render_run_last(job_id, segments[3])
                self._send_html(HTTPStatus.OK, body)
                return

            if len(segments) == 4 and segments[2] == "candidate_frames":
                target = _safe_candidate_frame(job_dir, segments[3])
                if target is None:
                    self._not_found()
                    return
                self._send_bytes(target, _content_type_for(target))
                return

            self._not_found()

        # ---- POST ---------------------------------------------------

        def _reject_post(
            self,
            status: HTTPStatus,
            reason: str,
            message: str,
            *,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = _page(
                f"Recap · {status.value}",
                f"<h1>Recap · {status.value}</h1><p>{_e(message)}</p>",
            )
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra_headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            self.server.logger_stream.write(
                f"[recap-ui] rejected POST from={self.address_string()} "
                f"reason={reason}\n"
            )
            self.server.logger_stream.flush()

        def _respond_new_error(
            self, status: HTTPStatus, reason: str, message: str,
        ) -> None:
            """Re-render /new with an inline error message.

            Caller is responsible for any cleanup (e.g. releasing the
            global run slot) before this method returns.
            """
            token = getattr(self.server, "csrf_token", "") or ""
            body = render_new(
                sources_resolved or sources_root,
                token,
                error=message,
            )
            self.send_response(status.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            self.server.logger_stream.write(
                f"[recap-ui] rejected POST /run "
                f"from={self.address_string()} reason={reason}\n"
            )
            self.server.logger_stream.flush()

        def _handle_new_run(self, form: dict) -> None:
            if sources_resolved is None:
                self._reject_post(
                    HTTPStatus.INTERNAL_SERVER_ERROR, "no-sources-root",
                    "sources-root is not configured.",
                )
                return

            # Acquire the global run slot (one concurrent recap run).
            if not _run_slot.acquire(blocking=False):
                self._reject_post(
                    HTTPStatus.TOO_MANY_REQUESTS, "slot",
                    "Another video is being processed. "
                    "Please wait and try again.",
                    extra_headers={"Retry-After": "30"},
                )
                return

            slot_transferred = False
            try:
                # Source candidate: prefer `source`, fall back to
                # `source_path` if `source` is blank.
                source_value = (form.get("source") or [""])[0].strip()
                source_path_value = (
                    form.get("source_path") or [""]
                )[0].strip()
                candidate = source_value or source_path_value
                if not candidate:
                    self._respond_new_error(
                        HTTPStatus.BAD_REQUEST, "source-missing",
                        "Select a video or enter a path.",
                    )
                    return

                try:
                    resolved = Path(candidate).expanduser().resolve()
                except (OSError, RuntimeError, ValueError) as e:
                    self._respond_new_error(
                        HTTPStatus.BAD_REQUEST, "source-invalid",
                        f"Could not resolve source path: {e}",
                    )
                    return

                try:
                    resolved.relative_to(sources_resolved)
                except ValueError:
                    self._respond_new_error(
                        HTTPStatus.FORBIDDEN, "source-outside-root",
                        "Source path is outside the sources root.",
                    )
                    return

                if not resolved.is_file():
                    self._respond_new_error(
                        HTTPStatus.BAD_REQUEST, "source-not-file",
                        "Source does not exist or is not a regular file.",
                    )
                    return

                if resolved.suffix.lower() not in _VIDEO_EXTENSIONS:
                    exts = " ".join(sorted(_VIDEO_EXTENSIONS))
                    self._respond_new_error(
                        HTTPStatus.BAD_REQUEST, "source-bad-ext",
                        f"Unsupported video extension. Allowed: {exts}.",
                    )
                    return

                # Synchronous ingest.
                try:
                    ingest = subprocess.run(
                        [
                            sys.executable, "-m", "recap", "ingest",
                            "--source", str(resolved),
                            "--jobs-root", str(root_resolved),
                        ],
                        cwd=str(REPO_ROOT),
                        capture_output=True,
                        text=True,
                        timeout=_INGEST_TIMEOUT,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    self._respond_new_error(
                        HTTPStatus.BAD_REQUEST, "ingest-timeout",
                        f"ingest timed out after {int(_INGEST_TIMEOUT)}s.",
                    )
                    return
                except OSError as e:
                    self._respond_new_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR, "ingest-spawn",
                        f"failed to spawn recap ingest: "
                        f"{type(e).__name__}: {e}",
                    )
                    return

                if ingest.returncode != 0:
                    err = (
                        (ingest.stderr or "").strip()
                        or (ingest.stdout or "").strip()
                        or f"ingest failed with exit {ingest.returncode}"
                    )
                    # Truncate to keep the error banner readable.
                    if len(err) > 400:
                        err = err[:399] + "…"
                    self._respond_new_error(
                        HTTPStatus.BAD_REQUEST, "ingest-failed",
                        f"ingest failed: {err}",
                    )
                    return

                stdout_lines = [
                    ln for ln in (ingest.stdout or "").splitlines()
                    if ln.strip()
                ]
                if not stdout_lines:
                    self._respond_new_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "ingest-no-root",
                        "ingest produced no job root.",
                    )
                    return
                new_job_dir = Path(stdout_lines[-1].strip())
                job_id = new_job_dir.name
                safe_job_dir = _safe_job_dir(root_resolved, job_id)
                if safe_job_dir is None:
                    self._respond_new_error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "ingest-unexpected-root",
                        f"ingest produced an unexpected job root: "
                        f"{stdout_lines[-1]}",
                    )
                    return

                # Mark the background run as in-progress and spawn.
                # Pass the re-resolved safe path, not the raw stdout
                # parse, so `recap run --job ...` targets only a
                # direct child of the configured jobs root.
                _set_in_progress(job_id, "run", _now_iso())
                thread = threading.Thread(
                    target=_background_run,
                    args=(job_id, safe_job_dir),
                    daemon=True,
                )
                thread.start()
                slot_transferred = True

                self.server.logger_stream.write(
                    f"[recap-ui] started recap run job={job_id}\n"
                )
                self.server.logger_stream.flush()

                location = f"/job/{job_id}/"
                self.send_response(HTTPStatus.SEE_OTHER.value)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            finally:
                if not slot_transferred:
                    _run_slot.release()

        def do_POST(self) -> None:  # noqa: N802
            # 1. Host pinning.
            expected_host = getattr(self.server, "expected_host", "")
            got_host = self.headers.get("Host") or ""
            if not expected_host or not secrets.compare_digest(
                got_host, expected_host
            ):
                self._reject_post(
                    HTTPStatus.FORBIDDEN, "host",
                    "Host header mismatch.",
                )
                return

            # 2. Content-Length limit.
            raw_len = self.headers.get("Content-Length")
            try:
                content_length = int(raw_len) if raw_len is not None else -1
            except ValueError:
                content_length = -1
            if content_length < 0:
                self._reject_post(
                    HTTPStatus.LENGTH_REQUIRED, "content-length-missing",
                    "Content-Length is required.",
                )
                return
            if content_length > _POST_BODY_MAX:
                self._reject_post(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body-too-large",
                    "Request body exceeds 4096 bytes.",
                )
                return

            body_bytes = (
                self.rfile.read(content_length) if content_length > 0
                else b""
            )
            try:
                form = urllib.parse.parse_qs(
                    body_bytes.decode("utf-8", "replace"),
                    keep_blank_values=True,
                    max_num_fields=10,
                )
            except ValueError:
                self._reject_post(
                    HTTPStatus.BAD_REQUEST, "body-parse",
                    "Could not parse form body.",
                )
                return

            # 3. CSRF.
            expected_token = getattr(self.server, "csrf_token", "") or ""
            got_token = (form.get("_token") or [""])[0]
            if not expected_token or not secrets.compare_digest(
                got_token, expected_token
            ):
                self._reject_post(
                    HTTPStatus.FORBIDDEN, "csrf",
                    "CSRF token missing or invalid.",
                )
                return

            # 4. Path dispatch.
            try:
                segments = _split_path(self.path)
            except ValueError:
                self._not_found()
                return

            # 4a. POST /run — start a new job from a video path.
            if segments == ["run"]:
                self._handle_new_run(form)
                return

            # 4b. POST /job/<id>/run/<stage> — rerun an exporter.
            if (
                len(segments) != 4
                or segments[0] != "job"
                or segments[2] != "run"
            ):
                self._not_found()
                return
            job_id = segments[1]
            stage = segments[3]
            if stage not in _RUNNABLE_STAGES:
                self._not_found()
                return
            job_dir = _safe_job_dir(root_resolved, job_id)
            if job_dir is None:
                self._not_found()
                return

            # 5. Per-job lock.
            lock = _get_job_lock(job_id)
            acquired = lock.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT)
            if not acquired:
                self._reject_post(
                    HTTPStatus.TOO_MANY_REQUESTS, "lock",
                    "Another run is already in progress for this job. "
                    "Try again shortly.",
                    extra_headers={"Retry-After": "2"},
                )
                return

            try:
                _set_in_progress(job_id, stage, _now_iso())
                result = _run_stage(stage, job_dir)
                _set_final(job_id, stage, result)
                self.server.logger_stream.write(
                    f"[recap-ui] run {stage} job={job_id} "
                    f"exit={result['exit_code']} "
                    f"elapsed={result['elapsed']:.2f}s\n"
                )
                self.server.logger_stream.flush()
            finally:
                lock.release()

            location = f"/job/{job_id}/run/{stage}/last"
            self.send_response(HTTPStatus.SEE_OTHER.value)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

    return Handler


def serve(
    host: str, port: int, jobs_root: Path, sources_root: Path,
) -> int:
    if not jobs_root.exists():
        raise RuntimeError(f"jobs-root not found: {jobs_root}")
    if not jobs_root.is_dir():
        raise RuntimeError(f"jobs-root is not a directory: {jobs_root}")

    # `sources_root` is allowed to not exist yet — the /new page will
    # render a helpful message instead of 500'ing.
    handler_cls = _make_handler(jobs_root, sources_root)
    server = ThreadingHTTPServer((host, port), handler_cls)
    # Attach server-wide state used by the handler.
    server.logger_stream = sys.stderr
    server.csrf_token = secrets.token_urlsafe(32)
    server.expected_host = f"{host}:{port}"
    print(
        f"Recap UI running at http://{host}:{port} (Ctrl-C to stop)",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
