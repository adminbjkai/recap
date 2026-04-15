"""Stage 3: Transcribe.

Default engine is faster-whisper. Reads `audio.wav` and writes
`transcript.json` and `transcript.srt`.

`transcript.json` shape:
{
  "engine": "<name>",          # e.g. "faster-whisper"
  "provider": <str or null>,   # null for local engines; e.g. "deepgram", "groq"
  "model": "<name>",
  "language": "<detected>",
  "duration": <seconds>,
  "segments": [
    {"id": int, "start": float, "end": float, "text": str}
  ]
}

Engine swap seam: to add a new engine later (Deepgram, Groq, OpenRouter-hosted
Whisper, a different Whisper variant, etc.), add a sibling
`_transcribe_<name>(audio, model_name) -> dict` that returns the same shape,
then branch on `engine` inside `run()`. Do not add a registry, plugin system,
or config-driven indirection — one inline `if/elif` is the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


def _format_srt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], out: Path) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start = _format_srt_ts(float(seg["start"]))
        end = _format_srt_ts(float(seg["end"]))
        text = (seg.get("text") or "").strip()
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def _transcribe_faster_whisper(audio: Path, model_name: str) -> dict:
    from faster_whisper import WhisperModel  # lazy import

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(str(audio), vad_filter=False)

    segments: list[dict] = []
    for i, s in enumerate(segments_iter):
        segments.append(
            {
                "id": i,
                "start": float(s.start),
                "end": float(s.end),
                "text": s.text.strip() if s.text else "",
            }
        )

    return {
        "engine": "faster-whisper",
        "provider": None,
        "model": model_name,
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "segments": segments,
    }


def run(paths: JobPaths, model: str = "small", force: bool = False) -> dict:
    if not paths.audio_wav.exists():
        raise FileNotFoundError("audio.wav not found; run normalize first")

    if (
        not force
        and paths.transcript_json.exists()
        and paths.transcript_srt.exists()
    ):
        with open(paths.transcript_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "transcribe",
            COMPLETED,
            extra={
                "engine": data.get("engine"),
                "model": data.get("model"),
                "segments": len(data.get("segments", [])),
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "transcribe", RUNNING)
    try:
        data = _transcribe_faster_whisper(paths.audio_wav, model)
        with open(paths.transcript_json, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        write_srt(data["segments"], paths.transcript_srt)

        update_stage(
            paths,
            "transcribe",
            COMPLETED,
            extra={
                "engine": data["engine"],
                "model": data["model"],
                "language": data.get("language"),
                "segments": len(data["segments"]),
            },
        )
        return data
    except Exception as e:
        update_stage(paths, "transcribe", FAILED, error=f"{type(e).__name__}: {e}")
        raise
