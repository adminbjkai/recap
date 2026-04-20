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

        print(f"OK: {CHECKS_PASSED} API checks passed")
        return 0
    finally:
        if proc is not None:
            stop_ui(proc)
        shutil.rmtree(scratch_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
