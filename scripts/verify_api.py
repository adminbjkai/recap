#!/usr/bin/env python3
"""Offline smoke validation for the Recap JSON API.

Starts `recap ui` against a scratch copy of the committed minimal job
fixture and exercises the `/api/*` routes added for the modern web app.
Stdlib only; never mutates `scripts/fixtures/*`.
"""

from __future__ import annotations

import http.client
import json
import os
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


def request(
    port: int,
    method: str,
    path: str,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    host_override: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host_override or f"127.0.0.1:{port}")
        for key, value in (headers or {}).items():
            conn.putheader(key, value)
        if method in {"POST", "PUT", "PATCH"}:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        if body:
            conn.send(body)
        resp = conn.getresponse()
        data = resp.read()
        got_headers = {k: v for k, v in resp.getheaders()}
        return resp.status, got_headers, data
    finally:
        conn.close()


def get_json(case: str, port: int, path: str, want: int = 200) -> dict:
    status, headers, body = request(port, "GET", path)
    if status != want:
        fail(case, f"GET {path} status={status}, expected {want}; body={body!r}")
    ctype = headers.get("Content-Type", "")
    if want == 200 and "application/json" not in ctype:
        fail(case, f"GET {path} Content-Type={ctype!r}, expected JSON")
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError as e:
        fail(case, f"GET {path} did not return JSON: {e}; body={body!r}")
    raise AssertionError("unreachable")


def post_json(
    port: int,
    path: str,
    payload: object,
    *,
    token: str | None = None,
    host_override: str | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict[str, str], dict]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": content_type}
    if token is not None:
        headers["X-Recap-Token"] = token
    status, got_headers, got_body = request(
        port,
        "POST",
        path,
        body=body,
        headers=headers,
        host_override=host_override,
    )
    try:
        parsed = json.loads(got_body.decode("utf-8"))
    except ValueError:
        parsed = {"_raw": got_body.decode("utf-8", "replace")}
    return status, got_headers, parsed


