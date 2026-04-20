"""Opt-in slice: structured insights for reports.

Reads existing artifacts (`transcript.json`, optional
`chapter_candidates.json`, optional `speaker_names.json`, optional
`selected_frames.json`) and writes a single `insights.json` artifact
with overview, per-chapter summaries, and a flat list of action items.

Two providers are supported:

- ``mock`` — deterministic, offline; derived from the transcript and
  chapter text. Used by tests and as the default for local work that
  has no LLM credentials. No network calls.
- ``groq`` — calls the Groq chat-completions API (strict JSON mode)
  using the ``GROQ_API_KEY`` / ``GROQ_MODEL`` env vars. Implemented
  with stdlib ``http.client`` so the slice adds no Python
  dependencies. Fails cleanly with a one-line error when
  ``GROQ_API_KEY`` is missing.

This stage is **not** part of :data:`recap.job.STAGES` and is **not**
invoked by ``recap run``. It mutates only ``insights.json`` and the
``stages.insights`` entry inside ``job.json``. It never touches
``transcript.json`` or any other upstream artifact.

The schema written to disk:

    {
        "version": 1,
        "provider": "mock" | "groq",
        "model": "...",
        "generated_at": "2026-04-20T12:34:56Z",
        "sources": {
            "transcript": "transcript.json",
            "chapters": "chapter_candidates.json" | null,
            "speaker_names": "speaker_names.json" | null,
            "selected_frames": "selected_frames.json" | null
        },
        "overview": {
            "title": "...",
            "short_summary": "...",
            "detailed_summary": "...",
            "quick_bullets": ["...", "..."]
        },
        "chapters": [
            {
                "index": 0,
                "start_seconds": 0.0,
                "end_seconds": 123.4,
                "title": "...",
                "summary": "...",
                "bullets": ["...", "..."],
                "action_items": ["...", "..."],
                "speaker_focus": ["Host", "Guest"]
            }
        ],
        "action_items": [
            {
                "text": "...",
                "chapter_index": 0,
                "timestamp_seconds": 42.0,
                "owner": null,
                "due": null
            }
        ]
    }
"""

from __future__ import annotations

import http.client
import json
import os
import re
import ssl
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, read_job, update_stage


# ---------------------------------------------------------------------------
# Public constants / env
# ---------------------------------------------------------------------------

INSIGHTS_VERSION = 1
PROVIDER_CHOICES: tuple[str, ...] = ("mock", "groq")
DEFAULT_PROVIDER = "mock"

GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"
GROQ_DEFAULT_BASE_URL = "https://api.groq.com"
GROQ_CHAT_PATH = "/openai/v1/chat/completions"

# Input-size safety rails for Groq. Mock provider ignores these.
MAX_TRANSCRIPT_CHARS = 48_000
MAX_CHAPTER_TEXT_CHARS = 2_000
MAX_RESPONSE_BYTES = 512 * 1024

# Heuristic patterns the mock provider uses to find action-item
# candidates. Case-insensitive, applied to segment text. Deliberately
# conservative: we want a stable mock, not a smart one.
_MOCK_ACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baction item\b[:\-]?\s*(.+)", re.IGNORECASE),
    re.compile(r"\btodo\b[:\-]?\s*(.+)", re.IGNORECASE),
    re.compile(r"\bwe (?:need|should|must)\s+(.+)", re.IGNORECASE),
    re.compile(r"\bfollow[- ]up\b[:\-]?\s*(.+)", re.IGNORECASE),
)

_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _first_sentence(text: str, max_words: int = 12) -> str:
    """Return a short one-liner suitable for a chapter title fallback."""
    cleaned = _collapse_ws(text)
    if not cleaned:
        return ""
    # Split on sentence boundary, then fall back to word count.
    parts = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)
    candidate = parts[0] if parts else cleaned
    words = candidate.split()
    if len(words) > max_words:
        words = words[:max_words]
    title = " ".join(words).rstrip(".,;:")
    return title


