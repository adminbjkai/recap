"""Job model and per-job working directory.

A job is a directory on disk. All state lives in `job.json` inside the
directory alongside the stage artifacts. Readers and writers here are
intentionally dumb: load dict, mutate, write back.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


STAGES = ("ingest", "normalize", "transcribe", "assemble")

# Stage status values used in job.json
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"


@dataclass
class JobPaths:
    root: Path

    @property
    def job_json(self) -> Path:
        return self.root / "job.json"

    @property
    def metadata_json(self) -> Path:
        return self.root / "metadata.json"

    @property
    def analysis_mp4(self) -> Path:
        return self.root / "analysis.mp4"

    @property
    def audio_wav(self) -> Path:
        return self.root / "audio.wav"

    @property
    def transcript_json(self) -> Path:
        return self.root / "transcript.json"

    @property
    def transcript_srt(self) -> Path:
        return self.root / "transcript.srt"

    @property
    def report_md(self) -> Path:
        return self.root / "report.md"

    @property
    def scenes_json(self) -> Path:
        return self.root / "scenes.json"

    @property
    def candidate_frames_dir(self) -> Path:
        return self.root / "candidate_frames"

    @property
    def frame_scores_json(self) -> Path:
        return self.root / "frame_scores.json"

    @property
    def frame_windows_json(self) -> Path:
        return self.root / "frame_windows.json"

    @property
    def frame_similarities_json(self) -> Path:
        return self.root / "frame_similarities.json"

    @property
    def chapter_candidates_json(self) -> Path:
        return self.root / "chapter_candidates.json"

    @property
    def frame_ranks_json(self) -> Path:
        return self.root / "frame_ranks.json"

    @property
    def frame_shortlist_json(self) -> Path:
        return self.root / "frame_shortlist.json"

    @property
    def selected_frames_json(self) -> Path:
        return self.root / "selected_frames.json"

    def original(self, ext: str) -> Path:
        ext = ext.lstrip(".")
        return self.root / f"original.{ext}"

    def find_original(self) -> Path | None:
        for p in self.root.glob("original.*"):
            if p.is_file():
                return p
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_job_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


def create_job(jobs_root: Path, job_id: str | None = None) -> JobPaths:
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_id = job_id or new_job_id()
    root = jobs_root / job_id
    root.mkdir(parents=True, exist_ok=False)
    paths = JobPaths(root=root)
    state = {
        "job_id": job_id,
        "created_at": _now(),
        "updated_at": _now(),
        "status": "pending",
        "source_path": None,
        "original_filename": None,
        "stages": {name: {"status": PENDING} for name in STAGES},
        "error": None,
    }
    write_job(paths, state)
    return paths


def open_job(job_root: Path) -> JobPaths:
    job_root = Path(job_root)
    if not (job_root / "job.json").exists():
        raise FileNotFoundError(f"job.json not found in {job_root}")
    return JobPaths(root=job_root)


def read_job(paths: JobPaths) -> dict[str, Any]:
    with open(paths.job_json, "r") as f:
        return json.load(f)


def write_job(paths: JobPaths, state: dict[str, Any]) -> None:
    state["updated_at"] = _now()
    tmp = paths.job_json.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, paths.job_json)


def update_stage(
    paths: JobPaths,
    stage: str,
    status: str,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate job.json for a single stage transition."""
    state = read_job(paths)
    entry = state["stages"].setdefault(stage, {})
    entry["status"] = status
    if status == RUNNING:
        entry["started_at"] = _now()
        entry.pop("finished_at", None)
        entry.pop("error", None)
    elif status == COMPLETED:
        entry["finished_at"] = _now()
        entry.pop("error", None)
    elif status == FAILED:
        entry["finished_at"] = _now()
        entry["error"] = error or "unknown error"
    if extra:
        entry.update(extra)

    # Roll up top-level status.
    stages = state["stages"]
    if any(s.get("status") == FAILED for s in stages.values()):
        state["status"] = FAILED
        state["error"] = next(
            (s.get("error") for s in stages.values() if s.get("status") == FAILED),
            None,
        )
    elif all(stages.get(n, {}).get("status") == COMPLETED for n in STAGES):
        state["status"] = COMPLETED
        state["error"] = None
    elif any(s.get("status") == RUNNING for s in stages.values()):
        state["status"] = RUNNING
        state["error"] = None
    else:
        state["status"] = "pending"

    write_job(paths, state)
    return state
