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
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
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


def start_ui(jobs_root: Path, port: int) -> subprocess.Popen:
    args = [
        sys.executable, "-m", "recap", "ui",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--jobs-root", str(jobs_root),
    ]
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

    port = free_port()
    proc = start_ui(jobs_root, port)
    try:
        wait_for_server(port)
        passed()

        # --- pre-report route checks ----------------------------------
        case = "index"
        _, body = expect_status(case, port, "/", 200)
        expect_contains(case, body, b"minimal_job")
        passed()

        case = "job-detail"
        _, body = expect_status(case, port, "/job/minimal_job/", 200)
        for stage in (b"ingest", b"normalize", b"transcribe", b"assemble"):
            expect_contains(case, body, b"<code>" + stage + b"</code>")
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
    finally:
        stop_ui(proc)
        shutil.rmtree(scratch_root, ignore_errors=True)

    print(f"OK: {CHECKS_PASSED} UI checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