def _is_nonneg_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _sorted_set_preserve_order(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        if v and v not in seen:
            seen[v] = None
    return list(seen)


# ---------------------------------------------------------------------------
# Shape validation (used by both providers and the verifier scripts)
# ---------------------------------------------------------------------------

def _require(data: dict, field: str) -> None:
    if field not in data:
        raise RuntimeError(f"insights.json malformed: missing '{field}'")


def validate_insights(data: object) -> dict:
    """Raise RuntimeError with ``insights.json malformed: ...`` prefix on
    any structural problem; return the validated dict on success."""
    if not isinstance(data, dict):
        raise RuntimeError(
            "insights.json malformed: top-level is not a JSON object"
        )
    for field in (
        "version",
        "provider",
        "model",
        "generated_at",
        "overview",
        "chapters",
        "action_items",
    ):
        _require(data, field)
    if data["version"] != INSIGHTS_VERSION:
        raise RuntimeError(
            f"insights.json malformed: unsupported version "
            f"{data['version']!r}, expected {INSIGHTS_VERSION}"
        )
    if data["provider"] not in PROVIDER_CHOICES:
        raise RuntimeError(
            "insights.json malformed: provider must be one of "
            f"{list(PROVIDER_CHOICES)}"
        )
    if not isinstance(data["model"], str) or not data["model"]:
        raise RuntimeError(
            "insights.json malformed: model must be a non-empty string"
        )
    if not isinstance(data["generated_at"], str):
        raise RuntimeError(
            "insights.json malformed: generated_at must be a string"
        )

    overview = data["overview"]
    if not isinstance(overview, dict):
        raise RuntimeError(
            "insights.json malformed: overview is not a JSON object"
        )
    for f in ("title", "short_summary", "detailed_summary", "quick_bullets"):
        if f not in overview:
            raise RuntimeError(
                f"insights.json malformed: overview.{f} missing"
            )
    for f in ("title", "short_summary", "detailed_summary"):
        if not isinstance(overview[f], str):
            raise RuntimeError(
                f"insights.json malformed: overview.{f} must be a string"
            )
    if not isinstance(overview["quick_bullets"], list) or not all(
        isinstance(x, str) for x in overview["quick_bullets"]
    ):
        raise RuntimeError(
            "insights.json malformed: overview.quick_bullets must be a "
            "list of strings"
        )

    chapters = data["chapters"]
    if not isinstance(chapters, list):
        raise RuntimeError(
            "insights.json malformed: 'chapters' is not a list"
        )
    for ch in chapters:
        if not isinstance(ch, dict):
            raise RuntimeError(
                "insights.json malformed: chapter entry is not an object"
            )
        for f in (
            "index",
            "start_seconds",
            "end_seconds",
            "title",
            "summary",
            "bullets",
            "action_items",
            "speaker_focus",
        ):
            if f not in ch:
                raise RuntimeError(
                    f"insights.json malformed: chapter missing '{f}'"
                )
        if not isinstance(ch["index"], int) or isinstance(ch["index"], bool):
            raise RuntimeError(
                "insights.json malformed: chapter 'index' must be an "
                "integer"
            )
        if not _is_nonneg_number(ch["start_seconds"]):
            raise RuntimeError(
                "insights.json malformed: chapter 'start_seconds' must be "
                "a non-negative number"
            )
        if not _is_nonneg_number(ch["end_seconds"]):
            raise RuntimeError(
                "insights.json malformed: chapter 'end_seconds' must be a "
                "non-negative number"
            )
        if not isinstance(ch["title"], str):
            raise RuntimeError(
                "insights.json malformed: chapter 'title' must be a string"
            )
        if not isinstance(ch["summary"], str):
            raise RuntimeError(
                "insights.json malformed: chapter 'summary' must be a "
                "string"
            )
        for list_field in ("bullets", "action_items", "speaker_focus"):
            if not isinstance(ch[list_field], list) or not all(
                isinstance(x, str) for x in ch[list_field]
            ):
                raise RuntimeError(
                    f"insights.json malformed: chapter '{list_field}' "
                    "must be a list of strings"
                )

    actions = data["action_items"]
    if not isinstance(actions, list):
        raise RuntimeError(
            "insights.json malformed: 'action_items' is not a list"
        )
    for ai in actions:
        if not isinstance(ai, dict):
            raise RuntimeError(
                "insights.json malformed: action_item entry is not an "
                "object"
            )
        if "text" not in ai or not isinstance(ai["text"], str):
            raise RuntimeError(
                "insights.json malformed: action_item.text must be a string"
            )
        if "chapter_index" in ai and ai["chapter_index"] is not None:
            if not isinstance(ai["chapter_index"], int) or isinstance(
                ai["chapter_index"], bool
            ):
                raise RuntimeError(
                    "insights.json malformed: action_item.chapter_index "
                    "must be integer or null"
                )
        if "timestamp_seconds" in ai and ai["timestamp_seconds"] is not None:
            if not _is_nonneg_number(ai["timestamp_seconds"]):
                raise RuntimeError(
                    "insights.json malformed: action_item.timestamp_seconds "
                    "must be a non-negative number or null"
                )
    return data


# ---------------------------------------------------------------------------
# Input loading helpers
# ---------------------------------------------------------------------------

def _load_json_if_exists(path: Path) -> Any | None:
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _iter_segments(transcript: dict) -> list[dict]:
    """Prefer diarized utterances when present so action-item heuristics
    can attach speaker info; fall back to segments."""
    uts = transcript.get("utterances")
    if isinstance(uts, list) and uts:
        return [u for u in uts if isinstance(u, dict)]
    segs = transcript.get("segments")
    if isinstance(segs, list):
        return [s for s in segs if isinstance(s, dict)]
    return []


def _speaker_label(segment: dict, speaker_names: dict[str, str]) -> str | None:
    sp = segment.get("speaker")
    if isinstance(sp, int):
        key = str(sp)
        return speaker_names.get(key) or f"Speaker {sp}"
    if isinstance(sp, str) and sp.strip():
        stripped = sp.strip()
        return speaker_names.get(stripped) or stripped
    return None


def _load_context(paths: JobPaths) -> dict:
    """Read transcript + optional artifacts into a single context dict.

    Never raises on missing optional artifacts; raises RuntimeError when
    the required transcript is absent or malformed.
    """
    if not paths.transcript_json.is_file():
        raise RuntimeError(
            "transcript.json is required for recap insights and was not "
            "found"
        )
    with open(paths.transcript_json, "r", encoding="utf-8") as f:
        try:
            transcript = json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"transcript.json malformed: invalid JSON: {e.msg}"
            ) from e
    if not isinstance(transcript, dict):
        raise RuntimeError(
            "transcript.json malformed: top-level is not a JSON object"
        )

    chapters = _load_json_if_exists(paths.chapter_candidates_json)
    if chapters is not None and not isinstance(chapters, dict):
        chapters = None

    selected = _load_json_if_exists(paths.selected_frames_json)
    if selected is not None and not isinstance(selected, dict):
        selected = None

    speaker_names_doc = _load_json_if_exists(paths.speaker_names_json) or {}
    if isinstance(speaker_names_doc, dict):
        raw_speakers = speaker_names_doc.get("speakers")
    else:
        raw_speakers = None
    speaker_names: dict[str, str] = {}
    if isinstance(raw_speakers, dict):
        for key, value in raw_speakers.items():
            if isinstance(key, str) and isinstance(value, str) and value.strip():
                speaker_names[key] = value.strip()

    return {
        "transcript": transcript,
        "chapter_candidates": chapters,
        "selected_frames": selected,
        "speaker_names": speaker_names,
    }


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