def raw_post_recording(
    port: int,
    *,
    path: str,
    body: bytes,
    content_type: str,
    token: str | None,
    content_length_override: int | None = None,
    extra_headers: dict[str, str] | None = None,
    host_override: str | None = None,
) -> tuple[int, dict[str, str], dict]:
    """POST a recording-style upload, supporting a header that lies
    about Content-Length. Used to prove the 413 fast-path rejects a
    claimed-huge body without reading anything.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10.0)
    try:
        conn.putrequest(
            "POST", path, skip_host=True, skip_accept_encoding=True,
        )
        conn.putheader("Host", host_override or f"127.0.0.1:{port}")
        conn.putheader("Content-Type", content_type)
        declared = (
            content_length_override
            if content_length_override is not None
            else len(body)
        )
        conn.putheader("Content-Length", str(declared))
        if token is not None:
            conn.putheader("X-Recap-Token", token)
        conn.putheader("Connection", "close")
        for key, value in (extra_headers or {}).items():
            conn.putheader(key, value)
        conn.endheaders()
        if body:
            try:
                conn.send(body)
            except (BrokenPipeError, ConnectionResetError):
                # The server may close the socket immediately after
                # a short-circuit reject (e.g. 413 on a lying
                # Content-Length). That is OK; we still read the
                # response below.
                pass
        # Signal "no more body bytes" so the server can detect a
        # short body without blocking on `rfile.read`. For full
        # bodies this is a no-op; for lying Content-Length cases it
        # lets the streaming loop hit EOF cleanly.
        try:
            conn.sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        resp = conn.getresponse()
        data = resp.read()
        got_headers = {k: v for k, v in resp.getheaders()}
        try:
            parsed = json.loads(data.decode("utf-8"))
        except ValueError:
            parsed = {"_raw": data.decode("utf-8", "replace")}
        return resp.status, got_headers, parsed
    finally:
        conn.close()


def wait_for_server(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    last_err: str | None = None
    while time.monotonic() < deadline:
        try:
            status, _, _ = request(port, "GET", "/")
            if status == 200:
                return
            last_err = f"status={status}"
        except (ConnectionRefusedError, OSError) as e:
            last_err = str(e)
        time.sleep(0.1)
    fail("startup", f"UI did not respond within {timeout}s (last={last_err})")


def start_ui(
    jobs_root: Path,
    port: int,
    sources_root: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen:
    args = [
        sys.executable, "-m", "recap", "ui",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--jobs-root", str(jobs_root),
        "--sources-root", str(sources_root),
    ]
    env = os.environ.copy()
    env.pop("DEEPGRAM_API_KEY", None)
    # The /api/jobs/start dispatch test relies on the test-only shim
    # documented in recap/ui.py so the verifier can prove validation
    # without spawning a real recap ingest + recap run pair. All other
    # routes are unaffected by the shim.
    env["RECAP_API_STUB_JOB_START"] = "1"
    # Also short-circuit /api/jobs/<id>/runs/insights and
    # /api/jobs/<id>/runs/rich-report so CI never spawns a real
    # `recap insights` call or the 11-stage chain.
    env["RECAP_API_STUB_RUN"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen(
        args,
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def stop_ui(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3.0)


def expect_reason(case: str, got: dict, reason: str) -> None:
    if got.get("reason") != reason:
        fail(case, f"reason={got.get('reason')!r}, expected {reason!r}")


def main() -> int:
    if not FIXTURE.is_dir():
        fail("fixture", f"missing fixture at {FIXTURE}")

    scratch_root = Path(tempfile.mkdtemp(prefix="recap_api_"))
    proc: subprocess.Popen | None = None
    try:
        jobs_root = scratch_root / "jobs"
        jobs_root.mkdir()
        job_dir = jobs_root / "minimal_job"
        shutil.copytree(FIXTURE, job_dir)
        sources_root = scratch_root / "sources"
        sources_root.mkdir()
        # Scratch video file so /api/sources has something to list and
        # the dispatch-success test has a real source to resolve.
        scratch_video = sources_root / "demo.mp4"
        scratch_video.write_bytes(b"fake mp4 bytes for verifier")
        # Plus one file that must be ignored by the listing (wrong ext).
        (sources_root / "notes.txt").write_bytes(b"not a video")

        port = free_port()
        proc = start_ui(jobs_root, port, sources_root)
        wait_for_server(port)

        case = "api-csrf-returns-token"
        csrf = get_json(case, port, "/api/csrf")
        token = csrf.get("token")
        if not isinstance(token, str) or len(token) < 32:
            fail(case, f"bad csrf token shape: {token!r}")
        passed()

        case = "api-sources-lists-scratch-videos"
        payload = get_json(case, port, "/api/sources")
        exts = payload.get("extensions") or []
        if ".mp4" not in exts:
            fail(case, f"extensions missing .mp4: {payload!r}")
        if payload.get("sources_root") != str(sources_root.resolve()):
            fail(case, f"sources_root wrong: {payload!r}")
        if payload.get("sources_root_exists") is not True:
            fail(case, f"sources_root_exists should be True: {payload!r}")
        entries = payload.get("sources") or []
        names = [e.get("name") for e in entries]
        if "demo.mp4" not in names:
            fail(case, f"demo.mp4 not listed: {entries!r}")
        if "notes.txt" in names:
            fail(
                case,
                f"notes.txt unexpectedly listed (wrong ext filter): "
                f"{entries!r}",
            )
        demo_entry = next(e for e in entries if e.get("name") == "demo.mp4")
        if not isinstance(demo_entry.get("size_bytes"), int):
            fail(case, f"demo.mp4 size_bytes missing/invalid: {demo_entry!r}")
        if not isinstance(demo_entry.get("modified_at"), str):
            fail(case, f"demo.mp4 modified_at missing/invalid: {demo_entry!r}")
        passed()

        case = "api-engines-reports-availability"
        payload = get_json(case, port, "/api/engines")
        engines = payload.get("engines") or []
        by_id = {e.get("id"): e for e in engines}
        if "faster-whisper" not in by_id or "deepgram" not in by_id:
            fail(case, f"engines missing entries: {engines!r}")
        if by_id["faster-whisper"].get("available") is not True:
            fail(case, f"faster-whisper must be available: {engines!r}")
        # The verifier subprocess scrubs DEEPGRAM_API_KEY from env, so
        # Deepgram should report as unavailable.
        if by_id["deepgram"].get("available") is not False:
            fail(case, f"deepgram should be unavailable: {engines!r}")
        if payload.get("default") != "faster-whisper":
            fail(case, f"default engine wrong: {payload!r}")
        # Belt-and-braces: no engine entry should carry a raw API key.
        as_text = json.dumps(payload)
        if "DEEPGRAM_API_KEY=" in as_text or " sk-" in as_text:
            fail(case, "engines payload appears to leak a key value")
        passed()

        case = "api-start-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/start",
            {
                "source": {"kind": "sources-root", "name": "demo.mp4"},
                "engine": "faster-whisper",
            },
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-start-invalid-engine"
        status, _, got = post_json(
            port,
            "/api/jobs/start",
            {
                "source": {"kind": "sources-root", "name": "demo.mp4"},
                "engine": "bogus-engine",
            },
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "engine-invalid")
        passed()

        case = "api-start-deepgram-without-key"
        status, _, got = post_json(
            port,
            "/api/jobs/start",
            {
                "source": {"kind": "sources-root", "name": "demo.mp4"},
                "engine": "deepgram",
            },
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "deepgram-unavailable")
        passed()

        case = "api-start-rejects-path-outside-sources-root"
        status, _, got = post_json(
            port,
            "/api/jobs/start",
            {
                "source": {
                    "kind": "absolute-path",
                    "path": "/etc/hosts",
                },
                "engine": "faster-whisper",
            },
            token=token,
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "source-outside-root")
        passed()

        case = "api-start-rejects-traversal-name"
        status, _, got = post_json(
            port,
            "/api/jobs/start",
            {
                "source": {
                    "kind": "sources-root",
                    "name": "../../etc/hosts",
                },
                "engine": "faster-whisper",
            },
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "source-name-invalid")
        passed()

        case = "api-start-accepts-valid-dispatch"
        # Server runs with RECAP_API_STUB_JOB_START=1 so this call
        # proves every validation step without spawning `recap ingest`
        # or `recap run`. The response is 202 with a synthesized
        # stub-<timestamp> job id.
        status, _, got = post_json(
            port,
            "/api/jobs/start",
            {
                "source": {"kind": "sources-root", "name": "demo.mp4"},
                "engine": "faster-whisper",
            },
            token=token,
        )
        if status != 202:
            fail(case, f"expected 202, got {status}: {got!r}")
        if got.get("engine") != "faster-whisper":
            fail(case, f"engine echo wrong: {got!r}")
        if got.get("stub") is not True:
            fail(case, f"response must indicate stub: {got!r}")
        job_id = got.get("job_id")
        if not isinstance(job_id, str) or not job_id.startswith("stub-"):
            fail(case, f"stub job_id wrong: {got!r}")
        if got.get("react_detail") != f"/app/job/{job_id}":
            fail(case, f"react_detail wrong: {got!r}")
        if got.get("legacy_detail") != f"/job/{job_id}/":
            fail(case, f"legacy_detail wrong: {got!r}")
        passed()

        # -----------------------------------------------------------
        # /api/recordings — browser-recorded screen capture upload.
        # The server picks the filename, rejects disallowed content
        # types, enforces Content-Length, and stores under the
        # configured sources root so /api/sources lists it.
        # -----------------------------------------------------------

        # A tiny WebM EBML header is enough for the server: it never
        # parses the video, and the verifier never spawns FFmpeg or a
        # transcription engine against the file. We just care that the
        # bytes round-trip to disk and re-appear under /api/sources.
        fake_webm = (
            b"\x1a\x45\xdf\xa3"  # EBML magic
            b"recap-api-verifier-fake-webm-payload-for-tests"
        )

        case = "api-recordings-missing-csrf"
        status, _, got = raw_post_recording(
            port,
            path="/api/recordings",
            body=fake_webm,
            content_type="video/webm",
            token=None,
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-recordings-bad-content-type"
        status, _, got = raw_post_recording(
            port,
            path="/api/recordings",
            body=fake_webm,
            content_type="application/octet-stream",
            token=token,
        )
        if status != 415:
            fail(case, f"expected 415, got {status}: {got!r}")
        expect_reason(case, got, "content-type")
        passed()

        case = "api-recordings-oversized-rejected-by-header"
        status, _, got = raw_post_recording(
            port,
            path="/api/recordings",
            body=b"",
            content_type="video/webm",
            token=token,
            content_length_override=3 * 1024 * 1024 * 1024,
        )
        if status != 413:
            fail(case, f"expected 413, got {status}: {got!r}")
        expect_reason(case, got, "body-too-large")
        passed()

        case = "api-recordings-saves-webm-and-lists-it"
        status, headers_rec, got = raw_post_recording(
            port,
            path="/api/recordings",
            body=fake_webm,
            content_type="video/webm;codecs=vp9,opus",
            token=token,
        )
        if status != 201:
            fail(case, f"expected 201, got {status}: {got!r}")
        rec_name = got.get("name")
        if (
            not isinstance(rec_name, str)
            or not rec_name.startswith("recording-")
            or not rec_name.endswith(".webm")
        ):
            fail(case, f"bad recording name: {got!r}")
        if got.get("size_bytes") != len(fake_webm):
            fail(case, f"recorded size wrong: {got!r}")
        if got.get("content_type") != "video/webm":
            fail(case, f"content_type echo wrong: {got!r}")
        source_ref = got.get("source") or {}
        if (
            source_ref.get("kind") != "sources-root"
            or source_ref.get("name") != rec_name
        ):
            fail(case, f"source ref wrong: {got!r}")
        # File must exist under the sources root with matching bytes.
        stored = sources_root / rec_name
        if not stored.is_file():
            fail(case, f"recording not stored: {stored}")
        if stored.read_bytes() != fake_webm:
            fail(case, "recording bytes round-trip mismatch")
        # /api/sources must now include it.
        listing = get_json(
            "api-recordings-saves-webm-and-lists-it",
            port, "/api/sources",
        )
        names = [e.get("name") for e in (listing.get("sources") or [])]
        if rec_name not in names:
            fail(case, f"recording missing from /api/sources: {names!r}")
        passed()

        case = "api-recordings-filename-is-server-picked"
        # The server never trusts the Content-Disposition filename; we
        # prove that by sending a path-traversal Content-Disposition and
        # ensuring the stored filename is still a safe recording-* name
        # in the sources root. (The handler just ignores the header.)
        status, _, got2 = raw_post_recording(
            port,
            path="/api/recordings",
            body=fake_webm,
            content_type="video/webm",
            token=token,
            extra_headers={
                "Content-Disposition": (
                    'attachment; filename="../../etc/passwd"'
                ),
            },
        )
        if status != 201:
            fail(case, f"expected 201, got {status}: {got2!r}")
        name2 = got2.get("name") or ""
        if (
            ".." in name2
            or "/" in name2
            or not name2.startswith("recording-")
        ):
            fail(case, f"server-picked name unsafe: {name2!r}")
        # The file must be under sources_root and the traversal target
        # must not exist.
        if not (sources_root / name2).is_file():
            fail(case, f"server-picked recording missing: {name2!r}")
        passed()

        case = "api-recordings-rejects-short-body"
        status, _, got = raw_post_recording(
            port,
            path="/api/recordings",
            body=b"tiny",
            content_type="video/webm",
            token=token,
            content_length_override=len(b"tiny") + 16,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "short-body")
        passed()

        # -----------------------------------------------------------
        # /api/jobs/<id>/runs/{insights,rich-report} — React dispatch
        # endpoints for slice 4b. The server is spawned with
        # RECAP_API_STUB_RUN=1 so the POST handlers skip the real
        # subprocess chain and write a canned success entry
        # synchronously.
        # -----------------------------------------------------------

        case = "api-runs-insights-last-no-run"
        got = get_json(case, port, "/api/jobs/minimal_job/runs/insights/last")
        if got.get("run_type") != "insights":
            fail(case, f"run_type wrong: {got!r}")
        if got.get("status") != "no-run":
            fail(case, f"status should be no-run before any run: {got!r}")
        passed()

        case = "api-runs-rich-report-last-no-run"
        got = get_json(
            case, port, "/api/jobs/minimal_job/runs/rich-report/last",
        )
        if got.get("run_type") != "rich-report":
            fail(case, f"run_type wrong: {got!r}")
        if got.get("status") != "no-run":
            fail(case, f"status should be no-run before any run: {got!r}")
        passed()

        case = "api-runs-insights-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/runs/insights",
            {"provider": "mock"},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-runs-insights-invalid-provider"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/runs/insights",
            {"provider": "openai"},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "provider-invalid")
        passed()

        case = "api-runs-insights-groq-without-key"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/runs/insights",
            {"provider": "groq"},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "groq-unavailable")
        passed()

        case = "api-runs-insights-no-such-job"
        status, _, got = post_json(
            port,
            "/api/jobs/does-not-exist/runs/insights",
            {"provider": "mock"},
            token=token,
        )
        if status != 404:
            fail(case, f"expected 404, got {status}: {got!r}")
        expect_reason(case, got, "no-such-job")
        passed()

        case = "api-runs-insights-dispatch-mock"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/runs/insights",
            {"provider": "mock", "force": True},
            token=token,
        )
        if status != 202:
            fail(case, f"expected 202, got {status}: {got!r}")
        if got.get("run_type") != "insights":
            fail(case, f"run_type wrong: {got!r}")
        if got.get("stub") is not True:
            fail(case, f"expected stub=true in verifier: {got!r}")
        if got.get("provider") != "mock":
            fail(case, f"provider echo wrong: {got!r}")
        if got.get("force") is not True:
            fail(case, f"force echo wrong: {got!r}")
        if got.get("status_url") != "/api/jobs/minimal_job/runs/insights/last":
            fail(case, f"status_url wrong: {got!r}")
        if got.get("react_detail") != "/app/job/minimal_job":
            fail(case, f"react_detail wrong: {got!r}")
        passed()

        case = "api-runs-insights-last-after-stub"
        got = get_json(case, port, "/api/jobs/minimal_job/runs/insights/last")
        if got.get("status") != "success":
            fail(case, f"status should be success after stub: {got!r}")
        if got.get("provider") != "mock":
            fail(case, f"provider persisted wrong: {got!r}")
        if got.get("force") is not True:
            fail(case, f"force persisted wrong: {got!r}")
        if got.get("exit_code") != 0:
            fail(case, f"exit_code wrong: {got!r}")
        for key in ("started_at", "finished_at", "stdout", "stderr"):
            if key not in got:
                fail(case, f"missing key {key!r} in status: {got!r}")
        passed()

        case = "api-runs-rich-report-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/runs/rich-report",
            {},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-runs-rich-report-no-such-job"
        status, _, got = post_json(
            port,
            "/api/jobs/does-not-exist/runs/rich-report",
            {},
            token=token,
            content_type="text/plain",
        )
        if status != 404:
            fail(case, f"expected 404, got {status}: {got!r}")
        expect_reason(case, got, "no-such-job")
        passed()

        case = "api-runs-rich-report-dispatch"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/runs/rich-report",
            {},
            token=token,
            # The rich-report handler ignores the body; empty payload
            # with an arbitrary Content-Type must still be accepted.
            content_type="application/json",
        )
        if status != 202:
            fail(case, f"expected 202, got {status}: {got!r}")
        if got.get("run_type") != "rich-report":
            fail(case, f"run_type wrong: {got!r}")
        if got.get("stub") is not True:
            fail(case, f"expected stub=true: {got!r}")
        if got.get("status_url") != "/api/jobs/minimal_job/runs/rich-report/last":
            fail(case, f"status_url wrong: {got!r}")
        if got.get("react_detail") != "/app/job/minimal_job":
            fail(case, f"react_detail wrong: {got!r}")
        passed()

        case = "api-runs-rich-report-last-after-stub"
        got = get_json(
            case, port, "/api/jobs/minimal_job/runs/rich-report/last",
        )
        if got.get("status") != "success":
            fail(case, f"status should be success: {got!r}")
        stages = got.get("stages") or []
        if not isinstance(stages, list) or len(stages) != 11:
            fail(case, f"expected 11 stages in chain, got {len(stages)}: {got!r}")
        expected_stage_names = [
            "scenes", "dedupe", "window", "similarity", "chapters",
            "rank", "shortlist", "verify", "assemble",
            "export-html", "export-docx",
        ]
        got_names = [s.get("name") for s in stages]
        if got_names != expected_stage_names:
            fail(case, f"stage name order wrong: {got_names!r}")
        for entry in stages:
            if entry.get("status") != "completed":
                fail(case, f"stub stage not completed: {entry!r}")
        if got.get("current_stage") is not None:
            fail(case, f"current_stage should be None after success: {got!r}")
        if got.get("failed_stage") is not None:
            fail(case, f"failed_stage should be None on success: {got!r}")
        passed()

        case = "api-jobs-list-returns-jobs"
        listing = get_json(case, port, "/api/jobs")
        jobs = listing.get("jobs")
        if not isinstance(jobs, list):
            fail(case, f"jobs not a list: {listing!r}")
        if not jobs:
            fail(case, "jobs list unexpectedly empty")
        entry = next(
            (j for j in jobs if j.get("job_id") == "minimal_job"), None,
        )
        if entry is None:
            fail(case, f"minimal_job not in listing: {jobs!r}")
        for key in ("job_id", "status", "artifacts", "urls"):
            if key not in entry:
                fail(case, f"entry missing key {key!r}: {entry!r}")
        urls = entry.get("urls", {})
        for url_key in (
            "detail_html",
            "legacy_detail",
            "legacy_transcript",
            "react_detail",
            "react_transcript",
            "report_md",
            "report_html",
            "report_docx",
            "insights_json",
            "insights",
        ):
            if url_key not in urls:
                fail(case, f"urls missing {url_key!r}: {urls!r}")
        if urls["react_transcript"] != "/app/job/minimal_job/transcript":
            fail(case, f"react_transcript url wrong: {urls!r}")
        if urls["react_detail"] != "/app/job/minimal_job":
            fail(case, f"react_detail url wrong: {urls!r}")
        if urls["insights"] != "/api/jobs/minimal_job/insights":
            fail(case, f"insights url wrong: {urls!r}")
        artifacts = entry.get("artifacts", {})
        if "insights_json" not in artifacts:
            fail(case, f"artifacts missing insights_json: {artifacts!r}")
        if artifacts.get("insights_json") is not False:
            fail(
                case,
                "insights_json artifact flag should be False before "
                f"running insights; got {artifacts.get('insights_json')!r}",
            )
        passed()

        case = "api-jobs-list-skips-malformed-job"
        bad_dir = jobs_root / "not_a_real_job"
        bad_dir.mkdir()
        try:
            (bad_dir / "job.json").write_text("{not json", encoding="utf-8")
            listing = get_json(case, port, "/api/jobs")
            jobs = listing.get("jobs") or []
            if any(j.get("job_id") == "not_a_real_job" for j in jobs):
                fail(case, "malformed job.json leaked into listing")
            # the good entry must still be present
            if not any(j.get("job_id") == "minimal_job" for j in jobs):
                fail(case, "malformed entry dropped the good one too")
        finally:
            shutil.rmtree(bad_dir, ignore_errors=True)
        passed()

        case = "api-job-returns-summary"
        summary = get_json(case, port, "/api/jobs/minimal_job")
        for key in (
            "job_id", "original_filename", "status", "stages",
            "artifacts", "urls",
        ):
            if key not in summary:
                fail(case, f"missing key {key!r}")
        if summary.get("job_id") != "minimal_job":
            fail(case, f"job_id={summary.get('job_id')!r}")
        if summary.get("artifacts", {}).get("transcript_json") is not True:
            fail(case, "transcript_json artifact flag not true")
        if "transcript_json" not in summary.get("urls", {}):
            fail(case, "urls.transcript_json missing")
        passed()

        case = "api-job-404"
        got = get_json(case, port, "/api/jobs/does-not-exist", want=404)
        expect_reason(case, got, "no-such-job")
        passed()

        case = "api-transcript-returns-json"
        transcript = get_json(case, port, "/api/jobs/minimal_job/transcript")
        if not isinstance(transcript.get("segments"), list):
            fail(case, "transcript missing segments list")
        passed()

        case = "api-speaker-names-absent-empty"
        names = get_json(case, port, "/api/jobs/minimal_job/speaker-names")
        if names != {"version": 1, "updated_at": None, "speakers": {}}:
            fail(case, f"unexpected empty speaker names doc: {names!r}")
        passed()

        case = "api-speaker-names-malformed-graceful"
        names_path = job_dir / "speaker_names.json"
        names_path.write_text("{not json", encoding="utf-8")
        names = get_json(case, port, "/api/jobs/minimal_job/speaker-names")
        if names.get("speakers") != {}:
            fail(case, f"malformed speaker_names did not degrade: {names!r}")
        names_path.unlink()
        passed()

        case = "api-post-speaker-names-missing-token"
        status, _, got = post_json(
            port, "/api/jobs/minimal_job/speaker-names",
            {"speakers": {"0": "Ada"}},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-post-speaker-names-forged-host"
        status, _, got = post_json(
            port, "/api/jobs/minimal_job/speaker-names",
            {"speakers": {"0": "Ada"}},
            token=token,
            host_override="bogus.example:8765",
        )
        if status != 403:
            fail(case, f"expected 403, got {status}")
        expect_reason(case, got, "host")
        passed()

        case = "api-post-speaker-names-bad-key-shape"
        status, _, got = post_json(
            port, "/api/jobs/minimal_job/speaker-names",
            {"speakers": {"host": "Ada"}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}")
        expect_reason(case, got, "bad-key-shape")
        if names_path.exists():
            fail(case, "speaker_names.json written on bad key")
        passed()

        case = "api-post-speaker-names-too-long"
        status, _, got = post_json(
            port, "/api/jobs/minimal_job/speaker-names",
            {"speakers": {"0": "x" * 81}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}")
        expect_reason(case, got, "too-long")
        if names_path.exists():
            fail(case, "speaker_names.json written on too-long value")
        passed()

        case = "api-post-speaker-names-success"
        status, _, got = post_json(
            port, "/api/jobs/minimal_job/speaker-names",
            {"speakers": {"0": " Ada ", "1": "Lin"}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("speakers") != {"0": "Ada", "1": "Lin"}:
            fail(case, f"stored speakers wrong: {got!r}")
        disk = json.loads(names_path.read_text(encoding="utf-8"))
        if disk.get("speakers") != got.get("speakers"):
            fail(case, f"disk speakers mismatch: {disk!r} vs {got!r}")
        again = get_json(case, port, "/api/jobs/minimal_job/speaker-names")
        if again.get("speakers") != {"0": "Ada", "1": "Lin"}:
            fail(case, f"GET after POST mismatch: {again!r}")
        status, headers, raw_body = request(
            port, "GET", "/job/minimal_job/speaker_names.json",
        )
        if status != 200:
            fail(case, f"raw speaker_names.json status={status}")
        if "application/json" not in headers.get("Content-Type", ""):
            fail(case, "raw speaker_names.json did not serve as JSON")
        raw = json.loads(raw_body.decode("utf-8"))
        if raw.get("speakers") != {"0": "Ada", "1": "Lin"}:
            fail(case, f"raw artifact mismatch: {raw!r}")
        passed()

        case = "api-post-speaker-names-empty-clears"
        status, _, got = post_json(
            port, "/api/jobs/minimal_job/speaker-names",
            {"speakers": {"0": "", "1": "Lin"}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("speakers") != {"1": "Lin"}:
            fail(case, f"empty value did not clear mapping: {got!r}")
        passed()

        # -----------------------------------------------------------
        # /api/jobs/<id>/chapters + /api/jobs/<id>/chapter-titles.
        # The minimal fixture ships with transcript.json and a
        # single-chapter chapter_candidates.json, so we temporarily
        # move that file aside to exercise the empty baseline, then
        # seed a richer two-chapter artifact for the main flow, and
        # restore the original bytes at the end of the block so
        # later tests see the fixture scratch copy unchanged.
        # -----------------------------------------------------------
        cand_path = job_dir / "chapter_candidates.json"
        i_path = job_dir / "insights.json"
        titles_path = job_dir / "chapter_titles.json"
        fixture_cand_bytes = cand_path.read_bytes() if cand_path.exists() else None
        if cand_path.exists():
            cand_path.unlink()

        case = "api-chapters-empty-when-no-artifacts"
        got = get_json(case, port, "/api/jobs/minimal_job/chapters")
        if got.get("chapters") != []:
            fail(case, f"expected empty chapters, got: {got!r}")
        srcs = got.get("sources") or {}
        if srcs.get("chapter_candidates") is not False:
            fail(case, f"chapter_candidates flag should be False: {got!r}")
        if srcs.get("insights") is not False:
            fail(case, f"insights flag should be False: {got!r}")
        passed()

        case = "api-chapter-titles-empty-when-absent"
        got = get_json(
            case, port, "/api/jobs/minimal_job/chapter-titles",
        )
        if got != {"version": 1, "updated_at": None, "titles": {}}:
            fail(case, f"expected empty chapter-titles doc: {got!r}")
        passed()

        # Seed chapter_candidates.json; chapters list should reflect it.
        cand_path.write_text(
            json.dumps({
                "chapter_count": 2,
                "min_chapter_seconds": 1.0,
                "pause_seconds": 0.5,
                "source_signal": "pauses",
                "transcript_source": "segments",
                "video": {"path": "analysis.mp4"},
                "chapters": [
                    {
                        "index": 1,
                        "start_seconds": 0.0,
                        "end_seconds": 60.0,
                        "first_segment_id": 0,
                        "last_segment_id": 5,
                        "segment_ids": [0, 1, 2, 3, 4, 5],
                        "text": (
                            "Welcome to the call. We'll cover three "
                            "topics today: onboarding, pricing, and "
                            "next steps."
                        ),
                        "trigger": "start",
                    },
                    {
                        "index": 2,
                        "start_seconds": 60.0,
                        "end_seconds": 120.0,
                        "first_segment_id": 6,
                        "last_segment_id": 12,
                        "segment_ids": [6, 7, 8, 9, 10, 11, 12],
                        "text": "Let's dig into onboarding first.",
                        "trigger": "pause",
                    },
                ],
            }),
            encoding="utf-8",
        )

        case = "api-chapters-uses-candidates"
        got = get_json(case, port, "/api/jobs/minimal_job/chapters")
        chs = got.get("chapters") or []
        if len(chs) != 2:
            fail(case, f"expected 2 chapters, got {len(chs)}: {got!r}")
        if [c.get("index") for c in chs] != [1, 2]:
            fail(case, f"chapter order wrong: {chs!r}")
        if chs[0].get("start_seconds") != 0.0:
            fail(case, f"start_seconds wrong: {chs[0]!r}")
        if chs[0].get("end_seconds") != 60.0:
            fail(case, f"end_seconds wrong: {chs[0]!r}")
        if not isinstance(chs[0].get("fallback_title"), str):
            fail(case, f"fallback_title missing: {chs[0]!r}")
        if chs[0].get("fallback_title") == "" or chs[0].get(
            "fallback_title"
        ) == "Chapter 1":
            # The text starts with "Welcome to the call." — the
            # first-sentence derivation should pick that up, not the
            # generic fallback.
            fail(case, f"fallback_title not derived: {chs[0]!r}")
        if chs[0].get("custom_title") is not None:
            fail(case, f"custom_title should be None: {chs[0]!r}")
        if chs[0].get("display_title") != chs[0].get("fallback_title"):
            fail(case, f"display_title should equal fallback: {chs[0]!r}")
        passed()

        # Seed insights.json — chapters should pick up summaries and
        # when candidates are absent the chapters still render from
        # insights alone.
        insights_doc = {
            "version": 1,
            "provider": "mock",
            "model": "mock-v1",
            "generated_at": "2026-04-20T00:00:00Z",
            "sources": {
                "transcript": "transcript.json",
                "chapters": "chapter_candidates.json",
                "speaker_names": None,
                "selected_frames": None,
            },
            "overview": {
                "title": "Cue test",
                "short_summary": "s",
                "detailed_summary": "s",
                "quick_bullets": [],
            },
            "chapters": [
                {
                    "index": 1,
                    "start_seconds": 0.0,
                    "end_seconds": 60.0,
                    "title": "Intro and agenda",
                    "summary": "Three topics were introduced.",
                    "bullets": ["Onboarding", "Pricing"],
                    "action_items": [],
                    "speaker_focus": [],
                },
                {
                    "index": 2,
                    "start_seconds": 60.0,
                    "end_seconds": 120.0,
                    "title": "Onboarding deep-dive",
                    "summary": "Walkthrough of onboarding steps.",
                    "bullets": [],
                    "action_items": ["Ship migration guide"],
                    "speaker_focus": [],
                },
            ],
            "action_items": [
                {"text": "Ship migration guide", "chapter_index": 2},
            ],
        }
        i_path.write_text(
            json.dumps(insights_doc), encoding="utf-8",
        )

        case = "api-chapters-uses-insights-when-present"
        got = get_json(case, port, "/api/jobs/minimal_job/chapters")
        chs = got.get("chapters") or []
        if chs[0].get("fallback_title") != "Intro and agenda":
            fail(case, f"should prefer insights title: {chs[0]!r}")
        if chs[0].get("summary") != "Three topics were introduced.":
            fail(case, f"summary missing: {chs[0]!r}")
        if chs[0].get("bullets") != ["Onboarding", "Pricing"]:
            fail(case, f"bullets missing: {chs[0]!r}")
        if chs[1].get("action_items") != ["Ship migration guide"]:
            fail(case, f"action_items missing: {chs[1]!r}")
        passed()

        case = "api-chapters-insights-only"
        cand_path.unlink()
        got = get_json(case, port, "/api/jobs/minimal_job/chapters")
        chs = got.get("chapters") or []
        if len(chs) != 2 or chs[0].get("start_seconds") != 0.0:
            fail(case, f"insights-only chapters wrong: {got!r}")
        if got.get("sources", {}).get("chapter_candidates") is not False:
            fail(case, f"chapter_candidates flag should be False: {got!r}")
        if got.get("sources", {}).get("insights") is not True:
            fail(case, f"insights flag should be True: {got!r}")
        passed()

        case = "api-chapter-titles-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"1": "Kickoff"}},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-chapter-titles-forged-host"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"1": "Kickoff"}},
            token=token,
            host_override="bogus.example:8765",
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "host")
        passed()

        case = "api-chapter-titles-bad-key-shape"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"notint": "Kickoff"}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-key-shape")
        passed()

        case = "api-chapter-titles-too-long"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"1": "x" * 121}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "too-long")
        passed()

        case = "api-chapter-titles-control-chars"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"1": "Kickoff\x01"}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-value")
        passed()

        case = "api-chapter-titles-success"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"1": "  Kickoff  ", "2": "Onboarding"}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("titles") != {"1": "Kickoff", "2": "Onboarding"}:
            fail(case, f"titles round-trip wrong: {got!r}")
        disk = json.loads(titles_path.read_text(encoding="utf-8"))
        if disk.get("titles") != got.get("titles"):
            fail(case, f"disk mismatch: {disk!r}")
        passed()

        case = "api-chapters-uses-custom-title"
        got = get_json(case, port, "/api/jobs/minimal_job/chapters")
        chs = got.get("chapters") or []
        if chs[0].get("custom_title") != "Kickoff":
            fail(case, f"custom_title missing: {chs[0]!r}")
        if chs[0].get("display_title") != "Kickoff":
            fail(case, f"display_title not custom: {chs[0]!r}")
        if chs[0].get("fallback_title") != "Intro and agenda":
            fail(case, f"fallback_title lost: {chs[0]!r}")
        if got.get("sources", {}).get("chapter_titles_overlay") is not True:
            fail(case, f"overlay flag should be True: {got!r}")
        passed()

        case = "api-chapter-titles-empty-clears"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/chapter-titles",
            {"titles": {"1": "", "2": "Onboarding"}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("titles") != {"2": "Onboarding"}:
            fail(case, f"empty value did not clear: {got!r}")
        passed()

        case = "api-chapter-titles-malformed-graceful"
        titles_path.write_text("{not json", encoding="utf-8")
        got = get_json(
            case, port, "/api/jobs/minimal_job/chapter-titles",
        )
        if got.get("titles") != {}:
            fail(case, f"malformed overlay should degrade: {got!r}")
        got2 = get_json(case, port, "/api/jobs/minimal_job/chapters")
        if got2.get("chapters") and got2["chapters"][0].get(
            "custom_title"
        ) is not None:
            fail(case, "malformed overlay leaked into chapters view")
        passed()

        # Teardown: remove seeded artifacts and restore the fixture's
        # original chapter_candidates.json bytes so later tests start
        # from the clean fixture copy.
        i_path.unlink()
        if titles_path.exists():
            titles_path.unlink()
        if cand_path.exists():
            cand_path.unlink()
        if fixture_cand_bytes is not None:
            cand_path.write_bytes(fixture_cand_bytes)

        # -----------------------------------------------------------
        # /api/jobs/<id>/frames + /api/jobs/<id>/frame-review. The
        # minimal fixture ships with scene-001..003.jpg +
        # selected_frames.json already, so the merged view has real
        # data without any additional seeding. We move selected_frames
        # aside first to exercise the "candidates on disk but no
        # selected_frames.json yet" path, then restore it before the
        # main flow.
        # -----------------------------------------------------------
        fr_path = job_dir / "frame_review.json"
        sel_path = job_dir / "selected_frames.json"
        fixture_sel_bytes = (
            sel_path.read_bytes() if sel_path.exists() else None
        )

        # Exercise candidates-only view (selected_frames absent).
        if sel_path.exists():
            sel_path.unlink()
        case = "api-frames-candidates-only"
        got = get_json(case, port, "/api/jobs/minimal_job/frames")
        frames = got.get("frames") or []
        if not frames:
            fail(case, f"expected on-disk candidate frames: {got!r}")
        names = [f.get("frame_file") for f in frames]
        if "scene-001.jpg" not in names:
            fail(case, f"scene-001.jpg missing: {names!r}")
        first = next(f for f in frames if f.get("frame_file") == "scene-001.jpg")
        if first.get("image_url") != "/job/minimal_job/candidate_frames/scene-001.jpg":
            fail(case, f"image_url wrong: {first!r}")
        if first.get("on_disk") is not True:
            fail(case, f"on_disk should be True: {first!r}")
        if got.get("sources", {}).get("selected_frames") is not False:
            fail(case, f"selected_frames flag should be False: {got!r}")
        if got.get("sources", {}).get("candidate_frames_dir") is not True:
            fail(case, f"candidate_frames_dir flag should be True: {got!r}")
        passed()

        # Restore selected_frames.json and exercise the enriched view.
        if fixture_sel_bytes is not None:
            sel_path.write_bytes(fixture_sel_bytes)

        case = "api-frames-enriched-with-selected"
        got = get_json(case, port, "/api/jobs/minimal_job/frames")
        frames = got.get("frames") or []
        s1 = next(
            (f for f in frames if f.get("frame_file") == "scene-001.jpg"),
            None,
        )
        if s1 is None:
            fail(case, f"scene-001.jpg missing: {frames!r}")
        # Fixture's selected_frames.json for scene-001.jpg sets a
        # hero/supporting decision and chapter_index=1.
        if s1.get("chapter_index") != 1:
            fail(case, f"chapter_index wrong: {s1!r}")
        if not s1.get("decision"):
            fail(case, f"decision missing: {s1!r}")
        if got.get("sources", {}).get("selected_frames") is not True:
            fail(case, f"selected_frames flag should be True: {got!r}")
        # Frame-review overlay flag should be False (no overlay yet).
        if got.get("sources", {}).get("frame_review_overlay") is not False:
            fail(case, f"frame_review_overlay should be False: {got!r}")
        # Chapter context should be populated too.
        chs = got.get("chapters") or []
        if not chs or chs[0].get("index") != 1:
            fail(case, f"chapter context missing: {got!r}")
        passed()

        case = "api-frame-review-empty-when-absent"
        got = get_json(
            case, port, "/api/jobs/minimal_job/frame-review",
        )
        if got != {"version": 1, "updated_at": None, "frames": {}}:
            fail(case, f"expected empty overlay: {got!r}")
        passed()

        case = "api-frame-review-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {"frames": {"scene-001.jpg": {"decision": "keep", "note": "ok"}}},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-frame-review-traversal-filename"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {"frames": {"../../etc/passwd": {"decision": "keep"}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-key-shape")
        passed()

        case = "api-frame-review-disallowed-extension"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {"frames": {"evil.sh": {"decision": "keep"}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-key-shape")
        passed()

        case = "api-frame-review-bad-decision"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {"frames": {"scene-001.jpg": {"decision": "maybe"}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-decision")
        passed()

        case = "api-frame-review-note-too-long"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {
                "frames": {
                    "scene-001.jpg": {
                        "decision": "keep",
                        "note": "x" * 301,
                    },
                },
            },
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "too-long")
        passed()

        case = "api-frame-review-control-chars"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {
                "frames": {
                    "scene-001.jpg": {
                        "decision": "keep",
                        "note": "bad\x01note",
                    },
                },
            },
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-value")
        passed()

        case = "api-frame-review-success"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {
                "frames": {
                    "scene-001.jpg": {
                        "decision": "keep",
                        "note": "  hero looks right  ",
                    },
                    "scene-002.jpg": {
                        "decision": "reject",
                        "note": "",
                    },
                },
            },
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        stored = got.get("frames") or {}
        if stored.get("scene-001.jpg") != {
            "decision": "keep",
            "note": "hero looks right",
        }:
            fail(case, f"scene-001 entry wrong: {stored!r}")
        if stored.get("scene-002.jpg") != {
            "decision": "reject",
            "note": "",
        }:
            fail(case, f"scene-002 entry wrong: {stored!r}")
        disk = json.loads(fr_path.read_text(encoding="utf-8"))
        if disk.get("frames") != stored:
            fail(case, f"disk mismatch: {disk!r}")
        passed()

        case = "api-frames-reflects-review-overlay"
        got = get_json(case, port, "/api/jobs/minimal_job/frames")
        frames = got.get("frames") or []
        by_name = {f.get("frame_file"): f for f in frames}
        if by_name.get("scene-001.jpg", {}).get("review") != {
            "decision": "keep",
            "note": "hero looks right",
        }:
            fail(
                case,
                f"overlay not merged: {by_name.get('scene-001.jpg')!r}",
            )
        if by_name.get("scene-002.jpg", {}).get("review") != {
            "decision": "reject",
            "note": "",
        }:
            fail(
                case,
                f"reject overlay not merged: {by_name.get('scene-002.jpg')!r}",
            )
        if got.get("sources", {}).get("frame_review_overlay") is not True:
            fail(case, f"overlay flag should be True: {got!r}")
        passed()

        case = "api-frame-review-unset-removes"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/frame-review",
            {
                "frames": {
                    "scene-001.jpg": {"decision": "unset"},
                },
            },
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if "scene-001.jpg" in (got.get("frames") or {}):
            fail(case, f"unset did not remove entry: {got!r}")
        # scene-002 mapping should still be there.
        if "scene-002.jpg" not in (got.get("frames") or {}):
            fail(case, f"unset dropped unrelated entry: {got!r}")
        passed()

        case = "api-frame-review-malformed-graceful"
        fr_path.write_text("{not json", encoding="utf-8")
        got = get_json(
            case, port, "/api/jobs/minimal_job/frame-review",
        )
        if got.get("frames") != {}:
            fail(case, f"malformed overlay not graceful: {got!r}")
        got2 = get_json(case, port, "/api/jobs/minimal_job/frames")
        for entry in (got2.get("frames") or []):
            if entry.get("review", {}).get("decision") is not None:
                fail(case, "malformed overlay leaked into merged view")
        passed()

        # Teardown: remove the overlay file so later tests see the
        # fixture scratch copy unchanged.
        if fr_path.exists():
            fr_path.unlink()

        # -----------------------------------------------------------
        # /api/jobs/<id>/transcript-notes — per-row correction + note
        # overlay. Mirrors the speaker-names / chapter-titles /
        # frame-review contract: empty fields clear, malformed input
        # is rejected, malformed stored overlay degrades gracefully,
        # and the upstream transcript.json is never mutated.
        # -----------------------------------------------------------
        tn_path = job_dir / "transcript_notes.json"
        transcript_bytes_before = (
            (job_dir / "transcript.json").read_bytes()
            if (job_dir / "transcript.json").exists()
            else None
        )

        case = "api-transcript-notes-empty-when-absent"
        got = get_json(
            case, port, "/api/jobs/minimal_job/transcript-notes",
        )
        if got != {"version": 1, "updated_at": None, "items": {}}:
            fail(case, f"expected empty overlay: {got!r}")
        passed()

        case = "api-transcript-notes-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"utt-0": {"correction": "fix"}}},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-transcript-notes-bad-key"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"../../evil": {"correction": "x"}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-key-shape")
        passed()

        case = "api-transcript-notes-bad-key-shape-no-prefix"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"row-0": {"correction": "x"}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-key-shape")
        passed()

        case = "api-transcript-notes-correction-too-long"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"utt-0": {"correction": "x" * 2001}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "too-long")
        passed()

        case = "api-transcript-notes-note-too-long"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"utt-0": {"note": "n" * 1001}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "too-long")
        passed()

        case = "api-transcript-notes-control-chars"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"utt-0": {"correction": "bad\x01text"}}},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-value")
        passed()

        case = "api-transcript-notes-success"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {
                "items": {
                    "utt-0": {
                        "correction": "  Hello world  ",
                        "note": "Opening remarks\nfollow up",
                    },
                    "seg-3": {"note": "Check this later"},
                },
            },
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        stored = got.get("items") or {}
        if stored.get("utt-0") != {
            "correction": "Hello world",
            "note": "Opening remarks\nfollow up",
        }:
            fail(case, f"utt-0 wrong: {stored!r}")
        if stored.get("seg-3") != {"note": "Check this later"}:
            fail(case, f"seg-3 wrong: {stored!r}")
        on_disk = json.loads(tn_path.read_text(encoding="utf-8"))
        if on_disk.get("items") != stored:
            fail(case, f"disk mismatch: {on_disk!r}")
        passed()

        case = "api-transcript-notes-roundtrip"
        got = get_json(
            case, port, "/api/jobs/minimal_job/transcript-notes",
        )
        if got.get("items", {}).get("utt-0", {}).get("correction") != "Hello world":
            fail(case, f"GET after POST mismatch: {got!r}")
        passed()

        case = "api-transcript-notes-empty-clears-field"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"utt-0": {"correction": ""}}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        # Correction cleared; note preserved from prior POST.
        if got.get("items", {}).get("utt-0") != {
            "note": "Opening remarks\nfollow up",
        }:
            fail(
                case,
                "empty correction did not clear just that field: "
                f"{got!r}",
            )
        passed()

        case = "api-transcript-notes-empty-item-clears-mapping"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"utt-0": {"correction": "", "note": ""}}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if "utt-0" in (got.get("items") or {}):
            fail(
                case,
                f"empty correction + empty note did not drop mapping: "
                f"{got!r}",
            )
        # seg-3 still present.
        if "seg-3" not in (got.get("items") or {}):
            fail(case, f"unrelated entry dropped: {got!r}")
        passed()

        case = "api-transcript-notes-upstream-transcript-unchanged"
        now = (
            (job_dir / "transcript.json").read_bytes()
            if (job_dir / "transcript.json").exists()
            else None
        )
        if now != transcript_bytes_before:
            fail(
                case,
                "transcript_notes endpoint mutated transcript.json",
            )
        passed()

        case = "api-transcript-notes-malformed-graceful"
        tn_path.write_text("{not json", encoding="utf-8")
        got = get_json(
            case, port, "/api/jobs/minimal_job/transcript-notes",
        )
        if got.get("items") != {}:
            fail(case, f"malformed overlay not graceful: {got!r}")
        passed()

        case = "api-transcript-notes-static-artifact-serves"
        # After clearing mapping above, re-write a minimal payload and
        # confirm raw serving works under the static whitelist.
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/transcript-notes",
            {"items": {"seg-3": {"note": "Check this later"}}},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        code, headers, raw = request(
            port, "GET", "/job/minimal_job/transcript_notes.json",
        )
        if code != 200:
            fail(case, f"raw artifact status={code}")
        if "application/json" not in headers.get("Content-Type", ""):
            fail(case, "raw artifact not served as JSON")
        parsed_raw = json.loads(raw.decode("utf-8"))
        if parsed_raw.get("items", {}).get("seg-3", {}).get(
            "note"
        ) != "Check this later":
            fail(case, f"raw artifact mismatch: {parsed_raw!r}")
        passed()

        # Teardown: remove the overlay so later tests see the clean
        # fixture scratch copy.
        if tn_path.exists():
            tn_path.unlink()

        case = "api-insights-endpoint-404-when-absent"
        i_path = job_dir / "insights.json"
        if i_path.exists():
            i_path.unlink()
        got = get_json(
            case, port, "/api/jobs/minimal_job/insights", want=404,
        )
        expect_reason(case, got, "no-insights")
        passed()

        case = "api-insights-artifact-flag-and-raw-file"
        insights_doc = {
            "version": 1,
            "provider": "mock",
            "model": "mock-v1",
            "generated_at": "2026-04-20T00:00:00Z",
            "sources": {
                "transcript": "transcript.json",
                "chapters": None,
                "speaker_names": None,
                "selected_frames": None,
            },
            "overview": {
                "title": "Check",
                "short_summary": "s",
                "detailed_summary": "s",
                "quick_bullets": ["bullet"],
            },
            "chapters": [],
            "action_items": [],
        }
        (job_dir / "insights.json").write_text(
            json.dumps(insights_doc), encoding="utf-8",
        )
        summary_after = get_json(case, port, "/api/jobs/minimal_job")
        arts = summary_after.get("artifacts", {})
        if arts.get("insights_json") is not True:
            fail(
                case,
                f"insights_json artifact flag not True after writing "
                f"insights.json: {arts!r}",
            )
        insights_url = summary_after.get("urls", {}).get("insights_json")
        if insights_url != "/job/minimal_job/insights.json":
            fail(case, f"insights_json URL wrong: {insights_url!r}")
        status, headers, body = request(
            port, "GET", "/job/minimal_job/insights.json",
        )
        if status != 200:
            fail(case, f"raw insights.json status={status}")
        if "application/json" not in headers.get("Content-Type", ""):
            fail(case, "raw insights.json did not serve as JSON")
        parsed = json.loads(body.decode("utf-8"))
        if parsed.get("overview", {}).get("title") != "Check":
            fail(case, f"raw insights.json content mismatch: {parsed!r}")
        passed()

        case = "api-insights-endpoint-returns-doc"
        payload = get_json(case, port, "/api/jobs/minimal_job/insights")
        if payload.get("overview", {}).get("title") != "Check":
            fail(case, f"insights endpoint content mismatch: {payload!r}")
        if payload.get("provider") != "mock":
            fail(case, f"insights provider wrong: {payload!r}")
        passed()

        case = "api-insights-endpoint-malformed-gives-clean-error"
        (job_dir / "insights.json").write_text(
            "{not json", encoding="utf-8",
        )
        got = get_json(
            case, port, "/api/jobs/minimal_job/insights", want=500,
        )
        expect_reason(case, got, "insights-unreadable")
        (job_dir / "insights.json").unlink()
        passed()

        # -----------------------------------------------------------
        # /api/library + /api/jobs/<id>/metadata — local library
        # organization (project/folder/archive). The sidecar lives at
        # <jobs_root>/.recap_library.json; writes happen under the
        # process-wide library lock, atomic tmp → rename. Missing or
        # malformed sidecar degrades to empty metadata.
        # -----------------------------------------------------------
        library_sidecar = jobs_root / ".recap_library.json"

        case = "api-library-baseline-empty"
        got = get_json(case, port, "/api/library")
        if got.get("sidecar_present") is not False:
            fail(case, f"sidecar should be absent: {got!r}")
        if got.get("projects") != []:
            fail(case, f"projects should be empty: {got!r}")
        counts = got.get("counts") or {}
        if counts.get("total") != 1:
            fail(case, f"total jobs count wrong: {got!r}")
        if counts.get("active") != 1 or counts.get("archived") != 0:
            fail(case, f"active/archived split wrong: {got!r}")
        passed()

        case = "api-job-summary-adds-display-title-default"
        summary = get_json(case, port, "/api/jobs/minimal_job")
        if summary.get("display_title") != summary.get("original_filename"):
            fail(case, f"display_title default fallback wrong: {summary!r}")
        if summary.get("custom_title") is not None:
            fail(case, f"custom_title should be None: {summary!r}")
        if summary.get("project") is not None:
            fail(case, f"project should be None: {summary!r}")
        if summary.get("archived") is not False:
            fail(case, f"archived should be False: {summary!r}")
        if summary.get("urls", {}).get("metadata") != (
            "/api/jobs/minimal_job/metadata"
        ):
            fail(case, f"urls.metadata wrong: {summary!r}")
        passed()

        case = "api-metadata-missing-csrf"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"title": "Demo call"},
        )
        if status != 403:
            fail(case, f"expected 403, got {status}: {got!r}")
        expect_reason(case, got, "csrf")
        passed()

        case = "api-metadata-empty-body-rejected"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-schema")
        passed()

        case = "api-metadata-bad-title-type"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"title": 42},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-value")
        passed()

        case = "api-metadata-title-too-long"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"title": "x" * 121},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "too-long")
        passed()

        case = "api-metadata-project-control-char"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"project": "Demos\x01"},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-value")
        passed()

        case = "api-metadata-bad-archived-type"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"archived": "yes"},
            token=token,
        )
        if status != 400:
            fail(case, f"expected 400, got {status}: {got!r}")
        expect_reason(case, got, "bad-value")
        passed()

        case = "api-metadata-no-such-job"
        status, _, got = post_json(
            port,
            "/api/jobs/does-not-exist/metadata",
            {"title": "Nope"},
            token=token,
        )
        if status != 404:
            fail(case, f"expected 404, got {status}: {got!r}")
        expect_reason(case, got, "no-such-job")
        passed()

        case = "api-metadata-title-project-save"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"title": "  Demo call  ", "project": "  Client demos  "},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("display_title") != "Demo call":
            fail(case, f"display_title not applied: {got!r}")
        if got.get("custom_title") != "Demo call":
            fail(case, f"custom_title not applied: {got!r}")
        if got.get("project") != "Client demos":
            fail(case, f"project not applied: {got!r}")
        if got.get("archived") is not False:
            fail(case, f"archived should remain False: {got!r}")
        if not library_sidecar.is_file():
            fail(case, "library sidecar was not created on first POST")
        disk = json.loads(library_sidecar.read_text(encoding="utf-8"))
        if disk.get("jobs", {}).get("minimal_job", {}).get(
            "title"
        ) != "Demo call":
            fail(case, f"sidecar missing stored title: {disk!r}")
        passed()

        case = "api-library-lists-projects-after-save"
        lib = get_json(case, port, "/api/library")
        projects = lib.get("projects") or []
        names = [p.get("name") for p in projects]
        if "Client demos" not in names:
            fail(case, f"projects missing Client demos: {lib!r}")
        client = next(p for p in projects if p.get("name") == "Client demos")
        if client.get("active") != 1 or client.get("archived") != 0:
            fail(case, f"client demos rollup wrong: {client!r}")
        if lib.get("sidecar_present") is not True:
            fail(case, f"sidecar_present should be True: {lib!r}")
        passed()

        case = "api-metadata-archive-then-exclude-from-default"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"archived": True},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("archived") is not True:
            fail(case, f"archived did not flip True: {got!r}")
        listing = get_json(case, port, "/api/jobs")
        ids = [j.get("job_id") for j in (listing.get("jobs") or [])]
        if "minimal_job" in ids:
            fail(
                case,
                f"archived job leaked into default listing: {ids!r}",
            )
        if listing.get("include_archived") is not False:
            fail(
                case,
                f"include_archived flag should be False by default: "
                f"{listing!r}",
            )
        passed()

        case = "api-jobs-include-archived-opt-in"
        listing = get_json(
            case, port, "/api/jobs?include_archived=1",
        )
        if listing.get("include_archived") is not True:
            fail(case, f"include_archived echo wrong: {listing!r}")
        ids = [j.get("job_id") for j in (listing.get("jobs") or [])]
        if "minimal_job" not in ids:
            fail(
                case,
                f"archived job missing from ?include_archived=1: {ids!r}",
            )
        # Direct per-job fetch must always include the archived job.
        direct = get_json(case, port, "/api/jobs/minimal_job")
        if direct.get("archived") is not True:
            fail(case, "direct /api/jobs/<id> failed to reflect archive")
        passed()

        case = "api-library-counts-after-archive"
        lib = get_json(case, port, "/api/library")
        counts = lib.get("counts") or {}
        if counts.get("archived") != 1 or counts.get("active") != 0:
            fail(case, f"counts.archived should be 1: {lib!r}")
        # The archived job's project rollup must now attribute to
        # `archived`, not `active`.
        client = next(
            (p for p in (lib.get("projects") or []) if p.get("name") == "Client demos"),
            None,
        )
        if client is None:
            fail(case, "project vanished unexpectedly")
        if client.get("active") != 0 or client.get("archived") != 1:
            fail(case, f"rollup after archive wrong: {client!r}")
        passed()

        case = "api-metadata-unarchive-and-clear-project"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"archived": False, "project": ""},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("archived") is not False:
            fail(case, f"archived did not flip False: {got!r}")
        if got.get("project") is not None:
            fail(case, f"project empty-string did not clear: {got!r}")
        if got.get("custom_title") != "Demo call":
            fail(case, f"custom_title lost on partial PATCH: {got!r}")
        passed()

        case = "api-metadata-clear-title-reverts-display"
        status, _, got = post_json(
            port,
            "/api/jobs/minimal_job/metadata",
            {"title": ""},
            token=token,
        )
        if status != 200:
            fail(case, f"expected 200, got {status}: {got!r}")
        if got.get("custom_title") is not None:
            fail(case, f"custom_title should be cleared: {got!r}")
        if got.get("display_title") != got.get("original_filename"):
            fail(
                case,
                f"display_title should revert to original_filename: {got!r}",
            )
        # After clearing every field the sidecar's entry should be
        # pruned (empty object), so the library doesn't accumulate
        # dead rows.
        disk = json.loads(library_sidecar.read_text(encoding="utf-8"))
        if "minimal_job" in (disk.get("jobs") or {}):
            fail(
                case,
                "sidecar still carries a row after every field was "
                "cleared",
            )
        passed()

        case = "api-library-malformed-graceful"
        library_sidecar.write_text("{not json", encoding="utf-8")
        got = get_json(case, port, "/api/library")
        if got.get("projects") != []:
            fail(case, f"malformed sidecar not graceful: {got!r}")
        if got.get("counts", {}).get("total") != 1:
            fail(
                case,
                f"malformed sidecar dropped job enumeration: {got!r}",
            )
        # And /api/jobs should still work, treating the job as
        # unarchived + no custom metadata.
        listing = get_json(case, port, "/api/jobs")
        ids = [j.get("job_id") for j in (listing.get("jobs") or [])]
        if "minimal_job" not in ids:
            fail(case, "malformed sidecar dropped job from listing")
        library_sidecar.unlink()
        passed()

        print(f"OK: {CHECKS_PASSED} API checks passed")
        return 0
    finally:
        if proc is not None:
            stop_ui(proc)
        shutil.rmtree(scratch_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
