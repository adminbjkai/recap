"""Stage 2: Normalize.

- Run `ffprobe` against `original.*` and write `metadata.json`.
- Transcode the source to `analysis.mp4` (H.264 + AAC).
- Extract `audio.wav` as 16kHz mono PCM.

Each sub-step is skipped if its output already exists (unless `force=True`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} not found on PATH. Install FFmpeg and make sure both "
            "`ffmpeg` and `ffprobe` are available (e.g. `brew install ffmpeg` "
            "on macOS or `apt-get install ffmpeg` on Debian/Ubuntu)."
        )
    return path


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _ffprobe(original: Path, out: Path) -> dict:
    ffprobe = _require_tool("ffprobe")
    cp = _run([
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(original),
    ])
    data = json.loads(cp.stdout)
    with open(out, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return data


def _transcode(original: Path, out: Path) -> None:
    ffmpeg = _require_tool("ffmpeg")
    _run([
        ffmpeg,
        "-y",
        "-i", str(original),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ])


def _extract_audio(original: Path, out: Path) -> None:
    ffmpeg = _require_tool("ffmpeg")
    _run([
        ffmpeg,
        "-y",
        "-i", str(original),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-sample_fmt", "s16",
        "-c:a", "pcm_s16le",
        str(out),
    ])


def run(paths: JobPaths, force: bool = False) -> dict:
    original = paths.find_original()
    if original is None:
        raise FileNotFoundError("no original.* found; run ingest first")

    update_stage(paths, "normalize", RUNNING)
    try:
        if force or not paths.metadata_json.exists():
            _ffprobe(original, paths.metadata_json)
        if force or not paths.analysis_mp4.exists():
            _transcode(original, paths.analysis_mp4)
        if force or not paths.audio_wav.exists():
            _extract_audio(original, paths.audio_wav)

        artifacts = {
            "metadata": paths.metadata_json.name,
            "analysis_video": paths.analysis_mp4.name,
            "audio": paths.audio_wav.name,
        }
        update_stage(paths, "normalize", COMPLETED, extra={"artifacts": artifacts})
        return artifacts
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip().splitlines()[-1] if (e.stderr or e.stdout) else str(e)
        update_stage(paths, "normalize", FAILED, error=f"ffmpeg/ffprobe: {msg}")
        raise
    except Exception as e:
        update_stage(paths, "normalize", FAILED, error=f"{type(e).__name__}: {e}")
        raise
