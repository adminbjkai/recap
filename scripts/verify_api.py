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


def start_ui(jobs_root: Path, port: int, sources_root: Path) -> subprocess.Popen:
    args = [
        sys.executable, "-m", "recap", "ui",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--jobs-root", str(jobs_root),
        "--sources-root", str(sources_root),
    ]
    env = os.environ.copy()
    env.pop("DEEPGRAM_API_KEY", None)
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

        port = free_port()
        proc = start_ui(jobs_root, port, sources_root)
        wait_for_server(port)

        case = "api-csrf-returns-token"
        csrf = get_json(case, port, "/api/csrf")
        token = csrf.get("token")
        if not isinstance(token, str) or len(token) < 32:
            fail(case, f"bad csrf token shape: {token!r}")
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
            "legacy_transcript",
            "react_transcript",
            "report_md",
            "report_html",
            "report_docx",
            "insights_json",
        ):
            if url_key not in urls:
                fail(case, f"urls missing {url_key!r}: {urls!r}")
        if urls["react_transcript"] != "/app/job/minimal_job/transcript":
            fail(case, f"react_transcript url wrong: {urls!r}")
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

        print(f"OK: {CHECKS_PASSED} API checks passed")
        return 0
    finally:
        if proc is not None:
            stop_ui(proc)
        shutil.rmtree(scratch_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
