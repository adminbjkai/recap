#!/usr/bin/env python3
"""Offline smoke validation for the `recap ui` dashboard.

Spins up `recap ui` against a temp copy of `scripts/fixtures/minimal_job`,
curls a handful of routes, runs the three report exporters, and confirms
the dashboard serves the generated artifacts and blocks traversal /
non-whitelisted paths. Stdlib only.
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "scripts" / "fixtures" / "minimal_job"

CHECKS_PASSED = 0


def fail(case: str, reason: str) -> None:
    print(f"FAIL: {case}: {reason}")
    sys.exit(1)


def passed() -> None:
    global CHECKS_PASSED
    CHECKS_PASSED += 1


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(port: int, raw_path: str) -> tuple[int, str, bytes]:
    """Issue a raw GET to 127.0.0.1:port with path sent verbatim.

    Uses http.client directly so segments like '..' are NOT normalized by
    the client before going on the wire — the server must handle them.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.request("GET", raw_path)
        resp = conn.getresponse()
        body = resp.read()
        ctype = resp.getheader("Content-Type", "")
        return resp.status, ctype, body
    finally:
        conn.close()


_CSRF_RE = re.compile(rb'name="_token" value="([A-Za-z0-9_\-]+)"')


def extract_csrf(body: bytes) -> str:
    m = _CSRF_RE.search(body)
    if not m:
        fail("csrf-token", "no _token hidden input found on detail page")
    return m.group(1).decode("ascii")


