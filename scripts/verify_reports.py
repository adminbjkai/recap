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

# Prefix used by the mock insights provider's output on disk. Keep in
# sync with recap/stages/insights.py.
INSIGHTS_SCHEMA_VERSION = 1


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


def run_cmd(
    case: str,
    job: Path,
    cmd: str,
    force: bool = True,
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
    args = [sys.executable, "-m", "recap", cmd, "--job", str(job)]
    if force:
        args.append("--force")
    args.extend(extra)
    return subprocess.run(
        args, cwd=REPO_ROOT, capture_output=True, text=True
    )


def expect_ok(
    case: str,
    job: Path,
    cmd: str,
    extra: tuple[str, ...] = (),
) -> None:
    result = run_cmd(case, job, cmd, extra=extra)
    if result.returncode != 0:
        fail(
            case,
            f"`recap {cmd}` returned {result.returncode}; "
            f"stderr={result.stderr.strip()!r}; job={job}",
        )


def expect_fail_exact(
    case: str,
    job: Path,
    cmd: str,
    extra: tuple[str, ...],
    needles: tuple[str, ...],
) -> None:
    result = run_cmd(case, job, cmd, extra=extra)
    if result.returncode == 0:
        fail(
            case,
            f"`recap {cmd} {' '.join(extra)}` unexpectedly succeeded; "
            f"stdout={result.stdout.strip()!r}; job={job}",
        )
    if not any(n in result.stderr for n in needles):
        fail(
            case,
            f"`recap {cmd}` stderr did not contain any of {needles!r}; "
            f"got {result.stderr.strip()!r}",
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


def _assert_insights_shape(case: str, insights: dict) -> None:
    for key in (
        "version",
        "provider",
        "model",
        "generated_at",
        "overview",
        "chapters",
        "action_items",
        "sources",
    ):
        if key not in insights:
            fail(case, f"insights.json missing top-level key {key!r}")
    if insights["version"] != INSIGHTS_SCHEMA_VERSION:
        fail(
            case,
            f"insights.json version={insights['version']!r}, "
            f"expected {INSIGHTS_SCHEMA_VERSION}",
        )
    if insights["provider"] != "mock":
        fail(
            case,
            f"insights.json provider={insights['provider']!r}, expected 'mock'",
        )
    overview = insights["overview"]
    for key in ("title", "short_summary", "detailed_summary", "quick_bullets"):
        if key not in overview:
            fail(case, f"insights.overview missing {key!r}")
    if not isinstance(overview["quick_bullets"], list):
        fail(case, "insights.overview.quick_bullets is not a list")
    if not isinstance(insights["chapters"], list):
        fail(case, "insights.chapters is not a list")
    if not insights["chapters"]:
        fail(case, "insights.chapters unexpectedly empty for fixture")
    for ch in insights["chapters"]:
        for key in (
            "index",
            "start_seconds",
            "end_seconds",
            "title",
            "summary",
            "bullets",
            "action_items",
            "speaker_focus",
        ):
            if key not in ch:
                fail(case, f"insights chapter missing {key!r}: {ch!r}")


def check_insights_mock_flow() -> None:
    """Happy path: mock insights + assemble/export-html/export-docx must
    include Overview, Quick bullets, and per-chapter enrichment alongside
    the existing Chapters / Transcript sections."""
    case = "insights-mock-flow"
    job = copy_fixture()
    try:
        # First run insights to produce the artifact.
        result = subprocess.run(
            [
                sys.executable, "-m", "recap", "insights",
                "--job", str(job), "--provider", "mock", "--force",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode != 0:
            fail(
                case,
                f"`recap insights` returned {result.returncode}; "
                f"stderr={result.stderr.strip()!r}",
            )

        insights_path = job / "insights.json"
        if not insights_path.is_file():
            fail(case, "insights.json was not produced")
        if (job / "insights.json.tmp").exists():
            fail(case, "leftover insights.json.tmp after successful run")
        insights = json.loads(insights_path.read_text(encoding="utf-8"))
        _assert_insights_shape(case, insights)
        passed()

        # Re-run exports with insights present.
        for cmd in EXPORT_CMDS:
            expect_ok(case, job, cmd)

        md = job / "report.md"
        assert_contains(case, md, "## Overview")
        assert_contains(case, md, "### Quick bullets")
        assert_contains(case, md, "## Chapters")
        assert_contains(
            case,
            md,
            "### Chapter 1 — Welcome to the demo recording",
        )
        # Screenshots from selected_frames are still embedded.
        assert_contains(case, md, "candidate_frames/scene-001.jpg")
        passed()

        html = job / "report.html"
        assert_contains(case, html, '<section class="overview">')
        assert_contains(case, html, "<h2>Overview</h2>")
        assert_contains(case, html, '<ul class="quick-bullets">')
        assert_contains(case, html, "<h2>Chapters</h2>")
        assert_contains(case, html, "Welcome to the demo recording")
        # No unexpected script injection in the rendered HTML.
        assert_not_contains(case, html, "<script>")
        passed()

        docx = job / "report.docx"
        headings = docx_headings(docx)
        for required in ("Overview", "Quick bullets", "Chapters"):
            if required not in headings:
                fail(
                    case,
                    f"report.docx missing heading {required!r}; "
                    f"got {headings}",
                )
        if not any(
            h.startswith("Chapter 1") and "Welcome to the demo" in h
            for h in headings
        ):
            fail(
                case,
                f"report.docx missing insights-titled chapter heading; "
                f"got {headings}",
            )
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_absent_still_exports() -> None:
    """Insights artifact not required: when insights.json is absent,
    assemble / export-html / export-docx must still succeed and must
    NOT emit the Overview section."""
    case = "insights-absent-still-exports"
    job = copy_fixture()
    try:
        if (job / "insights.json").exists():
            fail(case, "fixture unexpectedly ships with insights.json")

        for cmd in EXPORT_CMDS:
            expect_ok(case, job, cmd)

        md = job / "report.md"
        assert_not_contains(case, md, "## Overview")
        assert_not_contains(case, md, "### Quick bullets")
        # Existing chapters-from-selected_frames still rendered.
        assert_contains(case, md, "## Chapters")

        html = job / "report.html"
        assert_not_contains(case, html, '<section class="overview">')
        assert_not_contains(case, html, "<h2>Overview</h2>")

        docx = job / "report.docx"
        headings = docx_headings(docx)
        if "Overview" in headings:
            fail(
                case,
                f"report.docx unexpectedly has Overview heading: {headings}",
            )
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_mock_offline_no_key() -> None:
    """Mock provider must run without any env vars, including no
    GROQ_API_KEY. This is what tests and local-only users rely on."""
    case = "insights-mock-offline-no-key"
    job = copy_fixture()
    try:
        import os
        env = dict(os.environ)
        env.pop("GROQ_API_KEY", None)
        env.pop("GROQ_MODEL", None)
        env.pop("GROQ_BASE_URL", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "recap", "insights",
                "--job", str(job), "--provider", "mock",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            fail(
                case,
                f"mock insights failed without Groq key: "
                f"stderr={result.stderr.strip()!r}",
            )
        if not (job / "insights.json").is_file():
            fail(case, "insights.json missing after offline mock run")
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_groq_missing_key() -> None:
    """Groq provider must fail cleanly with a one-line error when
    GROQ_API_KEY is absent, and must leave no insights.json artifact."""
    case = "insights-groq-missing-key"
    job = copy_fixture()
    try:
        import os
        env = dict(os.environ)
        env.pop("GROQ_API_KEY", None)
        env.pop("GROQ_MODEL", None)
        env.pop("GROQ_BASE_URL", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "recap", "insights",
                "--job", str(job), "--provider", "groq",
            ],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )
        if result.returncode == 0:
            fail(
                case,
                f"`recap insights --provider groq` unexpectedly "
                f"succeeded without GROQ_API_KEY; stdout="
                f"{result.stdout.strip()!r}",
            )
        if "GROQ_API_KEY is not set" not in result.stderr:
            fail(
                case,
                f"stderr did not surface missing GROQ_API_KEY; "
                f"got {result.stderr.strip()!r}",
            )
        if (job / "insights.json").exists():
            fail(
                case,
                "insights.json written despite failed Groq run",
            )
        if (job / "insights.json.tmp").exists():
            fail(case, "leftover insights.json.tmp after failed run")
        # The stage entry must be marked failed so the UI surfaces the
        # error instead of silently claiming everything is fine.
        state = json.loads((job / "job.json").read_text(encoding="utf-8"))
        sc = state.get("stages", {}).get("insights") or {}
        if sc.get("status") != "failed":
            fail(
                case,
                f"stages.insights.status={sc.get('status')!r}, "
                "expected 'failed'",
            )
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_stage_remains_opt_in() -> None:
    """Regression guard: the insights stage must NOT be part of
    ``job.STAGES`` and must NOT be invoked by ``recap run``.

    This is a static check against the source so a future refactor
    that quietly adds 'insights' to the canonical stage tuple or
    wires it into ``cmd_run`` composition fails this verifier even
    on a machine without Groq credentials.
    """
    case = "insights-stage-remains-opt-in"
    sys.path.insert(0, str(REPO_ROOT))
    from recap import job as job_mod  # type: ignore

    if "insights" in job_mod.STAGES:
        fail(
            case,
            f"recap.job.STAGES must not include 'insights'; got "
            f"{job_mod.STAGES!r}",
        )

    cli_text = (REPO_ROOT / "recap" / "cli.py").read_text(encoding="utf-8")
    # Find the cmd_run body and check it does not reference insights.
    start = cli_text.find("def cmd_run(")
    end = cli_text.find("\ndef ", start + 1)
    if start == -1 or end == -1:
        fail(case, "could not locate cmd_run in recap/cli.py")
    body = cli_text[start:end]
    if "insights" in body:
        fail(
            case,
            "cmd_run in recap/cli.py unexpectedly references "
            "insights; insights must stay opt-in",
        )
    passed()


def check_insights_validate_requires_sources() -> None:
    """``validate_insights`` must reject documents that omit the
    top-level ``sources`` block. We wrote the block into every output
    artifact from day one; schema validation has to enforce that
    future writers keep doing so."""
    case = "insights-validate-requires-sources"
    sys.path.insert(0, str(REPO_ROOT))
    from recap.stages.insights import (  # type: ignore
        INSIGHTS_VERSION,
        validate_insights,
    )

    bad = {
        "version": INSIGHTS_VERSION,
        "provider": "mock",
        "model": "mock-v1",
        "generated_at": "2026-04-20T00:00:00Z",
        "overview": {
            "title": "t",
            "short_summary": "s",
            "detailed_summary": "s",
            "quick_bullets": [],
        },
        "chapters": [],
        "action_items": [],
    }
    raised = False
    try:
        validate_insights(bad)
    except RuntimeError as e:
        raised = True
        if "sources" not in str(e):
            fail(
                case,
                f"validate_insights error should mention sources; "
                f"got {e!r}",
            )
    if not raised:
        fail(case, "validate_insights accepted a doc missing 'sources'")

    # And the schema must reject a bogus-shape sources block.
    bad2 = dict(bad)
    bad2["sources"] = {"transcript": 123}
    raised = False
    try:
        validate_insights(bad2)
    except RuntimeError as e:
        raised = True
        if "sources.transcript" not in str(e):
            fail(case, f"expected sources.transcript error; got {e!r}")
    if not raised:
        fail(
            case,
            "validate_insights accepted sources.transcript of wrong type",
        )
    passed()


def _insights_env_without_groq() -> dict:
    import os
    env = dict(os.environ)
    env.pop("GROQ_API_KEY", None)
    env.pop("GROQ_MODEL", None)
    env.pop("GROQ_BASE_URL", None)
    return env


def check_insights_malformed_speaker_names_graceful() -> None:
    """Policy: malformed ``speaker_names.json`` must NOT block insights
    generation. Insights should silently fall back to an empty speaker
    overlay (matches how ``recap ui`` handles a half-written overlay)."""
    case = "insights-malformed-speaker-names-graceful"
    job = copy_fixture()
    try:
        (job / "speaker_names.json").write_text("{not json", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable, "-m", "recap", "insights",
                "--job", str(job), "--provider", "mock", "--force",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=_insights_env_without_groq(),
        )
        if result.returncode != 0:
            fail(
                case,
                "insights should tolerate malformed speaker_names.json; "
                f"stderr={result.stderr.strip()!r}",
            )
        if not (job / "insights.json").is_file():
            fail(case, "insights.json missing after graceful fallback")
        # The sources block should report speaker_names as absent when
        # the overlay could not be parsed.
        doc = json.loads(
            (job / "insights.json").read_text(encoding="utf-8")
        )
        if doc.get("sources", {}).get("speaker_names") is not None:
            fail(
                case,
                f"sources.speaker_names should be null on malformed "
                f"overlay; got {doc.get('sources')!r}",
            )
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_malformed_selected_frames_graceful() -> None:
    """Policy: insights never parses selected_frames.json content, so
    malformed JSON must be tolerated with the artifact treated as
    absent in the sources block."""
    case = "insights-malformed-selected-frames-graceful"
    job = copy_fixture()
    try:
        (job / "selected_frames.json").write_text(
            "{not json", encoding="utf-8"
        )
        result = subprocess.run(
            [
                sys.executable, "-m", "recap", "insights",
                "--job", str(job), "--provider", "mock", "--force",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=_insights_env_without_groq(),
        )
        if result.returncode != 0:
            fail(
                case,
                "insights should tolerate malformed selected_frames.json; "
                f"stderr={result.stderr.strip()!r}",
            )
        if not (job / "insights.json").is_file():
            fail(case, "insights.json missing after graceful fallback")
        doc = json.loads(
            (job / "insights.json").read_text(encoding="utf-8")
        )
        if doc.get("sources", {}).get("selected_frames") is not None:
            fail(
                case,
                f"sources.selected_frames should be null on malformed "
                f"artifact; got {doc.get('sources')!r}",
            )
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_malformed_chapter_candidates_fails_cleanly() -> None:
    """Policy: insights reads chapter_candidates.json content, so
    malformed JSON must FAIL CLEANLY with the canonical
    ``chapter_candidates.json malformed: ...`` prefix rather than
    silently fall back to a whole-transcript chapter. Mirrors
    ``recap assemble`` / ``recap export-*`` behavior."""
    case = "insights-malformed-chapter-candidates-fails-cleanly"
    job = copy_fixture()
    try:
        (job / "chapter_candidates.json").write_text(
            "{not json", encoding="utf-8"
        )
        result = subprocess.run(
            [
                sys.executable, "-m", "recap", "insights",
                "--job", str(job), "--provider", "mock", "--force",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=_insights_env_without_groq(),
        )
        if result.returncode == 0:
            fail(
                case,
                "insights unexpectedly accepted malformed "
                "chapter_candidates.json",
            )
        if "chapter_candidates.json malformed" not in result.stderr:
            fail(
                case,
                "stderr must carry canonical "
                "'chapter_candidates.json malformed' prefix; got "
                f"{result.stderr.strip()!r}",
            )
        if (job / "insights.json").exists():
            fail(
                case,
                "insights.json written despite failed chapter_candidates "
                "parse",
            )
        if (job / "insights.json.tmp").exists():
            fail(case, "leftover insights.json.tmp after failed run")
        # Stage entry must be marked failed.
        state = json.loads((job / "job.json").read_text(encoding="utf-8"))
        sc = state.get("stages", {}).get("insights") or {}
        if sc.get("status") != "failed":
            fail(
                case,
                f"stages.insights.status={sc.get('status')!r}, "
                "expected 'failed'",
            )
        passed()
    finally:
        shutil.rmtree(job.parent, ignore_errors=True)


def check_insights_groq_max_tokens_is_bounded() -> None:
    """Static check: the Groq request body must carry a bounded
    ``max_tokens`` so responses are capped by the provider as well as
    by the client-side ``MAX_RESPONSE_BYTES`` guard."""
    case = "insights-groq-max-tokens-is-bounded"
    src = (REPO_ROOT / "recap" / "stages" / "insights.py").read_text(
        encoding="utf-8"
    )
    if '"max_tokens"' not in src:
        fail(case, "insights.py Groq body is missing a 'max_tokens' cap")
    if "GROQ_DEFAULT_MAX_TOKENS" not in src:
        fail(
            case,
            "insights.py must define a GROQ_DEFAULT_MAX_TOKENS constant",
        )
    passed()


def check_scenes_interrupt_marks_failed() -> None:
    """Regression guard: Ctrl-C during `recap scenes` must leave the
    stage as `failed`, not `running`, and remove partial
    `candidate_frames/`. Simulates the interrupt by monkeypatching
    `recap.stages.scenes._detect_and_extract` to raise
    `KeyboardInterrupt` directly; never invokes PySceneDetect.
    """
    case = "scenes-interrupt-marks-failed"
    # Import inside the function so the rest of the verifier keeps
    # working even on systems where PySceneDetect's transitive deps
    # (cv2) are unavailable. Here we monkeypatch the helper, so the
    # real detector is never called.
    sys.path.insert(0, str(REPO_ROOT))
    from recap import job as job_mod
    from recap.stages import scenes as scenes_mod

    scratch = Path(tempfile.mkdtemp(prefix="recap_scenes_interrupt_"))
    try:
        job_dir = scratch / "job"
        job_dir.mkdir()
        # Minimum plausible on-disk state: analysis.mp4 must exist so
        # scenes.run() doesn't FileNotFoundError before the interrupt.
        (job_dir / "analysis.mp4").write_bytes(b"")
        job_json = {
            "job_id": "scratch",
            "created_at": "2026-04-19T00:00:00Z",
            "updated_at": "2026-04-19T00:00:00Z",
            "status": "pending",
            "source_path": None,
            "original_filename": None,
            "stages": {
                "ingest": {"status": "completed"},
                "normalize": {"status": "completed"},
                "transcribe": {"status": "completed"},
                "assemble": {"status": "completed"},
            },
            "error": None,
        }
        (job_dir / "job.json").write_text(json.dumps(job_json))
        # Seed BOTH a stale scenes.json AND a partial
        # candidate_frames/ from a prior incomplete run. The stage
        # entered recompute because `_outputs_exist` would have
        # returned False (frames listed in scenes.json aren't all on
        # disk). The interrupt-cleanup path must remove both, not
        # just candidate_frames/.
        stale_scenes = {
            "video": "analysis.mp4",
            "detector": "ContentDetector",
            "threshold": 27.0,
            "fallback": False,
            "scene_count": 2,
            "frames_dir": "candidate_frames",
            "scenes": [
                {
                    "index": 1,
                    "start_seconds": 0.0,
                    "end_seconds": 5.0,
                    "start_frame": 0,
                    "end_frame": 150,
                    "midpoint_seconds": 2.5,
                    "frame_file": "scene-001.jpg",
                },
                {
                    "index": 2,
                    "start_seconds": 5.0,
                    "end_seconds": 10.0,
                    "start_frame": 150,
                    "end_frame": 300,
                    "midpoint_seconds": 7.5,
                    "frame_file": "scene-002.jpg",
                },
            ],
        }
        (job_dir / "scenes.json").write_text(json.dumps(stale_scenes))
        (job_dir / "candidate_frames").mkdir()
        (job_dir / "candidate_frames" / "scene-001.jpg").write_bytes(b"x")
        # scene-002.jpg deliberately missing — this is why
        # `_outputs_exist` returns False and the stage recomputes.
        # Also seed a lingering .tmp from an earlier crash.
        (job_dir / "scenes.json.tmp").write_bytes(b"{}")

        paths = job_mod.open_job(job_dir)

        original = scenes_mod._detect_and_extract
        def _raise_interrupt(*_a, **_k):
            raise KeyboardInterrupt()
        scenes_mod._detect_and_extract = _raise_interrupt
        try:
            caught = False
            try:
                scenes_mod.run(paths, force=False)
            except KeyboardInterrupt:
                caught = True
            if not caught:
                fail(case, "scenes.run() did not re-raise KeyboardInterrupt")
        finally:
            scenes_mod._detect_and_extract = original

        state = json.loads((job_dir / "job.json").read_text())
        sc = state.get("stages", {}).get("scenes") or {}
        if sc.get("status") != "failed":
            fail(
                case,
                f"stages.scenes.status={sc.get('status')!r}, expected 'failed'",
            )
        if "KeyboardInterrupt" not in (sc.get("error") or ""):
            fail(
                case,
                f"stages.scenes.error missing KeyboardInterrupt: "
                f"{sc.get('error')!r}",
            )
        if (job_dir / "scenes.json").exists():
            fail(
                case,
                "stale scenes.json was not cleaned up after interrupted "
                "recompute",
            )
        if (job_dir / "candidate_frames").exists():
            fail(case, "candidate_frames/ was not cleaned up after interrupt")
        if (job_dir / "scenes.json.tmp").exists():
            fail(case, "scenes.json.tmp left behind")
        passed()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    if not FIXTURE_ROOT.exists():
        fail("fixture", f"committed fixture not found at {FIXTURE_ROOT}")

    check_selected_path()
    check_absent_selected_path()
    check_bad_start_seconds()
    check_traversal_frame_file()
    check_missing_image()
    check_insights_mock_flow()
    check_insights_absent_still_exports()
    check_insights_mock_offline_no_key()
    check_insights_groq_missing_key()
    check_insights_stage_remains_opt_in()
    check_insights_validate_requires_sources()
    check_insights_malformed_speaker_names_graceful()
    check_insights_malformed_selected_frames_graceful()
    check_insights_malformed_chapter_candidates_fails_cleanly()
    check_insights_groq_max_tokens_is_bounded()
    check_scenes_interrupt_marks_failed()

    print(f"OK: {CHECKS_PASSED} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
