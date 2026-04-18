#!/usr/bin/env python3
"""Offline golden-path validation for Recap's Markdown / HTML / DOCX exports.

Runs `recap assemble`, `recap export-html`, and `recap export-docx`
against a tiny committed fixture under `scripts/fixtures/minimal_job/`
and asserts the expected structure for both the selected-path and the
absent-selected path, plus the shared error envelope for a small set of
malformed artifacts.

No network, no model downloads, no pytest. Uses stdlib plus `python-docx`
(already a project dependency).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document


REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "scripts" / "fixtures" / "minimal_job"
EXPORT_CMDS = ("assemble", "export-html", "export-docx")
CHECKS_PASSED = 0


def fail(case: str, reason: str) -> None:
    print(f"FAIL: {case}: {reason}")
    sys.exit(1)


def passed() -> None:
    global CHECKS_PASSED
    CHECKS_PASSED += 1


def copy_fixture() -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="recap_verify_"))
    job = scratch / "minimal_job"
    shutil.copytree(FIXTURE_ROOT, job)
    return job


def run_cmd(case: str, job: Path, cmd: str, force: bool = True) -> subprocess.CompletedProcess:
    args = [sys.executable, "-m", "recap", cmd, "--job", str(job)]
    if force:
        args.append("--force")
    return subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, text=True
    )


def expect_ok(case: str, job: Path, cmd: str) -> None:
    result = run_cmd(case, job, cmd)
    if result.returncode != 0:
        fail(
            case,
            f"`recap {cmd}` returned {result.returncode}; "
            f"stderr={result.stderr.strip()!r}; job={job}",
        )


def expect_fail_with(
    case: str, job: Path, cmd: str, needles: tuple[str, ...]
) -> None:
    result = run_cmd(case, job, cmd)
    if result.returncode != 2:
        fail(
            case,
            f"`recap {cmd}` returned {result.returncode}, expected 2; "
            f"stderr={result.stderr.strip()!r}; job={job}",
        )
    if not any(n in result.stderr for n in needles):
        fail(
            case,
            f"`recap {cmd}` stderr did not contain any of {needles!r}; "
            f"got {result.stderr.strip()!r}",
        )
    for tmp_name in ("report.md.tmp", "report.html.tmp", "report.docx.tmp"):
        if (job / tmp_name).exists():
            fail(case, f"leftover tmp file: {tmp_name}")


def assert_contains(case: str, path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle not in text:
        fail(case, f"{path.name} missing {needle!r}")


def assert_not_contains(case: str, path: Path, needle: str) -> None:
    text = path.read_text(encoding="utf-8")
    if needle in text:
        fail(case, f"{path.name} unexpectedly contains {needle!r}")


def docx_headings(path: Path) -> list[str]:
    doc = Document(str(path))
    return [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]


def docx_inline_shapes(path: Path) -> int:
    return len(Document(str(path)).inline_shapes)


def check_selected_path() -> None:
    case = "selected-path"
    job = copy_fixture()
    try:
        for cmd in EXPORT_CMDS:
            expect_ok(case, job, cmd)

        md = job / "report.md"
        assert_contains(case, md, "## Chapters")
        assert_contains(case, md, "candidate_frames/scene-001.jpg")
        assert_contains(case, md, "candidate_frames/scene-003.jpg")
        assert_not_contains(case, md, "candidate_frames/scene-002.jpg")
        assert_contains(case, md, "## Transcript")
        passed()

        html = job / "report.html"
        assert_contains(case, html, "<h2>Chapters</h2>")
        assert_contains(case, html, 'src="candidate_frames/scene-001.jpg"')
        assert_contains(case, html, 'src="candidate_frames/scene-003.jpg"')
        assert_not_contains(case, html, "scene-002.jpg")
        assert_contains(case, html, "<h2>Transcript</h2>")
        assert_contains(case, html, "<h3>Segments</h3>")
        assert_not_contains(case, html, "<script>")
        passed()

        docx = job / "report.docx"
        headings = docx_headings(docx)
        for required in ("Recap: minimal.mp4", "Media", "Chapters",
                         "Transcript", "Segments"):
            if required not in headings:
                fail(case, f"report.docx missing heading {required!r}; "
                     f"got {headings}")
        shapes = docx_inline_shapes(docx)
        if shapes != 2:
            fail(case, f"report.docx inline_shapes={shapes}, expected 2")
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_absent_selected_path() -> None:
    case = "absent-selected"
    job = copy_fixture()
    try:
        (job / "selected_frames.json").unlink()
        for cmd in EXPORT_CMDS:
            expect_ok(case, job, cmd)

        md = job / "report.md"
        assert_not_contains(case, md, "## Chapters")
        assert_not_contains(case, md, "candidate_frames/")
        passed()

        html = job / "report.html"
        assert_not_contains(case, html, "<h2>Chapters</h2>")
        assert_not_contains(case, html, "<img")
        passed()

        docx = job / "report.docx"
        headings = docx_headings(docx)
        if "Chapters" in headings:
            fail(case, f"report.docx unexpectedly has Chapters heading: {headings}")
        shapes = docx_inline_shapes(docx)
        if shapes != 0:
            fail(case, f"report.docx inline_shapes={shapes}, expected 0")
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def _mutate_selected(job: Path, mutator) -> None:
    p = job / "selected_frames.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    mutator(data)
    p.write_text(json.dumps(data), encoding="utf-8")


def check_bad_start_seconds() -> None:
    case = "bad-start-seconds"
    needles = (
        "error: selected_frames.json malformed: "
        "chapter 1 'start_seconds' must be numeric",
    )
    for cmd in EXPORT_CMDS:
        job = copy_fixture()
        try:
            _mutate_selected(
                job,
                lambda d: d["chapters"][0].__setitem__("start_seconds", "bad"),
            )
            for out in ("report.md", "report.html", "report.docx"):
                (job / out).unlink(missing_ok=True)
            expect_fail_with(case, job, cmd, needles)
            passed()
        finally:
            shutil.rmtree(job.parent, ignore_errors=True)


def check_traversal_frame_file() -> None:
    case = "traversal-frame-file"
    # All three exporters must reject traversal via the plain-filename
    # safety check, not the existence check. This is a validator-contract
    # requirement, not an implementation detail.
    needles = ("plain filename inside candidate_frames/",)
    for cmd in EXPORT_CMDS:
        job = copy_fixture()
        try:
            def mut(d):
                ch = d["chapters"][0]
                ch["hero"]["frame_file"] = "../report.md"
                ch["frames"][0]["frame_file"] = "../report.md"
            _mutate_selected(job, mut)
            for out in ("report.md", "report.html", "report.docx"):
                (job / out).unlink(missing_ok=True)
            expect_fail_with(case, job, cmd, needles)
            passed()
        finally:
            shutil.rmtree(job.parent, ignore_errors=True)


def check_missing_image() -> None:
    case = "missing-image"
    needles = ("missing candidate frame: candidate_frames/scene-001.jpg",)
    for cmd in EXPORT_CMDS:
        job = copy_fixture()
        try:
            (job / "candidate_frames" / "scene-001.jpg").unlink()
            for out in ("report.md", "report.html", "report.docx"):
                (job / out).unlink(missing_ok=True)
            expect_fail_with(case, job, cmd, needles)
            passed()
        finally:
            shutil.rmtree(job.parent, ignore_errors=True)


def main() -> int:
    if not FIXTURE_ROOT.exists():
        fail("fixture", f"committed fixture not found at {FIXTURE_ROOT}")

    check_selected_path()
    check_absent_selected_path()
    check_bad_start_seconds()
    check_traversal_frame_file()
    check_missing_image()

    print(f"OK: {CHECKS_PASSED} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
