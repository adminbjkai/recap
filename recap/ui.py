"""Read-only local web dashboard for Recap jobs.

Served via `recap ui --host 127.0.0.1 --port 8765 --jobs-root jobs`.
Renders a jobs index and per-job detail pages, and serves whitelisted
artifacts (report.md/html/docx, job.json, transcript.*, selected/chapter
JSONs, and candidate_frames/*.{jpg,jpeg,png}) directly from disk.

Entirely read-only: no POST routes, no forms that mutate state, no
subprocess calls, no stage execution, no new dependencies. Uses stdlib
`http.server.ThreadingHTTPServer` + a custom `BaseHTTPRequestHandler`.
"""

from __future__ import annotations

import html
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


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


def _page(title: str, body_html: str) -> bytes:
    doc = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        f"<style>{_INLINE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        + body_html
        + "\n</body>\n</html>\n"
    )
    return doc.encode("utf-8")


# ---- page renderers ------------------------------------------------------


def render_index(jobs_root: Path) -> bytes:
    jobs = _list_jobs(jobs_root)
    body: list[str] = []
    body.append(f"<h1>Recap · jobs</h1>")
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


def render_job(jobs_root: Path, job_id: str) -> bytes | None:
    job_dir = jobs_root / job_id
    if not job_dir.is_dir():
        return None
    data = _read_job_json(job_dir)
    if data is None:
        return None

    title = data.get("original_filename") or job_id
    body: list[str] = []
    body.append(f"<h1>Recap · {_e(title)}</h1>")

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
    return _page(f"Recap · {title}", "\n".join(body))


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


def _make_handler(jobs_root: Path):
    """Build a BaseHTTPRequestHandler subclass closed over jobs_root."""
    root_resolved = jobs_root.resolve()

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
                body = render_job(root_resolved, job_id)
                if body is None:
                    self._not_found()
                    return
                self._send_html(HTTPStatus.OK, body)
                return

            if len(segments) == 3:
                filename = segments[2]
                target = _safe_whitelisted(job_dir, filename)
                if target is None:
                    self._not_found()
                    return
                self._send_bytes(target, _content_type_for(target))
                return

            if len(segments) == 4 and segments[2] == "candidate_frames":
                target = _safe_candidate_frame(job_dir, segments[3])
                if target is None:
                    self._not_found()
                    return
                self._send_bytes(target, _content_type_for(target))
                return

            self._not_found()

    return Handler


def serve(host: str, port: int, jobs_root: Path) -> int:
    if not jobs_root.exists():
        raise RuntimeError(f"jobs-root not found: {jobs_root}")
    if not jobs_root.is_dir():
        raise RuntimeError(f"jobs-root is not a directory: {jobs_root}")

    handler_cls = _make_handler(jobs_root)
    server = ThreadingHTTPServer((host, port), handler_cls)
    # Attach a stream for log_message to use.
    import sys
    server.logger_stream = sys.stderr
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
