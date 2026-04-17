"""Stage 3: Transcribe.

Default engine is faster-whisper. Reads `audio.wav` and writes
`transcript.json` and `transcript.srt`.

Current shape of `transcript.json` (faster-whisper; fields required for
downstream consumers marked *required*):

  {
    "engine":               "faster-whisper" | "deepgram",
    "provider":             null | "deepgram",
    "model":                "<engine-specific model id>",
    "language":             "<detected>",
    "language_probability": float | null,
    "duration":             float (*required*),
    "segments": [                                         (*required*)
      {"id": int, "start": float, "end": float, "text": str}
    ]
  }

Optional Deepgram-only fields (absent for faster-whisper):

  {
    "utterances":        [{id, start, end, text, speaker, confidence}],
    "speakers":          [{id, utterance_count, total_seconds,
                          first_seen_seconds, last_seen_seconds}],
    "words":             [{start, end, word, confidence, speaker}],
    "provider_metadata": {provider_version, model, diarize, smart_format,
                          punctuate, detect_language, base_url,
                          request_params}
  }

Downstream consumers (`recap window`, `recap chapters`, `recap assemble`)
read only `segments` and `duration`; they are completely unaware of
`utterances` / `speakers` / `words` / `provider_metadata`. Deepgram is
additive only; faster-whisper's on-disk shape is unchanged.

Engine swap seam: to add a new engine later (Groq, OpenRouter-hosted
Whisper, a different Whisper variant, etc.), add a sibling
`_transcribe_<name>(audio, model_name, ...) -> dict` that returns the
same shape and add a branch on `engine` inside `run()`. Do not add a
registry, plugin system, or config-driven indirection — one inline
`if/elif` is the contract.

Deepgram-specific code-level constants (not CLI flags / config beyond
the env vars below):

  DEEPGRAM_DEFAULT_MODEL      = "nova-3"
  DEEPGRAM_DEFAULT_BASE_URL   = "https://api.deepgram.com"
  DEEPGRAM_TIMEOUT_SECONDS    = 300
  DEEPGRAM_PROVIDER_VERSION   = "deepgram_v1"

Request parameters sent to `POST {base_url}/v1/listen` are pinned:
`smart_format=true`, `punctuate=true`, `utterances=true`,
`diarize=true`, `detect_language=true`. A retune of any of these or of
the defaults must bump `DEEPGRAM_PROVIDER_VERSION`.

Environment variables read via `os.environ` (no `.env` loader):

  DEEPGRAM_API_KEY   Required when a Deepgram recompute is needed. A
                     skip path (stored engine + model already match) does
                     NOT require the key.
  DEEPGRAM_MODEL     Optional override of `DEEPGRAM_DEFAULT_MODEL`.
  DEEPGRAM_BASE_URL  Optional override of `DEEPGRAM_DEFAULT_BASE_URL`.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# ---- Deepgram constants (pinned at the code level) ----------------------

DEEPGRAM_DEFAULT_MODEL = "nova-3"
DEEPGRAM_DEFAULT_BASE_URL = "https://api.deepgram.com"
DEEPGRAM_TIMEOUT_SECONDS = 300
DEEPGRAM_PROVIDER_VERSION = "deepgram_v1"

_DEEPGRAM_BODY_SNIPPET_MAX = 200
_WS_RE = re.compile(r"\s+")


# ---- SRT writer (unchanged contract) ------------------------------------

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


# ---- faster-whisper engine (unchanged output shape) ---------------------

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


# ---- Deepgram engine ----------------------------------------------------

def _snippet(body: bytes | str) -> str:
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    else:
        text = body
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > _DEEPGRAM_BODY_SNIPPET_MAX:
        text = text[:_DEEPGRAM_BODY_SNIPPET_MAX]
    return text


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _round3(x: float) -> float:
    return round(float(x), 3)


def _deepgram_request_params(model: str) -> dict[str, str]:
    return {
        "model": model,
        "smart_format": "true",
        "punctuate": "true",
        "utterances": "true",
        "diarize": "true",
        "detect_language": "true",
    }


def _deepgram_http(
    audio: Path, model: str, base_url: str, api_key: str
) -> dict:
    """POST audio.wav to Deepgram /v1/listen and return the parsed JSON."""
    params = _deepgram_request_params(model)
    query = urllib.parse.urlencode(params)
    url = f"{base_url.rstrip('/')}/v1/listen?{query}"

    try:
        audio_bytes = audio.read_bytes()
    except OSError as e:
        raise RuntimeError(f"deepgram could not read audio.wav: {e}") from e

    req = urllib.request.Request(
        url,
        data=audio_bytes,
        method="POST",
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/wav",
        },
    )

    try:
        with urllib.request.urlopen(
            req, timeout=DEEPGRAM_TIMEOUT_SECONDS
        ) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = e.read() or b""
        except Exception:
            body = b""
        snippet = _snippet(body)
        if status in (401, 403):
            raise RuntimeError(
                f"deepgram authentication failed ({status}): {snippet}"
            ) from e
        raise RuntimeError(
            f"deepgram request failed ({status}): {snippet}"
        ) from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, socket.timeout):
            raise RuntimeError(
                f"deepgram request timed out after {DEEPGRAM_TIMEOUT_SECONDS}s"
            ) from e
        raise RuntimeError(f"deepgram network error: {reason}") from e
    except socket.timeout as e:
        raise RuntimeError(
            f"deepgram request timed out after {DEEPGRAM_TIMEOUT_SECONDS}s"
        ) from e

    if status < 200 or status >= 300:
        raise RuntimeError(
            f"deepgram request failed ({status}): {_snippet(body)}"
        )

    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"deepgram returned invalid JSON: {e}") from e


def _normalize_deepgram_utterance(
    raw: object, assigned_id: int
) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text_raw = raw.get("transcript", "")
    if not isinstance(text_raw, str):
        return None
    text = text_raw.strip()
    if not text:
        return None
    start = raw.get("start", 0.0)
    end = raw.get("end", start)
    if not _is_number(start):
        start = 0.0
    if not _is_number(end):
        end = start
    start_f = _round3(start)
    end_f = _round3(max(float(end), float(start)))
    speaker_raw = raw.get("speaker")
    if isinstance(speaker_raw, bool):
        speaker = None
    elif isinstance(speaker_raw, int):
        speaker = speaker_raw
    elif isinstance(speaker_raw, float):
        speaker = int(speaker_raw) if float(speaker_raw).is_integer() else None
    else:
        speaker = None
    conf_raw = raw.get("confidence")
    confidence = float(conf_raw) if _is_number(conf_raw) else None
    return {
        "id": assigned_id,
        "start": start_f,
        "end": end_f,
        "text": text,
        "speaker": speaker,
        "confidence": confidence,
    }


def _normalize_deepgram_words(raw_list: object) -> list[dict]:
    if not isinstance(raw_list, list):
        return []
    out: list[dict] = []
    for w in raw_list:
        if not isinstance(w, dict):
            continue
        word_text = w.get("punctuated_word")
        if not isinstance(word_text, str) or not word_text.strip():
            word_text = w.get("word")
        if not isinstance(word_text, str) or not word_text.strip():
            continue
        start = w.get("start", 0.0)
        end = w.get("end", start)
        if not _is_number(start):
            start = 0.0
        if not _is_number(end):
            end = start
        conf_raw = w.get("confidence")
        confidence = float(conf_raw) if _is_number(conf_raw) else None
        speaker_raw = w.get("speaker")
        if isinstance(speaker_raw, bool):
            speaker = None
        elif isinstance(speaker_raw, int):
            speaker = speaker_raw
        elif isinstance(speaker_raw, float):
            speaker = int(speaker_raw) if float(speaker_raw).is_integer() else None
        else:
            speaker = None
        out.append(
            {
                "start": _round3(start),
                "end": _round3(max(float(end), float(start))),
                "word": word_text.strip(),
                "confidence": confidence,
                "speaker": speaker,
            }
        )
    return out


def _derive_speakers(utterances: list[dict]) -> list[dict]:
    acc: dict[int, dict] = {}
    for u in utterances:
        sp = u.get("speaker")
        if sp is None:
            continue
        start = float(u["start"])
        end = float(u["end"])
        entry = acc.get(sp)
        if entry is None:
            acc[sp] = {
                "id": sp,
                "utterance_count": 1,
                "total_seconds": max(end - start, 0.0),
                "first_seen_seconds": start,
                "last_seen_seconds": end,
            }
        else:
            entry["utterance_count"] += 1
            entry["total_seconds"] += max(end - start, 0.0)
            entry["first_seen_seconds"] = min(entry["first_seen_seconds"], start)
            entry["last_seen_seconds"] = max(entry["last_seen_seconds"], end)
    out: list[dict] = []
    for sp in sorted(acc.keys()):
        e = acc[sp]
        out.append(
            {
                "id": e["id"],
                "utterance_count": e["utterance_count"],
                "total_seconds": _round3(e["total_seconds"]),
                "first_seen_seconds": _round3(e["first_seen_seconds"]),
                "last_seen_seconds": _round3(e["last_seen_seconds"]),
            }
        )
    return out


def _transcribe_deepgram(
    audio: Path, model_name: str, base_url: str, api_key: str
) -> dict:
    payload = _deepgram_http(audio, model_name, base_url, api_key)

    if not isinstance(payload, dict):
        raise RuntimeError("deepgram returned invalid JSON: not an object")

    results = payload.get("results") if isinstance(payload, dict) else None
    results = results if isinstance(results, dict) else {}

    raw_utterances = results.get("utterances")
    if not isinstance(raw_utterances, list):
        raw_utterances = []

    # Sort incoming utterances by start; then assign 0-based ids.
    tagged: list[tuple[float, dict]] = []
    for u in raw_utterances:
        if not isinstance(u, dict):
            continue
        s = u.get("start", 0.0)
        if not _is_number(s):
            s = 0.0
        tagged.append((float(s), u))
    tagged.sort(key=lambda p: p[0])

    utterances: list[dict] = []
    for i, (_, raw) in enumerate(tagged):
        norm = _normalize_deepgram_utterance(raw, len(utterances))
        if norm is not None:
            utterances.append(norm)

    # segments derived from utterances (strip speaker + confidence)
    segments: list[dict] = []
    if utterances:
        for u in utterances:
            segments.append(
                {
                    "id": u["id"],
                    "start": u["start"],
                    "end": u["end"],
                    "text": u["text"],
                }
            )
    else:
        # Fallback: channel-level transcript as a single segment.
        channels = results.get("channels")
        alt: dict | None = None
        if isinstance(channels, list) and channels:
            ch0 = channels[0]
            if isinstance(ch0, dict):
                alts = ch0.get("alternatives")
                if isinstance(alts, list) and alts and isinstance(alts[0], dict):
                    alt = alts[0]
        fallback_text = ""
        if alt is not None:
            fb = alt.get("transcript")
            if isinstance(fb, str):
                fallback_text = fb.strip()
        if not fallback_text:
            raise RuntimeError("deepgram returned no transcript")
        meta = payload.get("metadata")
        dur_seed = 0.0
        if isinstance(meta, dict):
            md = meta.get("duration")
            if _is_number(md):
                dur_seed = float(md)
        segments.append(
            {
                "id": 0,
                "start": 0.0,
                "end": _round3(dur_seed),
                "text": fallback_text,
            }
        )

    # Language + language_probability from channels[0].alternatives[0]
    channels = results.get("channels")
    language = "en"
    language_probability = None
    if isinstance(channels, list) and channels and isinstance(channels[0], dict):
        alts = channels[0].get("alternatives")
        if isinstance(alts, list) and alts and isinstance(alts[0], dict):
            alt = alts[0]
            lang_raw = alt.get("language")
            if isinstance(lang_raw, str) and lang_raw.strip():
                language = lang_raw.strip()
            else:
                langs = alt.get("languages")
                if (
                    isinstance(langs, list)
                    and langs
                    and isinstance(langs[0], str)
                    and langs[0].strip()
                ):
                    language = langs[0].strip()
            conf_raw = alt.get("confidence")
            if _is_number(conf_raw):
                language_probability = float(conf_raw)
            words_raw = alt.get("words")
        else:
            words_raw = None
    else:
        words_raw = None
    words = _normalize_deepgram_words(words_raw)

    # duration: metadata.duration if present, else max segment end
    duration = None
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        md = meta.get("duration")
        if _is_number(md):
            duration = float(md)
    if duration is None:
        duration = max((float(s["end"]) for s in segments), default=0.0)

    speakers = _derive_speakers(utterances)

    request_params = _deepgram_request_params(model_name)

    return {
        "engine": "deepgram",
        "provider": "deepgram",
        "model": model_name,
        "language": language,
        "language_probability": language_probability,
        "duration": duration,
        "segments": segments,
        "utterances": utterances,
        "speakers": speakers,
        "words": words,
        "provider_metadata": {
            "provider_version": DEEPGRAM_PROVIDER_VERSION,
            "model": model_name,
            "diarize": True,
            "smart_format": True,
            "punctuate": True,
            "detect_language": True,
            "base_url": base_url,
            "request_params": request_params,
        },
    }


# ---- engine dispatch + entry point --------------------------------------

def _resolve_deepgram_model() -> str:
    env_model = os.environ.get("DEEPGRAM_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()
    return DEEPGRAM_DEFAULT_MODEL


def _resolve_deepgram_base_url() -> str:
    env_url = os.environ.get("DEEPGRAM_BASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()
    return DEEPGRAM_DEFAULT_BASE_URL


def run(
    paths: JobPaths,
    model: str = "small",
    engine: str = "faster-whisper",
    force: bool = False,
) -> dict:
    if not paths.audio_wav.exists():
        raise FileNotFoundError("audio.wav not found; run normalize first")

    # Resolve desired engine + model up-front so the skip check can use them.
    if engine == "faster-whisper":
        desired_model = model
        base_url = None
    elif engine == "deepgram":
        desired_model = _resolve_deepgram_model()
        base_url = _resolve_deepgram_base_url()
    else:
        raise RuntimeError(f"unsupported transcription engine: {engine!r}")

    # Skip only when both artifacts exist AND stored engine+model match.
    if (
        not force
        and paths.transcript_json.exists()
        and paths.transcript_srt.exists()
    ):
        try:
            with open(paths.transcript_json) as f:
                stored = json.load(f)
        except (OSError, json.JSONDecodeError):
            stored = None
        if (
            isinstance(stored, dict)
            and stored.get("engine") == engine
            and stored.get("model") == desired_model
        ):
            update_stage(
                paths,
                "transcribe",
                COMPLETED,
                extra={
                    "engine": stored.get("engine"),
                    "model": stored.get("model"),
                    "segments": len(stored.get("segments", [])),
                    "skipped": True,
                },
            )
            return stored

    update_stage(paths, "transcribe", RUNNING)
    json_tmp = paths.transcript_json.with_suffix(".json.tmp")
    srt_tmp = paths.transcript_srt.with_suffix(".srt.tmp")
    try:
        if engine == "faster-whisper":
            data = _transcribe_faster_whisper(paths.audio_wav, desired_model)
        else:  # deepgram
            api_key = os.environ.get("DEEPGRAM_API_KEY")
            if not api_key or not api_key.strip():
                raise RuntimeError("DEEPGRAM_API_KEY is not set")
            data = _transcribe_deepgram(
                paths.audio_wav, desired_model, base_url, api_key.strip()
            )

        with open(json_tmp, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        write_srt(data["segments"], srt_tmp)
        json_tmp.replace(paths.transcript_json)
        srt_tmp.replace(paths.transcript_srt)

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
        # Clean up any partial tmp artifacts so no half-written file remains.
        for p in (json_tmp, srt_tmp):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        update_stage(paths, "transcribe", FAILED, error=f"{type(e).__name__}: {e}")
        raise