def _mock_chapter_entry(
    raw_chapter: dict,
    transcript: dict,
    speaker_names: dict[str, str],
) -> dict:
    idx = raw_chapter.get("index")
    if not isinstance(idx, int):
        idx = 0
    start = raw_chapter.get("start_seconds")
    end = raw_chapter.get("end_seconds")
    start_seconds = float(start) if _is_nonneg_number(start) else 0.0
    end_seconds = float(end) if _is_nonneg_number(end) else start_seconds
    text = raw_chapter.get("text") or ""
    cleaned = _collapse_ws(text)
    title = _first_sentence(cleaned) or f"Chapter {idx}"
    summary = _truncate(cleaned, 320)
    # Bullets: up to three sentence-boundary splits of the chapter text.
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", cleaned)
        if s.strip()
    ]
    bullets = [_truncate(s, 180) for s in sentences[:3]]

    # Action items: scan full chapter text for any of the heuristic
    # patterns and collect unique hits.
    action_hits: list[str] = []
    for sent in sentences:
        for pat in _MOCK_ACTION_PATTERNS:
            m = pat.search(sent)
            if m:
                action_hits.append(_truncate(_collapse_ws(m.group(1)), 160))
                break
    action_items = _sorted_set_preserve_order(action_hits)[:5]

    # Speakers appearing in the chapter's segment range.
    segs = _iter_segments(transcript)
    speaker_focus: list[str] = []
    seen: set[str] = set()
    for seg in segs:
        seg_start = seg.get("start")
        if not _is_nonneg_number(seg_start):
            continue
        if seg_start < start_seconds or seg_start >= end_seconds:
            continue
        label = _speaker_label(seg, speaker_names)
        if label and label not in seen:
            seen.add(label)
            speaker_focus.append(label)

    return {
        "index": idx,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "title": title,
        "summary": summary,
        "bullets": bullets,
        "action_items": action_items,
        "speaker_focus": speaker_focus,
    }


