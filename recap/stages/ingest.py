"""Stage 1: Ingest.

Copy the source file into the job directory as `original.<ext>` and record
the source path on the job state. This stage does no media work.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..job import (
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    JobPaths,
    read_job,
    update_stage,
    write_job,
)


# Downstream artifacts that must be invalidated when the source is replaced.
_DOWNSTREAM_ARTIFACTS = (
    "metadata_json",
    "analysis_mp4",
    "audio_wav",
    "transcript_json",
    "transcript_srt",
    "scenes_json",
    "frame_scores_json",
    "frame_windows_json",
    "frame_similarities_json",
    "report_md",
)
_DOWNSTREAM_STAGES = (
    "normalize",
    "transcribe",
    "scenes",
    "dedupe",
    "window",
    "similarity",
    "assemble",
)


def _invalidate_downstream(paths: JobPaths) -> None:
    for attr in _DOWNSTREAM_ARTIFACTS:
        p: Path = getattr(paths, attr)
        if p.exists():
            p.unlink()
    if paths.candidate_frames_dir.is_dir():
        shutil.rmtree(paths.candidate_frames_dir)
    state = read_job(paths)
    for name in _DOWNSTREAM_STAGES:
        state["stages"][name] = {"status": PENDING}
    state["status"] = "pending"
    state["error"] = None
    write_job(paths, state)


def run(paths: JobPaths, source: Path, force: bool = False) -> Path:
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source video not found: {source}")

    state = read_job(paths)
    existing = paths.find_original()
    recorded_source = state.get("source_path")
    source_str = str(source)
    source_changed = bool(existing) and recorded_source not in (None, source_str)

    if existing and source_changed and not force:
        raise RuntimeError(
            "refusing to re-ingest: job already has "
            f"{existing.name} from {recorded_source!r}, but --source is "
            f"{source_str!r}. Re-run with --force to replace the source "
            "(this will also discard downstream analysis, audio, transcript, "
            "scenes, candidate frames, frame scores, frame windows, frame "
            "similarities, and report)."
        )

    if existing and not force:
        update_stage(paths, "ingest", COMPLETED, extra={"original": existing.name})
        return existing

    update_stage(paths, "ingest", RUNNING)
    try:
        ext = source.suffix.lstrip(".") or "bin"
        target = paths.original(ext)

        if existing and source_changed:
            _invalidate_downstream(paths)

        # Remove any stale original.* before copying (handles ext change).
        for old in paths.root.glob("original.*"):
            old.unlink()
        shutil.copy2(source, target)

        state = read_job(paths)
        state["source_path"] = source_str
        state["original_filename"] = source.name
        write_job(paths, state)

        update_stage(
            paths,
            "ingest",
            COMPLETED,
            extra={"original": target.name, "size_bytes": target.stat().st_size},
        )
        return target
    except Exception as e:
        update_stage(paths, "ingest", FAILED, error=f"{type(e).__name__}: {e}")
        raise
