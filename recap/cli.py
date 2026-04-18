"""Recap CLI.

Subcommands:
  run        Ingest a source video and run the full Phase 1 pipeline.
  ingest     Stage 1 only.
  normalize  Stage 2 only.
  transcribe Stage 3 only.
  scenes     Stage 5 only (Phase 2 slice; not invoked by `run`).
  dedupe     pHash + SSIM duplicate marking + OCR novelty (Phase 2 slice; not invoked by `run`).
  window     Transcript-window alignment per candidate frame (Phase 3 slice; not invoked by `run`).
  similarity OpenCLIP frame/text cosine similarity (Phase 3 slice; not invoked by `run`).
  chapters   Transcript-pause chapter proposal (Phase 3 slice; not invoked by `run`).
  rank       Per-chapter ranking fusion (Phase 3 slice; not invoked by `run`).
  shortlist  Keep/reject pre-VLM shortlist (Phase 3 slice; not invoked by `run`).
  verify     Optional VLM verification over the shortlist (Phase 4 slice; not invoked by `run`).
  assemble   Stage 8 Markdown assembly; embeds selected screenshots when present.
  export-html Phase 4 slice: export report.html (not invoked by run).
  export-docx Phase 4 slice: export report.docx (not invoked by run).
  status     Print job.json summary.

All commands operate on a job directory (`--job <path>`). When `run` is
invoked without an existing job, a new one is created under `--jobs-root`
(default: ./jobs). `recap run` deliberately stays Phase 1 only; the
Phase 2 slices are opt-in via `recap scenes --job <path>` (Stage 5) and
`recap dedupe --job <path>` (pHash + SSIM duplicate marking +
Tesseract OCR novelty scoring).

Transcription engine selection is exposed on `recap run` and
`recap transcribe` via `--engine {faster-whisper,deepgram}`. Default
is `faster-whisper`. The Deepgram engine reads `DEEPGRAM_API_KEY`,
`DEEPGRAM_MODEL`, and `DEEPGRAM_BASE_URL` from the environment; the
API key is only required on recompute, so a job whose stored
transcript already matches the requested engine and model will skip
without needing credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import job as job_mod
from .stages import (
    assemble,
    chapters,
    dedupe,
    export_docx,
    export_html,
    ingest,
    normalize,
    rank,
    scenes,
    shortlist,
    similarity,
    transcribe,
    verify,
    window,
)


DEFAULT_JOBS_ROOT = Path("jobs")
DEFAULT_MODEL = "small"
DEFAULT_ENGINE = "faster-whisper"
ENGINE_CHOICES = ("faster-whisper", "deepgram")
DEFAULT_VLM_PROVIDER = "mock"
VLM_PROVIDER_CHOICES = ("mock", "gemini")


def _open_or_create(args) -> job_mod.JobPaths:
    if args.job:
        return job_mod.open_job(Path(args.job))
    jobs_root = Path(args.jobs_root or DEFAULT_JOBS_ROOT)
    return job_mod.create_job(jobs_root)


def cmd_run(args) -> int:
    if args.job:
        paths = job_mod.open_job(Path(args.job))
        if args.source:
            ingest.run(paths, Path(args.source), force=args.force)
        elif paths.find_original() is None:
            print("error: job has no original.* and no --source provided", file=sys.stderr)
            return 2
    else:
        if not args.source:
            print("error: --source is required when creating a new job", file=sys.stderr)
            return 2
        paths = job_mod.create_job(Path(args.jobs_root or DEFAULT_JOBS_ROOT))
        ingest.run(paths, Path(args.source), force=args.force)

    print(f"[job] {paths.root}")
    normalize.run(paths, force=args.force)
    transcribe.run(
        paths, model=args.model, engine=args.engine, force=args.force
    )
    assemble.run(paths, force=args.force)
    print(f"[done] {paths.report_md}")
    return 0


def cmd_ingest(args) -> int:
    if args.job:
        paths = job_mod.open_job(Path(args.job))
    else:
        paths = job_mod.create_job(Path(args.jobs_root or DEFAULT_JOBS_ROOT))
    ingest.run(paths, Path(args.source), force=args.force)
    print(paths.root)
    return 0


def cmd_normalize(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    normalize.run(paths, force=args.force)
    return 0


def cmd_transcribe(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    transcribe.run(
        paths, model=args.model, engine=args.engine, force=args.force
    )
    return 0


def cmd_scenes(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    scenes.run(paths, force=args.force)
    return 0


def cmd_dedupe(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    dedupe.run(paths, force=args.force)
    return 0


def cmd_window(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    window.run(paths, force=args.force)
    return 0


def cmd_similarity(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    similarity.run(paths, force=args.force)
    return 0


def cmd_chapters(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    chapters.run(paths, force=args.force)
    return 0


def cmd_rank(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    rank.run(paths, force=args.force)
    return 0


def cmd_shortlist(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    shortlist.run(paths, force=args.force)
    return 0


def cmd_verify(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    verify.run(paths, provider=args.provider, force=args.force)
    return 0


def cmd_assemble(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    out = assemble.run(paths, force=args.force)
    print(out)
    return 0


def cmd_export_html(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    out = export_html.run(paths, force=args.force)
    print(out)
    return 0


def cmd_export_docx(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    out = export_docx.run(paths, force=args.force)
    print(out)
    return 0


def cmd_status(args) -> int:
    paths = job_mod.open_job(Path(args.job))
    state = job_mod.read_job(paths)
    json.dump(state, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="recap",
        description=(
            "Recap pipeline (Phase 1 core + opt-in Phase 2 slices: "
            "Stage 5 candidate frames, pHash + SSIM duplicate marking "
            "+ Tesseract OCR novelty scoring)"
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    def _common(sp):
        sp.add_argument("--job", help="path to an existing job directory")
        sp.add_argument(
            "--jobs-root",
            help=f"root directory for new jobs (default: {DEFAULT_JOBS_ROOT})",
        )
        sp.add_argument("--force", action="store_true", help="recompute stage outputs")

    sp = sub.add_parser("run", help="run the full Phase 1 pipeline")
    _common(sp)
    sp.add_argument("--source", help="path to the source video (required for new job)")
    sp.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "faster-whisper model name; ignored for --engine deepgram, "
            "which uses DEEPGRAM_MODEL or 'nova-3'"
        ),
    )
    sp.add_argument(
        "--engine",
        default=DEFAULT_ENGINE,
        choices=ENGINE_CHOICES,
        help=(
            f"transcription engine (default: {DEFAULT_ENGINE}). "
            "'deepgram' requires DEEPGRAM_API_KEY in env on recompute."
        ),
    )
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("ingest", help="Stage 1: copy source into a job directory")
    _common(sp)
    sp.add_argument("--source", required=True)
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("normalize", help="Stage 2: metadata + analysis.mp4 + audio.wav")
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_normalize)

    sp = sub.add_parser("transcribe", help="Stage 3: transcript.json + transcript.srt")
    sp.add_argument("--job", required=True)
    sp.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            "faster-whisper model name; ignored for --engine deepgram, "
            "which uses DEEPGRAM_MODEL or 'nova-3'"
        ),
    )
    sp.add_argument(
        "--engine",
        default=DEFAULT_ENGINE,
        choices=ENGINE_CHOICES,
        help=(
            f"transcription engine (default: {DEFAULT_ENGINE}). "
            "'deepgram' requires DEEPGRAM_API_KEY in env on recompute."
        ),
    )
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("scenes", help="Stage 5: scenes.json + candidate_frames/")
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_scenes)

    sp = sub.add_parser(
        "dedupe",
        help="Phase 2 slice: pHash + SSIM duplicate marking + OCR novelty -> frame_scores.json",
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_dedupe)

    sp = sub.add_parser(
        "window",
        help="Phase 3 slice: transcript-window alignment -> frame_windows.json",
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_window)

    sp = sub.add_parser(
        "similarity",
        help="Phase 3 slice: OpenCLIP frame/text cosine -> frame_similarities.json",
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_similarity)

    sp = sub.add_parser(
        "chapters",
        help="Phase 3 slice: transcript-pause chapter proposal -> chapter_candidates.json",
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_chapters)

    sp = sub.add_parser(
        "rank",
        help="Phase 3 slice: per-chapter ranking fusion -> frame_ranks.json",
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_rank)

    sp = sub.add_parser(
        "shortlist",
        help="Phase 3 slice: keep/reject shortlist -> frame_shortlist.json",
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_shortlist)

    sp = sub.add_parser(
        "verify",
        help=(
            "Phase 4 slice: optional VLM verification -> selected_frames.json. "
            "Not invoked by `recap run`."
        ),
    )
    sp.add_argument("--job", required=True)
    sp.add_argument(
        "--provider",
        default=DEFAULT_VLM_PROVIDER,
        choices=VLM_PROVIDER_CHOICES,
        help=(
            f"VLM provider (default: {DEFAULT_VLM_PROVIDER}). "
            "'gemini' requires GEMINI_API_KEY in env on recompute."
        ),
    )
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("assemble", help="Stage 8: basic report.md")
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_assemble)

    sp = sub.add_parser(
        "export-html", help="Phase 4 slice: export report.html"
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_export_html)

    sp = sub.add_parser(
        "export-docx", help="Phase 4 slice: export report.docx"
    )
    sp.add_argument("--job", required=True)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_export_docx)

    sp = sub.add_parser("status", help="print job.json")
    sp.add_argument("--job", required=True)
    sp.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