def _mock_global_actions(
    chapters: list[dict],
    transcript: dict,
) -> list[dict]:
    out: list[dict] = []
    seen_texts: set[str] = set()
    for ch in chapters:
        for ai_text in ch["action_items"]:
            key = ai_text.lower()
            if key in seen_texts:
                continue
            seen_texts.add(key)
            # Attach the first transcript segment in the chapter window
            # as a timestamp anchor, for jump-to-moment.
            anchor: float | None = None
            for seg in _iter_segments(transcript):
                s = seg.get("start")
                if _is_nonneg_number(s) and ch["start_seconds"] <= s < ch["end_seconds"]:
                    anchor = float(s)
                    break
            out.append({
                "text": ai_text,
                "chapter_index": ch["index"],
                "timestamp_seconds": anchor,
                "owner": None,
                "due": None,
            })
    return out


def _generate_mock(
    context: dict,
    original_filename: str | None,
    job_id: str,
) -> dict:
    transcript = context["transcript"]
    speaker_names = context["speaker_names"]
    raw_chapters = (
        (context["chapter_candidates"] or {}).get("chapters") or []
    )

    # Fall back to a single virtual chapter when no chapter_candidates.
    if not raw_chapters:
        segs = _iter_segments(transcript)
        end = transcript.get("duration")
        if not _is_nonneg_number(end):
            end = segs[-1].get("end") if segs else 0.0
        whole_text = " ".join(
            (seg.get("text") or "").strip() for seg in segs
        )
        raw_chapters = [{
            "index": 1,
            "start_seconds": 0.0,
            "end_seconds": float(end) if _is_nonneg_number(end) else 0.0,
            "text": whole_text,
        }]

    chapter_entries = [
        _mock_chapter_entry(ch, transcript, speaker_names)
        for ch in raw_chapters
        if isinstance(ch, dict)
    ]

    # Overview derived from concatenated chapter text.
    joined = _collapse_ws(
        " ".join(
            (ch.get("text") or "") if isinstance(ch, dict) else ""
            for ch in raw_chapters
        )
    )
    title = original_filename or job_id or "Recap"
    title = Path(title).stem if "." in title else title
    short_summary = _truncate(joined, 280) or f"Recap of {title}."
    detailed_summary = _truncate(joined, 1200) or short_summary
    quick_bullets = [ch["title"] for ch in chapter_entries if ch["title"]][:5]
    if not quick_bullets:
        quick_bullets = [short_summary]

    return {
        "version": INSIGHTS_VERSION,
        "provider": "mock",
        "model": "mock-v1",
        "generated_at": _now(),
        "sources": _build_sources_block(context),
        "overview": {
            "title": title,
            "short_summary": short_summary,
            "detailed_summary": detailed_summary,
            "quick_bullets": quick_bullets,
        },
        "chapters": chapter_entries,
        "action_items": _mock_global_actions(chapter_entries, transcript),
    }


# ---------------------------------------------------------------------------
# Groq provider
# ---------------------------------------------------------------------------