def http_post(
    port: int,
    path: str,
    form_fields: dict[str, str] | None,
    *,
    host_override: str | None = None,
    content_length_override: int | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Issue a raw POST. Lets callers forge Host and the declared length."""
    if form_fields is None:
        body_bytes = b""
    else:
        body_bytes = urllib.parse.urlencode(form_fields).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
        conn.putheader(
            "Host", host_override or f"127.0.0.1:{port}"
        )
        conn.putheader("Content-Type", "application/x-www-form-urlencoded")
        cl = (
            content_length_override
            if content_length_override is not None
            else len(body_bytes)
        )
        conn.putheader("Content-Length", str(cl))
        conn.endheaders()
        if body_bytes:
            conn.send(body_bytes)
        resp = conn.getresponse()
        headers = {k: v for k, v in resp.getheaders()}
        return resp.status, headers, resp.read()
    finally:
        conn.close()


def wait_for_server(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_err: str | None = None
    while time.monotonic() < deadline:
        try:
            status, _, body = http_get(port, "/")
            if status == 200:
                return
            last_err = f"status={status}"
        except (ConnectionRefusedError, OSError) as e:
            last_err = str(e)
        time.sleep(0.1)
    fail("startup", f"UI did not respond on port {port} within {timeout}s"
         f" (last={last_err})")


def start_ui(
    jobs_root: Path, port: int, sources_root: Path | None = None,
) -> subprocess.Popen:
    args = [
        sys.executable, "-m", "recap", "ui",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--jobs-root", str(jobs_root),
    ]
    if sources_root is not None:
        args.extend(["--sources-root", str(sources_root)])
    proc = subprocess.Popen(
        args, cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return proc


def stop_ui(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3.0)


def run_cli(case: str, cmd: str, job_dir: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "recap", cmd,
         "--job", str(job_dir), "--force"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        fail(case, f"`recap {cmd}` failed: {result.stderr.strip()!r}")


def expect_status(case: str, port: int, path: str, want: int) -> tuple[str, bytes]:
    status, ctype, body = http_get(port, path)
    if status != want:
        fail(case, f"GET {path} status={status}, expected {want}")
    return ctype, body


def expect_contains(case: str, body: bytes, needle: bytes) -> None:
    if needle not in body:
        fail(case, f"response missing {needle!r}")


def expect_not_contains(case: str, body: bytes, needle: bytes) -> None:
    if needle in body:
        fail(case, f"response unexpectedly contains {needle!r}")


def main() -> int:
    if not FIXTURE.is_dir():
        fail("fixture", f"missing fixture at {FIXTURE}")

    scratch_root = Path(tempfile.mkdtemp(prefix="recap_ui_"))
    jobs_root = scratch_root / "jobs"
    jobs_root.mkdir()
    job_dir = jobs_root / "minimal_job"
    shutil.copytree(FIXTURE, job_dir)

    sources_root = scratch_root / "sources"
    sources_root.mkdir()
    fake_video = sources_root / "fake.mp4"
    fake_video.write_bytes(b"")
    bad_ext = sources_root / "bad.txt"
    bad_ext.write_bytes(b"")

    port = free_port()
    proc = start_ui(jobs_root, port, sources_root=sources_root)
    try:
        wait_for_server(port)
        passed()

        # --- pre-report route checks ----------------------------------
        case = "index"
        _, body = expect_status(case, port, "/", 200)
        expect_contains(case, body, b"minimal_job")
        expect_contains(case, body, b'href="/new"')
        passed()

        # /new page renders a form, hidden token, and lists fake.mp4
        # but not bad.txt (extension whitelist).
        case = "new-page"
        _, body = expect_status(case, port, "/new", 200)
        expect_contains(case, body, b'action="/run"')
        expect_contains(case, body, b'name="_token"')
        expect_contains(case, body, b"fake.mp4")
        expect_not_contains(case, body, b"bad.txt")
        new_token = extract_csrf(body)
        passed()

        # POST /run validations (these never actually spawn ingest:
        # every case trips a pre-subprocess check.)
        case = "post-run-missing-token"
        status, _, _ = http_post(port, "/run", {})
        if status != 403:
            fail(case, f"expected 403, got {status}")
        passed()

        case = "post-run-forged-host"
        status, _, _ = http_post(
            port, "/run", {"_token": new_token},
            host_override="bogus.example:8765",
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        passed()

        case = "post-run-body-too-large"
        big = "x" * 5000
        status, _, _ = http_post(
            port, "/run", {"_token": new_token, "fill": big},
        )
        if status != 413:
            fail(case, f"expected 413, got {status}")
        passed()

        case = "post-run-missing-source"
        status, _, _ = http_post(port, "/run", {"_token": new_token})
        if status != 400:
            fail(case, f"expected 400, got {status}")
        passed()

        case = "post-run-outside-sources-root"
        status, _, _ = http_post(
            port, "/run",
            {"_token": new_token, "source_path": "/etc/hosts"},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        passed()

        case = "post-run-bad-extension"
        status, _, _ = http_post(
            port, "/run",
            {"_token": new_token, "source": str(bad_ext.resolve())},
        )
        if status != 400:
            fail(case, f"expected 400, got {status}")
        passed()

        case = "job-detail"
        _, body = expect_status(case, port, "/job/minimal_job/", 200)
        for stage in (b"ingest", b"normalize", b"transcribe", b"assemble"):
            expect_contains(case, body, b"<code>" + stage + b"</code>")
        # No stage has failed on a fresh fixture — no Errors section.
        expect_not_contains(case, body, b"<h2>Errors</h2>")
        passed()

        # A scratch job without selected_frames.json must NOT render the
        # Chapters & selected-frames summary.
        case = "detail-chapters-absent-without-selected"
        no_sf_scratch = Path(tempfile.mkdtemp(prefix="recap_ui_no_sf_"))
        try:
            no_sf_jobs = no_sf_scratch / "jobs"
            no_sf_jobs.mkdir()
            no_sf_job = no_sf_jobs / "minimal_job"
            shutil.copytree(FIXTURE, no_sf_job)
            (no_sf_job / "selected_frames.json").unlink()
            no_sf_port = free_port()
            no_sf_proc = start_ui(no_sf_jobs, no_sf_port)
            try:
                wait_for_server(no_sf_port)
                _, body2 = expect_status(
                    case, no_sf_port, "/job/minimal_job/", 200,
                )
                expect_not_contains(
                    case, body2, b"<h2>Chapters &amp; selected frames</h2>"
                )
            finally:
                stop_ui(no_sf_proc)
        finally:
            shutil.rmtree(no_sf_scratch, ignore_errors=True)
        passed()

        for case, path in [
            ("job-json", "/job/minimal_job/job.json"),
            ("metadata-json", "/job/minimal_job/metadata.json"),
            ("transcript-json", "/job/minimal_job/transcript.json"),
        ]:
            ctype, body = expect_status(case, port, path, 200)
            if "application/json" not in ctype:
                fail(case, f"content-type was {ctype!r}")
            try:
                json.loads(body)
            except ValueError as e:
                fail(case, f"body did not parse: {e}")
            passed()

        # Raw unnormalized traversal path. http.client sends it verbatim.
        case = "traversal-etc-passwd"
        _, body = expect_status(
            case, port, "/job/minimal_job/../../etc/passwd", 404
        )
        expect_not_contains(case, body, b"root:x:0:0")
        passed()

        case = "not-whitelisted-tmp"
        expect_status(case, port, "/job/minimal_job/report.html.tmp", 404)
        passed()

        case = "candidate-frame-jpeg"
        _, body = expect_status(
            case, port,
            "/job/minimal_job/candidate_frames/scene-001.jpg", 200,
        )
        if not body.startswith(b"\xff\xd8\xff"):
            fail(case, "body is not a JPEG (wrong magic bytes)")
        passed()

        case = "unknown-route"
        expect_status(case, port, "/nope", 404)
        passed()

        # --- generate reports and re-check ---------------------------
        for cmd in ("assemble", "export-html", "export-docx"):
            run_cli(f"cli-{cmd}", cmd, job_dir)
        passed()

        case = "detail-links-reports"
        _, body = expect_status(case, port, "/job/minimal_job/", 200)
        for name in (b"report.md", b"report.html", b"report.docx"):
            expect_contains(case, body, b"/job/minimal_job/" + name)
        passed()

        case = "report-html"
        ctype, body = expect_status(case, port, "/job/minimal_job/report.html", 200)
        if "text/html" not in ctype:
            fail(case, f"content-type was {ctype!r}")
        expect_contains(case, body, b"<h2>Chapters</h2>")
        passed()

        case = "report-docx"
        ctype, _ = expect_status(case, port, "/job/minimal_job/report.docx", 200)
        want_ct = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
        if want_ct not in ctype:
            fail(case, f"content-type was {ctype!r}")
        passed()

        case = "report-html-candidate-frames"
        _, html_body = expect_status(case, port, "/job/minimal_job/report.html", 200)
        expected_src = b'src="candidate_frames/scene-001.jpg"'
        expect_contains(case, html_body, expected_src)
        # Fetch the referenced image through the same server.
        _, frame_body = expect_status(
            case, port,
            "/job/minimal_job/candidate_frames/scene-001.jpg", 200,
        )
        if not frame_body.startswith(b"\xff\xd8\xff"):
            fail(case, "referenced candidate frame is not a JPEG")
        passed()

        # Chapters & selected-frames summary on the detail page.
        case = "detail-chapters-summary"
        _, body = expect_status(case, port, "/job/minimal_job/", 200)
        expect_contains(case, body, b"<h2>Chapters &amp; selected frames</h2>")
        expect_contains(case, body, b"Chapter 1")
        expect_contains(
            case, body,
            b'src="/job/minimal_job/candidate_frames/scene-001.jpg"',
        )
        expect_contains(
            case, body,
            b'src="/job/minimal_job/candidate_frames/scene-003.jpg"',
        )
        expect_contains(case, body, b"hero")
        expect_contains(case, body, b"supporting")
        expect_not_contains(case, body, b"scene-002.jpg")
        passed()

        # Errors section appears when a stage has status=failed.
        case = "detail-errors-section"
        jj = job_dir / "job.json"
        original_job_json = jj.read_text(encoding="utf-8")
        data = json.loads(original_job_json)
        data.setdefault("stages", {}).setdefault("assemble", {})
        data["stages"]["assemble"]["status"] = "failed"
        data["stages"]["assemble"]["error"] = "synthetic test error <tag>"
        jj.write_text(json.dumps(data), encoding="utf-8")
        try:
            _, body = expect_status(case, port, "/job/minimal_job/", 200)
            expect_contains(case, body, b"<h2>Errors</h2>")
            expect_contains(case, body, b"<code>assemble</code>")
            expect_contains(
                case, body,
                b"synthetic test error &lt;tag&gt;",
            )
            expect_not_contains(case, body, b"<tag>")
        finally:
            jj.write_text(original_job_json, encoding="utf-8")
        passed()

        # chapter_candidates.json missing the chapter that
        # selected_frames.json references must not crash the page; the
        # Chapters section is silently omitted and the page still 200s.
        case = "detail-chapters-orphan-selected"
        ccp = job_dir / "chapter_candidates.json"
        original_cc = ccp.read_text(encoding="utf-8")
        cc = json.loads(original_cc)
        # Remove every chapter so no index matches the selected chapter.
        cc["chapters"] = []
        cc["chapter_count"] = 0
        ccp.write_text(json.dumps(cc), encoding="utf-8")
        try:
            _, body = expect_status(case, port, "/job/minimal_job/", 200)
            expect_not_contains(
                case, body, b"<h2>Chapters &amp; selected frames</h2>"
            )
        finally:
            ccp.write_text(original_cc, encoding="utf-8")
        passed()

        # Malformed selected_frames.json must not crash the page; the
        # Chapters section is silently omitted and the page still 200s.
        # ---- POST / write surface -----------------------------------

        case = "detail-has-action-forms"
        _, body = expect_status(case, port, "/job/minimal_job/", 200)
        for stage in (b"assemble", b"export-html", b"export-docx"):
            needle = b'action="/job/minimal_job/run/' + stage + b'"'
            expect_contains(case, body, needle)
        expect_contains(case, body, b'name="_token"')
        token = extract_csrf(body)
        passed()

        case = "post-assemble-success"
        status, headers, _ = http_post(
            port, "/job/minimal_job/run/assemble", {"_token": token}
        )
        if status != 303:
            fail(case, f"expected 303, got {status}")
        expected_loc = "/job/minimal_job/run/assemble/last"
        if headers.get("Location") != expected_loc:
            fail(case, f"Location header was {headers.get('Location')!r}")
        _, last_body = expect_status(case, port, expected_loc, 200)
        expect_contains(case, last_body, b"Exit: <code>0</code>")
        expect_contains(case, last_body, b"<h2>stdout</h2>")
        expect_contains(case, last_body, b"<h2>stderr</h2>")
        passed()

        case = "last-export-docx-no-runs-yet"
        _, body = expect_status(
            case, port, "/job/minimal_job/run/export-docx/last", 200
        )
        expect_contains(case, body, b"No runs yet")
        passed()

        case = "post-export-html-success"
        status, headers, _ = http_post(
            port, "/job/minimal_job/run/export-html", {"_token": token}
        )
        if status != 303:
            fail(case, f"expected 303, got {status}")
        _, last_body = expect_status(
            case, port, "/job/minimal_job/run/export-html/last", 200
        )
        expect_contains(case, last_body, b"Exit: <code>0</code>")
        passed()

        case = "post-missing-token"
        status, _, _ = http_post(
            port, "/job/minimal_job/run/assemble", {}
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        passed()

        case = "post-wrong-token"
        status, _, _ = http_post(
            port, "/job/minimal_job/run/assemble", {"_token": "wrong"}
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        passed()

        case = "post-wrong-host"
        status, _, _ = http_post(
            port, "/job/minimal_job/run/assemble", {"_token": token},
            host_override="bogus.example:8765",
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        passed()

        case = "post-body-too-large"
        # Body well over the 4096-byte cap.
        big = "x" * 5000
        status, _, _ = http_post(
            port, "/job/minimal_job/run/assemble",
            {"_token": token, "fill": big},
        )
        if status != 413:
            fail(case, f"expected 413, got {status}")
        passed()

        case = "post-unknown-stage"
        status, _, _ = http_post(
            port, "/job/minimal_job/run/verify", {"_token": token}
        )
        if status != 404:
            fail(case, f"expected 404, got {status}")
        passed()

        case = "get-on-post-only"
        status, _, _ = http_get(port, "/job/minimal_job/run/assemble")
        if status not in (404, 405):
            fail(case, f"expected 404 or 405, got {status}")
        passed()

        case = "post-path-traversal"
        # Raw path with an unresolvable shape; server must not spawn a
        # subprocess and must return 404.
        status, _, _ = http_post(
            port, "/job/minimal_job/../..//run/assemble", {"_token": token}
        )
        if status != 404:
            fail(case, f"expected 404, got {status}")
        passed()

        case = "detail-malformed-selected"
        sfp = job_dir / "selected_frames.json"
        original_sf = sfp.read_text(encoding="utf-8")
        sf = json.loads(original_sf)
        sf["chapters"][0]["start_seconds"] = "bad"
        sfp.write_text(json.dumps(sf), encoding="utf-8")
        try:
            _, body = expect_status(case, port, "/job/minimal_job/", 200)
            expect_not_contains(
                case, body, b"<h2>Chapters &amp; selected frames</h2>"
            )
        finally:
            sfp.write_text(original_sf, encoding="utf-8")
        passed()

        # Detail page shows the "Run in progress" banner and a 10-s
        # meta refresh when any stage is currently running.
        case = "detail-running-banner"
        jjr = job_dir / "job.json"
        original_jj = jjr.read_text(encoding="utf-8")
        data = json.loads(original_jj)
        data.setdefault("stages", {}).setdefault("transcribe", {})
        data["stages"]["transcribe"]["status"] = "running"
        jjr.write_text(json.dumps(data), encoding="utf-8")
        try:
            _, body = expect_status(case, port, "/job/minimal_job/", 200)
            expect_contains(case, body, b"Run in progress")
            expect_contains(
                case, body, b'meta http-equiv="refresh" content="10"'
            )
        finally:
            jjr.write_text(original_jj, encoding="utf-8")
        passed()
    finally:
        stop_ui(proc)
        shutil.rmtree(scratch_root, ignore_errors=True)

    print(f"OK: {CHECKS_PASSED} UI checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
