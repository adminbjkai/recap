"""Stage 2: Normalize.

- Run ``ffprobe`` against ``original.*`` and write ``metadata.json``.
- Produce ``analysis.mp4`` (H.264 + AAC), either by stream-copy/remux when
  the source is already compatible, or by full re-encode otherwise.
- Extract ``audio.wav`` as 16kHz mono PCM.

Each sub-step is skipped if its output already exists (unless ``force=True``).

Reliability guarantees:

- Every output is written to ``<target>.tmp`` first and promoted with
  ``os.replace`` only after the FFmpeg subprocess exits cleanly *and*
  a shape-check ``ffprobe`` confirms the output is readable. A corrupt
  or truncated file never lands at the final path.
- FFmpeg runs under a stderr-drain thread so we can detect a stall: if
  neither the output file size nor FFmpeg's stderr changes for
  ``RECAP_NORMALIZE_STALL`` seconds (default 90), the process is killed
  and the stage fails cleanly. A wall-clock ``RECAP_NORMALIZE_TIMEOUT``
  (default 7200s / 2h) caps total runtime.
- During a normalize run the stage entry in ``job.json`` is updated
  roughly every two seconds with ``command_mode``, ``elapsed_seconds``,
  ``output_bytes``, and (when the probe duration is known) ``percent``.
  This bumps ``updated_at`` so the UI shows motion.
- On any failure the stage is marked FAILED with a short message and
  every ``*.tmp`` is unlinked, so a retry starts from a clean slate.

Env overrides:

- ``RECAP_NORMALIZE_TIMEOUT`` - hard wall clock, seconds.
- ``RECAP_NORMALIZE_STALL`` - stall window, seconds.
- ``RECAP_NORMALIZE_NO_FASTPATH=1`` - force full re-encode even when the
  input looks compatible.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# Defaults chosen to be generous: a 56 min 4k screen recording can easily
# take 20-30 minutes of full re-encode on a laptop.
DEFAULT_TIMEOUT_S = 2 * 60 * 60  # 2 hours
DEFAULT_STALL_S = 90              # 90s of no growth + no stderr => stalled
HEARTBEAT_INTERVAL_S = 2.0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return val if val > 0 else default


def _timeout_s() -> int:
    return _env_int("RECAP_NORMALIZE_TIMEOUT", DEFAULT_TIMEOUT_S)


def _stall_s() -> int:
    return _env_int("RECAP_NORMALIZE_STALL", DEFAULT_STALL_S)


def _no_fastpath() -> bool:
    return os.environ.get("RECAP_NORMALIZE_NO_FASTPATH", "") not in ("", "0")


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(
            f"{name} not found on PATH. Install FFmpeg and make sure both "
            "`ffmpeg` and `ffprobe` are available (e.g. `brew install ffmpeg` "
            "on macOS or `apt-get install ffmpeg` on Debian/Ubuntu)."
        )
    return path


def _tmp_for(out: Path) -> Path:
    return out.with_name(out.name + ".tmp")


def _cleanup_tmp(*paths: Path) -> None:
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Mode decision (pure - unit-testable without ffmpeg).
# ---------------------------------------------------------------------------

def _decide_normalize_mode(probe: dict[str, Any]) -> str:
    """Return ``"remux"`` when the source is already analysis-ready, else
    ``"reencode"``.

    "Analysis-ready" means: MP4 container, H.264 video at yuv420p with a
    non-zero width, and (if audio is present at all) AAC. Anything else -
    unknown codec, wrong pixel format, HEVC, VP9, Opus, MKV, etc. - falls
    back to the conservative full re-encode.

    Respects ``RECAP_NORMALIZE_NO_FASTPATH=1`` as a hard escape.
    """
    if _no_fastpath():
        return "reencode"
    if not isinstance(probe, dict):
        return "reencode"

    fmt = probe.get("format") or {}
    format_name = str(fmt.get("format_name") or "").lower()
    # ffprobe reports mp4 as "mov,mp4,m4a,3gp,3g2,mj2" - accept any that
    # explicitly lists mp4 or mov.
    if "mp4" not in format_name and "mov" not in format_name:
        return "reencode"

    streams = probe.get("streams") or []
    if not isinstance(streams, list):
        return "reencode"

    video_ok = False
    audio_ok = True  # audio absent is fine - ffmpeg will just skip it
    saw_audio = False
    for s in streams:
        if not isinstance(s, dict):
            return "reencode"
        kind = str(s.get("codec_type") or "").lower()
        codec = str(s.get("codec_name") or "").lower()
        if kind == "video":
            pix_fmt = str(s.get("pix_fmt") or "").lower()
            width = s.get("width") or 0
            try:
                width_i = int(width)
            except (TypeError, ValueError):
                width_i = 0
            if codec == "h264" and pix_fmt == "yuv420p" and width_i > 0:
                video_ok = True
            else:
                return "reencode"
        elif kind == "audio":
            saw_audio = True
            if codec != "aac":
                audio_ok = False

    if video_ok and (not saw_audio or audio_ok):
        return "remux"
    return "reencode"


# ---------------------------------------------------------------------------
# ffprobe wrappers.
# ---------------------------------------------------------------------------

def _ffprobe_json(target: Path) -> dict[str, Any]:
    ffprobe = _require_tool("ffprobe")
    cp = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(cp.stdout)


def _probe_duration_seconds(probe: dict[str, Any]) -> float | None:
    fmt = probe.get("format") or {}
    raw = fmt.get("duration")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _write_json_atomic(data: dict[str, Any], out: Path) -> None:
    tmp = _tmp_for(out)
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, out)
    finally:
        _cleanup_tmp(tmp)


# ---------------------------------------------------------------------------
# Streaming ffmpeg runner with stall guard.
# ---------------------------------------------------------------------------

class NormalizeError(RuntimeError):
    """Raised when FFmpeg fails, stalls, times out, or produces bad output."""


def _run_ffmpeg_streaming(
    cmd: list[str],
    out_tmp: Path,
    timeout_s: int,
    stall_s: int,
    heartbeat: Callable[[float, int], None] | None = None,
) -> None:
    """Run FFmpeg writing to ``out_tmp``; kill on stall or wall-clock timeout.

    ``heartbeat(elapsed_seconds, output_bytes)`` is invoked every
    ``HEARTBEAT_INTERVAL_S`` seconds while the process is alive.

    Raises ``NormalizeError`` on nonzero exit, stall, or timeout.
    """
    # Use line-buffered stderr so the drain thread sees activity whenever
    # ffmpeg prints a progress line. stdout is unused (our commands don't
    # emit to stdout) - merge it into stderr to keep one pipe.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_tail: list[str] = []
    stderr_tail_limit = 40
    last_stderr_activity = time.monotonic()
    drain_lock = threading.Lock()

    def _drain_stderr() -> None:
        nonlocal last_stderr_activity
        assert proc.stderr is not None
        try:
            for line in proc.stderr:
                now = time.monotonic()
                with drain_lock:
                    last_stderr_activity = now
                    stderr_tail.append(line.rstrip("\n"))
                    if len(stderr_tail) > stderr_tail_limit:
                        del stderr_tail[: len(stderr_tail) - stderr_tail_limit]
        except Exception:
            # Pipe closed mid-read; main loop will observe the exit.
            pass

    drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
    drain_thread.start()

    started = time.monotonic()
    last_size = -1
    last_size_change = started
    last_heartbeat = 0.0

    def _kill() -> None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    try:
        while True:
            rc = proc.poll()
            now = time.monotonic()
            elapsed = now - started

            try:
                size = out_tmp.stat().st_size if out_tmp.exists() else 0
            except OSError:
                size = 0
            if size != last_size:
                last_size = size
                last_size_change = now

            if heartbeat and (now - last_heartbeat) >= HEARTBEAT_INTERVAL_S:
                try:
                    heartbeat(elapsed, size)
                except Exception:
                    # Heartbeat errors must never kill the ffmpeg run.
                    pass
                last_heartbeat = now

            if rc is not None:
                break

            if elapsed > timeout_s:
                _kill()
                raise NormalizeError(
                    f"ffmpeg wall-clock timeout after {int(elapsed)}s "
                    f"(RECAP_NORMALIZE_TIMEOUT={timeout_s})"
                )

            with drain_lock:
                last_stderr = last_stderr_activity
            since_size = now - last_size_change
            since_stderr = now - last_stderr
            if since_size > stall_s and since_stderr > stall_s:
                _kill()
                raise NormalizeError(
                    f"ffmpeg stalled: no output growth or stderr activity "
                    f"for {int(min(since_size, since_stderr))}s "
                    f"(RECAP_NORMALIZE_STALL={stall_s})"
                )

            time.sleep(0.5)

        # Process exited; drain thread should finish quickly.
        drain_thread.join(timeout=2.0)
        if proc.returncode != 0:
            with drain_lock:
                tail = [ln for ln in stderr_tail if ln.strip()]
            msg = tail[-1] if tail else f"ffmpeg exit {proc.returncode}"
            raise NormalizeError(f"ffmpeg: {msg}")
    finally:
        if proc.poll() is None:
            _kill()


# ---------------------------------------------------------------------------
# Output validation.
# ---------------------------------------------------------------------------

def _validate_analysis(tmp: Path) -> None:
    """Confirm the tmp analysis file has a readable video stream."""
    try:
        probe = _ffprobe_json(tmp)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip().splitlines()
        tail = msg[-1] if msg else "ffprobe failed"
        raise NormalizeError(f"analysis validation failed: {tail}")
    except Exception as e:  # noqa: BLE001
        raise NormalizeError(f"analysis validation failed: {e}")
    streams = probe.get("streams") or []
    for s in streams:
        if not isinstance(s, dict):
            continue
        if str(s.get("codec_type") or "").lower() == "video":
            codec = str(s.get("codec_name") or "").strip()
            try:
                width = int(s.get("width") or 0)
            except (TypeError, ValueError):
                width = 0
            if codec and width > 0:
                return
    raise NormalizeError("analysis validation failed: no usable video stream")


def _validate_audio_wav(tmp: Path) -> None:
    try:
        probe = _ffprobe_json(tmp)
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip().splitlines()
        tail = msg[-1] if msg else "ffprobe failed"
        raise NormalizeError(f"audio validation failed: {tail}")
    except Exception as e:  # noqa: BLE001
        raise NormalizeError(f"audio validation failed: {e}")
    streams = probe.get("streams") or []
    for s in streams:
        if not isinstance(s, dict):
            continue
        if str(s.get("codec_type") or "").lower() == "audio":
            codec = str(s.get("codec_name") or "").lower()
            if codec == "pcm_s16le":
                return
    raise NormalizeError("audio validation failed: no pcm_s16le stream")


# ---------------------------------------------------------------------------
# High-level producers.
# ---------------------------------------------------------------------------

def _produce_metadata(original: Path, out: Path) -> dict[str, Any]:
    data = _ffprobe_json(original)
    _write_json_atomic(data, out)
    return data


def _produce_analysis(
    original: Path,
    out: Path,
    mode: str,
    paths: JobPaths,
    probe: dict[str, Any],
) -> None:
    ffmpeg = _require_tool("ffmpeg")
    tmp = _tmp_for(out)
    _cleanup_tmp(tmp)

    # NOTE: tmp name ends in ``.tmp`` so FFmpeg can't infer the container
    # from the extension. We always pass ``-f mp4`` here to force MP4.
    if mode == "remux":
        cmd = [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "warning",
            "-i", str(original),
            "-c", "copy",
            "-map", "0",
            "-movflags", "+faststart",
            "-f", "mp4",
            str(tmp),
        ]
    else:
        cmd = [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "warning",
            "-i", str(original),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-f", "mp4",
            str(tmp),
        ]

    duration = _probe_duration_seconds(probe)

    def _beat(elapsed: float, size: int) -> None:
        extra: dict[str, Any] = {
            "command_mode": mode,
            "elapsed_seconds": round(elapsed, 1),
            "output_bytes": int(size),
            "phase": "analysis",
        }
        if duration:
            extra["percent"] = max(
                0.0, min(100.0, round(100.0 * elapsed / duration, 1))
            )
            extra["input_duration_seconds"] = round(duration, 3)
        update_stage(paths, "normalize", RUNNING, extra=extra)

    try:
        _run_ffmpeg_streaming(
            cmd,
            out_tmp=tmp,
            timeout_s=_timeout_s(),
            stall_s=_stall_s(),
            heartbeat=_beat,
        )
        _validate_analysis(tmp)
        os.replace(tmp, out)
    finally:
        _cleanup_tmp(tmp)


def _produce_audio(
    original: Path,
    out: Path,
    paths: JobPaths,
    probe: dict[str, Any],
) -> None:
    ffmpeg = _require_tool("ffmpeg")
    tmp = _tmp_for(out)
    _cleanup_tmp(tmp)

    cmd = [
        ffmpeg,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel", "warning",
        "-i", str(original),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-sample_fmt", "s16",
        "-c:a", "pcm_s16le",
        # tmp name ends in ``.tmp`` — force the container explicitly.
        "-f", "wav",
        str(tmp),
    ]

    duration = _probe_duration_seconds(probe)

    def _beat(elapsed: float, size: int) -> None:
        extra: dict[str, Any] = {
            "elapsed_seconds": round(elapsed, 1),
            "output_bytes": int(size),
            "phase": "audio",
        }
        if duration:
            extra["percent"] = max(
                0.0, min(100.0, round(100.0 * elapsed / duration, 1))
            )
            extra["input_duration_seconds"] = round(duration, 3)
        update_stage(paths, "normalize", RUNNING, extra=extra)

    try:
        _run_ffmpeg_streaming(
            cmd,
            out_tmp=tmp,
            timeout_s=_timeout_s(),
            stall_s=_stall_s(),
            heartbeat=_beat,
        )
        _validate_audio_wav(tmp)
        os.replace(tmp, out)
    finally:
        _cleanup_tmp(tmp)


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

def run(paths: JobPaths, force: bool = False) -> dict:
    original = paths.find_original()
    if original is None:
        raise FileNotFoundError("no original.* found; run ingest first")

    update_stage(paths, "normalize", RUNNING, extra={"phase": "probe"})
    analysis_tmp = _tmp_for(paths.analysis_mp4)
    audio_tmp = _tmp_for(paths.audio_wav)
    meta_tmp = _tmp_for(paths.metadata_json)

    try:
        if force or not paths.metadata_json.exists():
            probe = _produce_metadata(original, paths.metadata_json)
        else:
            try:
                with open(paths.metadata_json, "r") as f:
                    probe = json.load(f)
            except (OSError, json.JSONDecodeError):
                probe = _produce_metadata(original, paths.metadata_json)

        mode = _decide_normalize_mode(probe)

        if force or not paths.analysis_mp4.exists():
            update_stage(
                paths,
                "normalize",
                RUNNING,
                extra={"command_mode": mode, "phase": "analysis"},
            )
            _produce_analysis(original, paths.analysis_mp4, mode, paths, probe)

        if force or not paths.audio_wav.exists():
            update_stage(
                paths,
                "normalize",
                RUNNING,
                extra={"phase": "audio"},
            )
            _produce_audio(original, paths.audio_wav, paths, probe)

        artifacts = {
            "metadata": paths.metadata_json.name,
            "analysis_video": paths.analysis_mp4.name,
            "audio": paths.audio_wav.name,
            "command_mode": mode,
        }
        update_stage(
            paths,
            "normalize",
            COMPLETED,
            extra={"artifacts": artifacts, "command_mode": mode},
        )
        return artifacts
    except NormalizeError as e:
        _cleanup_tmp(analysis_tmp, audio_tmp, meta_tmp)
        update_stage(paths, "normalize", FAILED, error=str(e))
        raise
    except subprocess.CalledProcessError as e:
        _cleanup_tmp(analysis_tmp, audio_tmp, meta_tmp)
        tail = (e.stderr or e.stdout or str(e)).strip().splitlines()
        msg = tail[-1] if tail else str(e)
        update_stage(paths, "normalize", FAILED, error=f"ffmpeg/ffprobe: {msg}")
        raise
    except Exception as e:
        _cleanup_tmp(analysis_tmp, audio_tmp, meta_tmp)
        update_stage(paths, "normalize", FAILED, error=f"{type(e).__name__}: {e}")
        raise