def _build_groq_prompt(
    context: dict,
    original_filename: str | None,
    job_id: str,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the chat-completions call."""
    transcript = context["transcript"]
    segs = _iter_segments(transcript)
    speaker_names = context["speaker_names"]

    # Flatten transcript into a compact "[start–end] Speaker: text" per
    # line so we fit more of it in the prompt budget.
    lines: list[str] = []
    for seg in segs:
        start = seg.get("start")
        end = seg.get("end")
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        label = _speaker_label(seg, speaker_names) or ""
        stamp = ""
        if _is_nonneg_number(start):
            stamp = f"[{float(start):.1f}s] "
        if label:
            lines.append(f"{stamp}{label}: {text}")
        else:
            lines.append(f"{stamp}{text}")
    transcript_text = _truncate(
        "\n".join(lines), MAX_TRANSCRIPT_CHARS
    )

    chapters_raw = (
        (context["chapter_candidates"] or {}).get("chapters") or []
    )
    chapter_lines: list[str] = []
    for ch in chapters_raw:
        if not isinstance(ch, dict):
            continue
        idx = ch.get("index")
        start = ch.get("start_seconds")
        end = ch.get("end_seconds")
        text = _truncate(_collapse_ws(ch.get("text") or ""), MAX_CHAPTER_TEXT_CHARS)
        chapter_lines.append(
            f"Chapter {idx} [{start}s – {end}s]: {text}"
        )
    chapters_text = "\n".join(chapter_lines)

    title_hint = original_filename or job_id or "Recap"
    system = (
        "You are Recap's insights generator. Read the transcript and "
        "chapters of a screen recording and produce STRICT JSON ONLY "
        "matching the schema in the user message. Do not add commentary, "
        "markdown, or code fences. Every field must be present. Summaries "
        "are concise and factual. Action items are concrete verbs the "
        "viewer can act on; do not invent action items that the transcript "
        "does not support."
    )
    user = (
        f"Source title: {title_hint}\n\n"
        "JSON schema you must return (values may differ; shape must not):\n"
        "{\n"
        "  \"overview\": {\"title\": str, \"short_summary\": str, "
        "\"detailed_summary\": str, \"quick_bullets\": [str]},\n"
        "  \"chapters\": [{\"index\": int, \"start_seconds\": number, "
        "\"end_seconds\": number, \"title\": str, \"summary\": str, "
        "\"bullets\": [str], \"action_items\": [str], "
        "\"speaker_focus\": [str]}],\n"
        "  \"action_items\": [{\"text\": str, \"chapter_index\": int|null, "
        "\"timestamp_seconds\": number|null, \"owner\": str|null, "
        "\"due\": str|null}]\n"
        "}\n\n"
        "Transcript (truncated if long):\n"
        f"{transcript_text}\n\n"
        "Chapters (may be empty):\n"
        f"{chapters_text}\n"
    )
    return system, user


def _groq_http_call(
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
) -> dict:
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError(
            f"GROQ_BASE_URL is not a valid URL: {base_url!r}"
        )
    body = json.dumps({
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")

    conn: http.client.HTTPConnection
    if parsed.scheme == "https":
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(
            parsed.hostname,
            parsed.port or 443,
            timeout=60.0,
            context=ctx,
        )
    else:
        conn = http.client.HTTPConnection(
            parsed.hostname,
            parsed.port or 80,
            timeout=60.0,
        )
    try:
        conn.request(
            "POST",
            GROQ_CHAT_PATH,
            body=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        resp = conn.getresponse()
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError(
                "Groq response exceeded maximum accepted size"
            )
        if resp.status != 200:
            snippet = raw.decode("utf-8", "replace")[:200]
            raise RuntimeError(
                f"Groq API returned {resp.status}: {snippet}"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Groq API returned non-JSON body: {e.msg}"
            ) from e
    finally:
        conn.close()

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("Groq API returned no choices")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Groq API returned empty message content")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Groq response content was not valid JSON: {e.msg}"
        ) from e


def _generate_groq(
    context: dict,
    original_filename: str | None,
    job_id: str,
) -> dict:
    api_key = os.environ.get("GROQ_API_KEY") or ""
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set; cannot run insights --provider groq"
        )
    model = os.environ.get("GROQ_MODEL") or GROQ_DEFAULT_MODEL
    base_url = os.environ.get("GROQ_BASE_URL") or GROQ_DEFAULT_BASE_URL

    system, user = _build_groq_prompt(context, original_filename, job_id)
    raw = _groq_http_call(api_key, base_url, model, system, user)

    # Merge server-provided fields into our canonical shape. Fill in
    # anything missing with a mock-generated default so the output is
    # always valid.
    fallback = _generate_mock(context, original_filename, job_id)

    overview = raw.get("overview")
    if not isinstance(overview, dict):
        overview = fallback["overview"]
    else:
        for field, default in fallback["overview"].items():
            if field == "quick_bullets":
                if not isinstance(overview.get(field), list) or not all(
                    isinstance(x, str) for x in overview[field]
                ):
                    overview[field] = default
            elif not isinstance(overview.get(field), str):
                overview[field] = default

    chapters = raw.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        chapters = fallback["chapters"]
    else:
        fixed: list[dict] = []
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            fixed.append({
                "index": ch.get("index") if isinstance(ch.get("index"), int) else len(fixed),
                "start_seconds": float(ch.get("start_seconds"))
                    if _is_nonneg_number(ch.get("start_seconds")) else 0.0,
                "end_seconds": float(ch.get("end_seconds"))
                    if _is_nonneg_number(ch.get("end_seconds")) else 0.0,
                "title": str(ch.get("title") or ""),
                "summary": str(ch.get("summary") or ""),
                "bullets": [str(x) for x in (ch.get("bullets") or []) if isinstance(x, str)],
                "action_items": [
                    str(x) for x in (ch.get("action_items") or [])
                    if isinstance(x, str)
                ],
                "speaker_focus": [
                    str(x) for x in (ch.get("speaker_focus") or [])
                    if isinstance(x, str)
                ],
            })
        chapters = fixed or fallback["chapters"]

    action_items_raw = raw.get("action_items")
    if not isinstance(action_items_raw, list):
        action_items_raw = []
    actions: list[dict] = []
    for ai in action_items_raw:
        if not isinstance(ai, dict):
            continue
        text = ai.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        actions.append({
            "text": text.strip(),
            "chapter_index": ai.get("chapter_index")
                if isinstance(ai.get("chapter_index"), int) else None,
            "timestamp_seconds": float(ai["timestamp_seconds"])
                if _is_nonneg_number(ai.get("timestamp_seconds")) else None,
            "owner": ai.get("owner") if isinstance(ai.get("owner"), str) else None,
            "due": ai.get("due") if isinstance(ai.get("due"), str) else None,
        })

    return {
        "version": INSIGHTS_VERSION,
        "provider": "groq",
        "model": model,
        "generated_at": _now(),
        "sources": _build_sources_block(context),
        "overview": overview,
        "chapters": chapters,
        "action_items": actions,
    }


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def _build_sources_block(context: dict) -> dict:
    return {
        "transcript": "transcript.json",
        "chapters": (
            "chapter_candidates.json" if context["chapter_candidates"] else None
        ),
        "speaker_names": (
            "speaker_names.json" if context["speaker_names"] else None
        ),
        "selected_frames": (
            "selected_frames.json" if context["selected_frames"] else None
        ),
    }


def _write_insights(paths: JobPaths, payload: dict) -> None:
    tmp = paths.insights_json.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(paths.insights_json)


def run(
    paths: JobPaths,
    provider: str = DEFAULT_PROVIDER,
    force: bool = False,
) -> Path:
    if provider not in PROVIDER_CHOICES:
        raise RuntimeError(
            f"insights provider must be one of {list(PROVIDER_CHOICES)}"
        )
    update_stage(paths, "insights", RUNNING)
    try:
        if not force and paths.insights_json.exists():
            update_stage(
                paths, "insights", COMPLETED, extra={"skipped": True}
            )
            return paths.insights_json

        context = _load_context(paths)
        state = read_job(paths)
        original_filename = state.get("original_filename")
        job_id = state.get("job_id") or paths.root.name

        if provider == "mock":
            payload = _generate_mock(context, original_filename, job_id)
        else:
            payload = _generate_groq(context, original_filename, job_id)

        # Sanity check before atomic write.
        validate_insights(payload)
        _write_insights(paths, payload)

        update_stage(
            paths,
            "insights",
            COMPLETED,
            extra={
                "artifact": paths.insights_json.name,
                "provider": payload["provider"],
                "model": payload["model"],
                "chapter_count": len(payload["chapters"]),
                "action_item_count": len(payload["action_items"]),
            },
        )
        return paths.insights_json
    except Exception as e:
        # Clean up any stray .tmp before surfacing the failure.
        tmp = paths.insights_json.with_suffix(".json.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(
            paths,
            "insights",
            FAILED,
            error=f"{type(e).__name__}: {e}",
        )
        raise
