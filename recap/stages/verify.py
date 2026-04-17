"""Phase 4 slice: optional VLM verification over `frame_shortlist.json`.

Reads the pre-VLM shortlist (`frame_shortlist.json`), the per-chapter
text context (`chapter_candidates.json`), the per-frame transcript
window (`frame_windows.json`), and the candidate JPEGs under
`candidate_frames/`.  Writes `selected_frames.json`.

Two providers are implemented as sibling functions (no registry, no
ABC, no plugin system):

  - `_verify_mock`   default; fully deterministic; no network.
  - `_verify_gemini` stdlib `urllib.request` only; reads
                     `GEMINI_API_KEY` / `GEMINI_MODEL` /
                     `GEMINI_BASE_URL` from the environment only on
                     recompute; never writes keys to disk.

The stage is opt-in via `recap verify --job <path>`.  `recap run`
stays Phase-1-only and does NOT invoke this stage.  The stage does
NOT modify `report.md`, does NOT embed screenshots, does NOT export
documents, does NOT add UI, does NOT add non-stdlib dependencies,
and does NOT touch any upstream artifact.

Selection policy (closed vocabularies, fixed at the code level):

  relevance: relevant | not_relevant | uncertain
  decision:  selected_hero | selected_supporting | vlm_rejected
  reasons append one of: vlm_relevant, vlm_uncertain_kept,
                         vlm_not_relevant, vlm_tie_broken_by_rank

A retune of the prompt, request shape, parse rules, or decision
policy MUST bump either `VLM_PROVIDER_VERSION` or
`VLM_POLICY_VERSION` so the skip contract invalidates any stored
artifact.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# ---- fixed code-level constants (not CLI flags / env / config) ----------

VLM_DEFAULT_PROVIDER = "mock"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_TIMEOUT_SECONDS = 120
VLM_PROVIDER_VERSION = "vlm_v1"
VLM_POLICY_VERSION = "vlm_select_v1"
VLM_CONFIDENCE_KEEP_THRESHOLD = 0.50
CHAPTER_CONTEXT_CHARS = 1500
WINDOW_CONTEXT_CHARS = 1500
VLM_MAX_CAPTION_CHARS = 240

_RELEVANCE_VALUES = ("relevant", "not_relevant", "uncertain")
_SHORTLIST_KEEP_DECISIONS = ("hero", "supporting")
_VERIFIED_FRAME_FIELDS = (
    "rank",
    "scene_index",
    "frame_file",
    "midpoint_seconds",
    "composite_score",
    "clip_similarity",
    "text_novelty",
    "decision",
    "reasons",
)
_BODY_SNIPPET_MAX = 200
_WS_RE = re.compile(r"\s+")


# ---- helpers ------------------------------------------------------------

def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def _fingerprint(data: object) -> str:
    canonical = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json_raw(path: Path, label: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return data


def _snippet(body: bytes | str) -> str:
    if isinstance(body, bytes):
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = ""
    else:
        text = body
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > _BODY_SNIPPET_MAX:
        text = text[:_BODY_SNIPPET_MAX]
    return text


def _truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        return ""
    if len(text) <= limit:
        return text
    return text[:limit]


# ---- input validation ---------------------------------------------------

def _validate_shortlist(raw: dict) -> list[dict]:
    for key in ("chapters", "chapter_count", "frame_count"):
        if key not in raw:
            raise RuntimeError(
                f"frame_shortlist.json is missing required field '{key}'"
            )
    chapters = raw["chapters"]
    if not isinstance(chapters, list):
        raise RuntimeError("frame_shortlist.json 'chapters' must be a list")
    for ci, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            raise RuntimeError(
                f"frame_shortlist.json chapter at index {ci} is not an object"
            )
        for field in ("chapter_index", "start_seconds", "end_seconds", "frames"):
            if field not in ch:
                raise RuntimeError(
                    f"frame_shortlist.json chapter at index {ci} "
                    f"is missing '{field}'"
                )
        if not _is_int(ch["chapter_index"]):
            raise RuntimeError(
                f"frame_shortlist.json chapter at index {ci} "
                "has non-integer 'chapter_index'"
            )
        if not _is_number(ch["start_seconds"]):
            raise RuntimeError(
                f"frame_shortlist.json chapter at index {ci} "
                "has non-numeric 'start_seconds'"
            )
        if not _is_number(ch["end_seconds"]):
            raise RuntimeError(
                f"frame_shortlist.json chapter at index {ci} "
                "has non-numeric 'end_seconds'"
            )
        frames = ch["frames"]
        if not isinstance(frames, list):
            raise RuntimeError(
                f"frame_shortlist.json chapter at index {ci} "
                "has non-list 'frames'"
            )
        for fi, fr in enumerate(frames):
            if not isinstance(fr, dict):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} is not an object"
                )
            if fr.get("decision") not in _SHORTLIST_KEEP_DECISIONS and fr.get(
                "decision"
            ) not in (
                "rejected_duplicate",
                "rejected_weak_signal",
                "dropped_over_budget",
            ):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has unsupported "
                    f"decision {fr.get('decision')!r}"
                )
            if fr["decision"] not in _SHORTLIST_KEEP_DECISIONS:
                continue
            for field in _VERIFIED_FRAME_FIELDS:
                if field not in fr:
                    raise RuntimeError(
                        f"frame_shortlist.json chapter {ch['chapter_index']} "
                        f"frame at index {fi} is missing '{field}'"
                    )
            if not _is_int(fr["rank"]):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-integer 'rank'"
                )
            if not _is_int(fr["scene_index"]):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-integer 'scene_index'"
                )
            if not isinstance(fr["frame_file"], str) or not fr["frame_file"]:
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has empty or non-string 'frame_file'"
                )
            if not _is_number(fr["midpoint_seconds"]):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric 'midpoint_seconds'"
                )
            if not _is_number(fr["composite_score"]):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric 'composite_score'"
                )
            if fr["clip_similarity"] is not None and not _is_number(
                fr["clip_similarity"]
            ):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric 'clip_similarity'"
                )
            if fr["text_novelty"] is not None and not _is_number(
                fr["text_novelty"]
            ):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric 'text_novelty'"
                )
            reasons = fr["reasons"]
            if not isinstance(reasons, list) or not all(
                isinstance(r, str) for r in reasons
            ):
                raise RuntimeError(
                    f"frame_shortlist.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has invalid 'reasons'"
                )
    return chapters


def _index_chapter_text(chapters_raw: dict) -> dict[int, str]:
    chs = chapters_raw.get("chapters")
    if not isinstance(chs, list):
        raise RuntimeError(
            "chapter_candidates.json is missing a 'chapters' list"
        )
    out: dict[int, str] = {}
    for ci, ch in enumerate(chs):
        if not isinstance(ch, dict):
            raise RuntimeError(
                f"chapter_candidates.json chapter at index {ci} is not an object"
            )
        idx = ch.get("index")
        text = ch.get("text", "")
        if not _is_int(idx):
            raise RuntimeError(
                f"chapter_candidates.json chapter at index {ci} "
                "has non-integer 'index'"
            )
        if not isinstance(text, str):
            raise RuntimeError(
                f"chapter_candidates.json chapter at index {ci} "
                "has non-string 'text'"
            )
        out[idx] = text
    return out


def _index_window_text(windows_raw: dict) -> dict[int, str]:
    frames = windows_raw.get("frames")
    if not isinstance(frames, list):
        raise RuntimeError(
            "frame_windows.json is missing a 'frames' list"
        )
    out: dict[int, str] = {}
    for fi, fr in enumerate(frames):
        if not isinstance(fr, dict):
            raise RuntimeError(
                f"frame_windows.json frame at index {fi} is not an object"
            )
        si = fr.get("scene_index")
        wt = fr.get("window_text", "")
        if not _is_int(si):
            raise RuntimeError(
                f"frame_windows.json frame at index {fi} has non-integer "
                "'scene_index'"
            )
        if wt is None:
            wt = ""
        if not isinstance(wt, str):
            raise RuntimeError(
                f"frame_windows.json frame at index {fi} has non-string "
                "'window_text'"
            )
        out[si] = wt
    return out


# ---- mock provider (deterministic, no network) --------------------------

def _verify_mock(
    frame: dict, chapter_text: str, window_text: str, image_bytes: bytes
) -> dict:
    del chapter_text, window_text, image_bytes
    composite = float(frame["composite_score"])
    relevance = "relevant" if composite >= 0.30 else "uncertain"
    confidence = _clamp01(composite)
    return {
        "relevance": relevance,
        "confidence": confidence,
        "caption": None,
    }


# ---- gemini provider (stdlib HTTP, one request per frame) ---------------

_GEMINI_PROMPT = (
    "You are verifying whether a screenshot from a screen recording is "
    "relevant to the spoken context in which it was captured. Respond "
    "with a single JSON object and nothing else, matching this shape "
    "exactly:\n"
    "{\"relevance\":\"relevant\"|\"not_relevant\"|\"uncertain\","
    "\"confidence\":<number between 0 and 1>,"
    "\"caption\":<short caption string or null>}\n"
    "Rules:\n"
    "- \"relevance\" must be one of relevant, not_relevant, uncertain.\n"
    "- \"confidence\" is your subjective confidence in the relevance "
    "label, between 0.0 and 1.0.\n"
    "- \"caption\" is optional; if provided, keep it under "
    f"{VLM_MAX_CAPTION_CHARS} characters. Use null if you cannot "
    "caption the image confidently.\n"
    "- Output JSON only. Do not wrap in markdown. Do not add prose."
)


def _gemini_build_body(
    chapter_text: str, window_text: str, image_bytes: bytes
) -> bytes:
    user_text = (
        f"{_GEMINI_PROMPT}\n\n"
        f"Chapter context (truncated):\n{chapter_text}\n\n"
        f"Per-frame transcript window (truncated):\n{window_text}"
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": user_text},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode(
                                "ascii"
                            ),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.0,
        },
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _gemini_extract_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise RuntimeError("not an object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("no candidates in response")
    first = candidates[0]
    if not isinstance(first, dict):
        raise RuntimeError("candidate is not an object")
    content = first.get("content")
    if not isinstance(content, dict):
        raise RuntimeError("candidate has no content")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise RuntimeError("candidate content has no parts")
    pieces: list[str] = []
    for p in parts:
        if isinstance(p, dict):
            t = p.get("text")
            if isinstance(t, str):
                pieces.append(t)
    text = "".join(pieces).strip()
    if not text:
        raise RuntimeError("candidate text is empty")
    return text


def _parse_verification_json(text: str) -> dict:
    # Some providers wrap JSON in ```json fences even when asked not to.
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        # Drop leading "json\n" if present
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"model output is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise RuntimeError("model output is not a JSON object")
    return parsed


def _coerce_verification(payload: dict) -> dict:
    relevance = payload.get("relevance")
    if relevance not in _RELEVANCE_VALUES:
        raise RuntimeError(f"gemini returned unsupported relevance: {relevance!r}")
    conf_raw = payload.get("confidence")
    if not _is_number(conf_raw):
        raise RuntimeError(
            f"gemini returned non-numeric confidence: {conf_raw!r}"
        )
    confidence = _clamp01(float(conf_raw))
    caption_raw = payload.get("caption")
    if caption_raw is None:
        caption = None
    elif isinstance(caption_raw, str):
        stripped = caption_raw.strip()
        if not stripped:
            caption = None
        else:
            caption = _truncate(stripped, VLM_MAX_CAPTION_CHARS)
    else:
        raise RuntimeError(
            f"gemini returned non-string caption: {type(caption_raw).__name__}"
        )
    return {
        "relevance": relevance,
        "confidence": confidence,
        "caption": caption,
    }


def _gemini_http(
    body: bytes, url: str
) -> dict:
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=GEMINI_TIMEOUT_SECONDS
        ) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read() or b""
        except Exception:
            raw = b""
        snippet = _snippet(raw)
        if status in (401, 403):
            raise RuntimeError(
                f"gemini authentication failed ({status}): {snippet}"
            ) from e
        raise RuntimeError(
            f"gemini request failed ({status}): {snippet}"
        ) from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, socket.timeout):
            raise RuntimeError(
                f"gemini request timed out after {GEMINI_TIMEOUT_SECONDS}s"
            ) from e
        raise RuntimeError(f"gemini network error: {reason}") from e
    except socket.timeout as e:
        raise RuntimeError(
            f"gemini request timed out after {GEMINI_TIMEOUT_SECONDS}s"
        ) from e

    if status < 200 or status >= 300:
        raise RuntimeError(
            f"gemini request failed ({status}): {_snippet(raw)}"
        )
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise RuntimeError(f"gemini returned invalid JSON: {e}") from e


def _verify_gemini(
    frame: dict,
    chapter_text: str,
    window_text: str,
    image_bytes: bytes,
    *,
    model: str,
    base_url: str,
    api_key: str,
) -> dict:
    del frame
    body = _gemini_build_body(chapter_text, window_text, image_bytes)
    query = urllib.parse.urlencode({"key": api_key})
    url = (
        f"{base_url.rstrip('/')}/v1beta/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent?{query}"
    )
    payload = _gemini_http(body, url)
    try:
        text = _gemini_extract_text(payload)
    except RuntimeError as e:
        raise RuntimeError(f"gemini returned invalid JSON: {e}") from e
    try:
        parsed = _parse_verification_json(text)
    except RuntimeError as e:
        raise RuntimeError(
            f"gemini returned invalid verification JSON: {e}"
        ) from e
    return _coerce_verification(parsed)


# ---- decision policy ----------------------------------------------------

def _apply_policy(
    shortlist_chapter: dict,
    verifications_by_scene: dict[int, dict],
) -> tuple[dict, dict]:
    """Apply the decision policy to one chapter.

    Returns (out_chapter, per_scene_counters) where out_chapter is the
    `selected_frames.json` chapter entry and counters is the per-chapter
    roll-up.
    """
    kept_frames: list[dict] = []
    rejected_frames: list[dict] = []
    ordered: list[dict] = []

    for fr in shortlist_chapter["frames"]:
        if fr["decision"] not in _SHORTLIST_KEEP_DECISIONS:
            continue
        verification = verifications_by_scene[fr["scene_index"]]
        shortlist_decision = fr["decision"]
        base_reason = (
            "kept_as_hero"
            if shortlist_decision == "hero"
            else "kept_as_supporting"
        )
        reasons: list[str] = [base_reason]
        relevance = verification["relevance"]
        if relevance == "not_relevant":
            decision = "vlm_rejected"
            reasons.append("vlm_not_relevant")
        elif relevance == "relevant":
            decision = (
                "selected_hero"
                if shortlist_decision == "hero"
                else "selected_supporting"
            )
            reasons.append("vlm_relevant")
        else:  # uncertain
            if verification["confidence"] >= VLM_CONFIDENCE_KEEP_THRESHOLD:
                decision = (
                    "selected_hero"
                    if shortlist_decision == "hero"
                    else "selected_supporting"
                )
                reasons.append("vlm_uncertain_kept")
            else:
                decision = "vlm_rejected"
                reasons.append("vlm_not_relevant")

        frame_out = {
            "rank": fr["rank"],
            "scene_index": fr["scene_index"],
            "frame_file": fr["frame_file"],
            "midpoint_seconds": fr["midpoint_seconds"],
            "composite_score": fr["composite_score"],
            "clip_similarity": fr["clip_similarity"],
            "text_novelty": fr["text_novelty"],
            "window_text": verifications_by_scene[fr["scene_index"]].get(
                "_window_text", ""
            ),
            "shortlist_decision": shortlist_decision,
            "verification": {
                "provider": verification["_provider"],
                "model": verification["_model"],
                "relevance": verification["relevance"],
                "confidence": verification["confidence"],
                "caption": verification["caption"],
            },
            "decision": decision,
            "reasons": reasons,
        }
        ordered.append(frame_out)
        if decision == "vlm_rejected":
            rejected_frames.append(frame_out)
        else:
            kept_frames.append(frame_out)

    # Hero promotion: if the original hero is not currently selected_hero,
    # promote the highest-ranked surviving supporting frame (lowest rank
    # number) to selected_hero.
    has_hero = any(f["decision"] == "selected_hero" for f in kept_frames)
    if not has_hero:
        promote = None
        for f in kept_frames:
            if f["decision"] == "selected_supporting":
                if promote is None or f["rank"] < promote["rank"]:
                    promote = f
        if promote is not None:
            promote["decision"] = "selected_hero"
            promote["reasons"].append("vlm_tie_broken_by_rank")

    hero: dict | None = None
    supporting_sis: list[int] = []
    selected_count = 0
    rejected_count = 0
    for f in ordered:
        if f["decision"] == "selected_hero":
            hero = {
                "scene_index": f["scene_index"],
                "frame_file": f["frame_file"],
                "midpoint_seconds": f["midpoint_seconds"],
            }
            selected_count += 1
        elif f["decision"] == "selected_supporting":
            supporting_sis.append(f["scene_index"])
            selected_count += 1
        elif f["decision"] == "vlm_rejected":
            rejected_count += 1

    out_chapter = {
        "chapter_index": shortlist_chapter["chapter_index"],
        "start_seconds": shortlist_chapter["start_seconds"],
        "end_seconds": shortlist_chapter["end_seconds"],
        "hero": hero,
        "supporting_scene_indices": supporting_sis,
        "frame_count": len(shortlist_chapter["frames"]),
        "verified_count": len(ordered),
        "selected_count": selected_count,
        "rejected_count": rejected_count,
        "frames": ordered,
    }
    return out_chapter, {
        "verified": len(ordered),
        "selected": selected_count,
        "rejected": rejected_count,
    }


# ---- core compute --------------------------------------------------------

def _compute(
    paths: JobPaths,
    shortlist_raw: dict,
    chapters_raw: dict,
    windows_raw: dict,
    provider: str,
    model_id: str | None,
    caption_mode: str,
    fingerprints: dict[str, str],
    verify_fn,  # callable(frame, chapter_text, window_text, image_bytes) -> dict
) -> dict:
    chapters_in = _validate_shortlist(shortlist_raw)
    chapter_text_by_index = _index_chapter_text(chapters_raw)
    window_text_by_scene = _index_window_text(windows_raw)

    video = paths.analysis_mp4.name if paths.analysis_mp4.exists() else None

    out_chapters: list[dict] = []
    total_verified = 0
    total_selected = 0
    total_rejected = 0
    total_frames_in_shortlist = 0

    for ch in chapters_in:
        total_frames_in_shortlist += len(ch["frames"])
        ch_idx = ch["chapter_index"]
        if ch_idx not in chapter_text_by_index:
            raise RuntimeError(
                f"chapter_candidates.json has no chapter with index {ch_idx} "
                f"(required by frame_shortlist.json)"
            )
        chapter_text = _truncate(
            chapter_text_by_index[ch_idx], CHAPTER_CONTEXT_CHARS
        )

        verifications_by_scene: dict[int, dict] = {}
        for fr in ch["frames"]:
            if fr["decision"] not in _SHORTLIST_KEEP_DECISIONS:
                continue
            frame_file = fr["frame_file"]
            image_path = paths.candidate_frames_dir / frame_file
            if not image_path.is_file():
                raise RuntimeError(
                    f"candidate frame image missing: {image_path}"
                )
            if fr["scene_index"] not in window_text_by_scene:
                raise RuntimeError(
                    f"frame_windows.json has no frame with scene_index "
                    f"{fr['scene_index']} (required by frame_shortlist.json)"
                )
            window_text_full = window_text_by_scene[fr["scene_index"]]
            window_text = _truncate(window_text_full, WINDOW_CONTEXT_CHARS)
            image_bytes = image_path.read_bytes()
            v = verify_fn(fr, chapter_text, window_text, image_bytes)
            # tag with per-verification metadata so _apply_policy can emit
            # provider/model on the artifact without another lookup
            v = dict(v)
            v["_provider"] = provider
            v["_model"] = model_id
            v["_window_text"] = window_text
            verifications_by_scene[fr["scene_index"]] = v

        out_chapter, counters = _apply_policy(ch, verifications_by_scene)
        out_chapters.append(out_chapter)
        total_verified += counters["verified"]
        total_selected += counters["selected"]
        total_rejected += counters["rejected"]

    return {
        "video": video,
        "shortlist_source": paths.frame_shortlist_json.name,
        "chapters_source": paths.chapter_candidates_json.name,
        "windows_source": paths.frame_windows_json.name,
        "frames_dir": paths.candidate_frames_dir.name,
        "provider": provider,
        "model": model_id,
        "provider_version": VLM_PROVIDER_VERSION,
        "policy_version": VLM_POLICY_VERSION,
        "caption_mode": caption_mode,
        "context": {
            "chapter_context_chars": CHAPTER_CONTEXT_CHARS,
            "window_context_chars": WINDOW_CONTEXT_CHARS,
        },
        "input_fingerprints": fingerprints,
        "chapter_count": len(out_chapters),
        "frame_count": total_frames_in_shortlist,
        "verified_count": total_verified,
        "selected_count": total_selected,
        "rejected_count": total_rejected,
        "chapters": out_chapters,
    }


# ---- skip contract -------------------------------------------------------

_TOP_LEVEL_STABLE_KEYS = (
    "shortlist_source",
    "chapters_source",
    "windows_source",
    "frames_dir",
    "provider",
    "model",
    "provider_version",
    "policy_version",
    "caption_mode",
    "context",
    "input_fingerprints",
)


_STORED_CHAPTER_FIELDS = (
    "chapter_index",
    "start_seconds",
    "end_seconds",
    "hero",
    "supporting_scene_indices",
    "frame_count",
    "verified_count",
    "selected_count",
    "rejected_count",
    "frames",
)
_STORED_FRAME_FIELDS = (
    "rank",
    "scene_index",
    "frame_file",
    "midpoint_seconds",
    "composite_score",
    "clip_similarity",
    "text_novelty",
    "window_text",
    "shortlist_decision",
    "verification",
    "decision",
    "reasons",
)
_SELECTED_DECISION_VALUES = (
    "selected_hero",
    "selected_supporting",
    "vlm_rejected",
)
_VERIFICATION_FIELDS = (
    "provider",
    "model",
    "relevance",
    "confidence",
    "caption",
)


def _stored_schema_ok(data: dict) -> bool:
    """Return True iff `data` is a well-formed selected_frames.json body.

    This is a structural and closed-vocabulary check only — it does not
    cross-check against the current shortlist.
    """
    for key in _TOP_LEVEL_STABLE_KEYS + (
        "chapter_count",
        "frame_count",
        "verified_count",
        "selected_count",
        "rejected_count",
        "chapters",
    ):
        if key not in data:
            return False
    for key in ("chapter_count", "frame_count", "verified_count",
                "selected_count", "rejected_count"):
        if not _is_int(data[key]) or data[key] < 0:
            return False
    chapters = data["chapters"]
    if not isinstance(chapters, list):
        return False
    if data["chapter_count"] != len(chapters):
        return False

    top_provider = data.get("provider")
    top_model = data.get("model")

    sum_verified = 0
    sum_selected = 0
    sum_rejected = 0
    sum_frame_count = 0
    for ch in chapters:
        if not isinstance(ch, dict):
            return False
        for field in _STORED_CHAPTER_FIELDS:
            if field not in ch:
                return False
        if not _is_int(ch["chapter_index"]):
            return False
        if not _is_number(ch["start_seconds"]) or not _is_number(
            ch["end_seconds"]
        ):
            return False
        for field in ("frame_count", "verified_count", "selected_count",
                      "rejected_count"):
            if not _is_int(ch[field]) or ch[field] < 0:
                return False
        hero = ch["hero"]
        if hero is not None:
            if not isinstance(hero, dict):
                return False
            for field in ("scene_index", "frame_file", "midpoint_seconds"):
                if field not in hero:
                    return False
            if not _is_int(hero["scene_index"]):
                return False
            if not isinstance(hero["frame_file"], str):
                return False
            if not _is_number(hero["midpoint_seconds"]):
                return False
        ssi = ch["supporting_scene_indices"]
        if not isinstance(ssi, list) or not all(_is_int(x) for x in ssi):
            return False
        frames = ch["frames"]
        if not isinstance(frames, list):
            return False
        ch_verified = 0
        ch_selected = 0
        ch_rejected = 0
        for fr in frames:
            if not isinstance(fr, dict):
                return False
            for field in _STORED_FRAME_FIELDS:
                if field not in fr:
                    return False
            if not _is_int(fr["rank"]):
                return False
            if not _is_int(fr["scene_index"]):
                return False
            if not isinstance(fr["frame_file"], str) or not fr["frame_file"]:
                return False
            if not _is_number(fr["midpoint_seconds"]):
                return False
            if not _is_number(fr["composite_score"]):
                return False
            if fr["clip_similarity"] is not None and not _is_number(
                fr["clip_similarity"]
            ):
                return False
            if fr["text_novelty"] is not None and not _is_number(
                fr["text_novelty"]
            ):
                return False
            if not isinstance(fr["window_text"], str):
                return False
            if fr["shortlist_decision"] not in _SHORTLIST_KEEP_DECISIONS:
                return False
            if fr["decision"] not in _SELECTED_DECISION_VALUES:
                return False
            if not isinstance(fr["reasons"], list) or not all(
                isinstance(r, str) for r in fr["reasons"]
            ):
                return False
            v = fr["verification"]
            if not isinstance(v, dict):
                return False
            for field in _VERIFICATION_FIELDS:
                if field not in v:
                    return False
            if v["relevance"] not in _RELEVANCE_VALUES:
                return False
            if not _is_number(v["confidence"]):
                return False
            if v["caption"] is not None and not isinstance(v["caption"], str):
                return False
            if v["provider"] != top_provider:
                return False
            if v["model"] != top_model:
                return False
            ch_verified += 1
            if fr["decision"] == "selected_hero":
                ch_selected += 1
            elif fr["decision"] == "selected_supporting":
                ch_selected += 1
            elif fr["decision"] == "vlm_rejected":
                ch_rejected += 1
        if ch["verified_count"] != ch_verified:
            return False
        if ch["selected_count"] != ch_selected:
            return False
        if ch["rejected_count"] != ch_rejected:
            return False
        # At most one frame may be labeled selected_hero per chapter.
        heroes = [f for f in frames if f["decision"] == "selected_hero"]
        if len(heroes) > 1:
            return False
        # hero/supporting_scene_indices must reflect the frames.
        if heroes:
            h = heroes[0]
            if hero is None:
                return False
            if hero["scene_index"] != h["scene_index"]:
                return False
            if hero["frame_file"] != h["frame_file"]:
                return False
            if hero["midpoint_seconds"] != h["midpoint_seconds"]:
                return False
        else:
            if hero is not None:
                return False
        computed_ssi = [
            f["scene_index"] for f in frames
            if f["decision"] == "selected_supporting"
        ]
        if list(ssi) != computed_ssi:
            return False
        sum_verified += ch_verified
        sum_selected += ch_selected
        sum_rejected += ch_rejected
        sum_frame_count += ch["frame_count"]
    if data["frame_count"] != sum_frame_count:
        return False
    if data["verified_count"] != sum_verified:
        return False
    if data["selected_count"] != sum_selected:
        return False
    if data["rejected_count"] != sum_rejected:
        return False
    return True


def _stored_aligns_with_shortlist(
    data: dict,
    shortlist_chapters: list[dict],
    window_text_by_scene: dict[int, str],
) -> bool:
    """Return True iff `data.chapters` matches the current shortlist's
    kept-frame set, ordered by shortlist rank per chapter, with every
    deterministic copied field matching the current inputs.

    The skip path for `--provider gemini` does not re-query the model,
    so every field that `_compute()` copies verbatim from the shortlist
    and the window artifact must be validated here — otherwise a
    manually corrupted stored field can masquerade as a valid skip.
    """
    stored_chapters = data["chapters"]
    if len(stored_chapters) != len(shortlist_chapters):
        return False
    for s_ch, sl_ch in zip(stored_chapters, shortlist_chapters):
        if s_ch["chapter_index"] != sl_ch["chapter_index"]:
            return False
        if s_ch["start_seconds"] != sl_ch["start_seconds"]:
            return False
        if s_ch["end_seconds"] != sl_ch["end_seconds"]:
            return False
        if s_ch["frame_count"] != len(sl_ch["frames"]):
            return False
        kept = [
            fr for fr in sl_ch["frames"]
            if fr["decision"] in _SHORTLIST_KEEP_DECISIONS
        ]
        stored_frames = s_ch["frames"]
        if len(stored_frames) != len(kept):
            return False
        for sf, kf in zip(stored_frames, kept):
            if sf["rank"] != kf["rank"]:
                return False
            if sf["scene_index"] != kf["scene_index"]:
                return False
            if sf["frame_file"] != kf["frame_file"]:
                return False
            if sf["midpoint_seconds"] != kf["midpoint_seconds"]:
                return False
            if sf["composite_score"] != kf["composite_score"]:
                return False
            if sf["clip_similarity"] != kf["clip_similarity"]:
                return False
            if sf["text_novelty"] != kf["text_novelty"]:
                return False
            if sf["shortlist_decision"] != kf["decision"]:
                return False
            # Window text must match the truncated current window for
            # this scene; missing window records always invalidate skip.
            if kf["scene_index"] not in window_text_by_scene:
                return False
            expected_wt = _truncate(
                window_text_by_scene[kf["scene_index"]], WINDOW_CONTEXT_CHARS
            )
            if sf["window_text"] != expected_wt:
                return False
    return True


def _stored_matches(
    paths: JobPaths,
    provider: str,
    model_id: str | None,
    caption_mode: str,
    fingerprints: dict[str, str],
    shortlist_chapters: list[dict],
    window_text_by_scene: dict[int, str],
    fresh_mock: dict | None,
) -> bool:
    if not paths.selected_frames_json.exists():
        return False
    try:
        with open(paths.selected_frames_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    want_top = {
        "shortlist_source": paths.frame_shortlist_json.name,
        "chapters_source": paths.chapter_candidates_json.name,
        "windows_source": paths.frame_windows_json.name,
        "frames_dir": paths.candidate_frames_dir.name,
        "provider": provider,
        "model": model_id,
        "provider_version": VLM_PROVIDER_VERSION,
        "policy_version": VLM_POLICY_VERSION,
        "caption_mode": caption_mode,
        "context": {
            "chapter_context_chars": CHAPTER_CONTEXT_CHARS,
            "window_context_chars": WINDOW_CONTEXT_CHARS,
        },
        "input_fingerprints": fingerprints,
    }
    for key in _TOP_LEVEL_STABLE_KEYS:
        if data.get(key) != want_top[key]:
            return False
    if not _stored_schema_ok(data):
        return False
    if not _stored_aligns_with_shortlist(
        data, shortlist_chapters, window_text_by_scene
    ):
        return False
    if provider == "mock":
        # Mock is deterministic and has no network; compare byte-identically
        # against a fresh recomputation when one has been prepared.
        if fresh_mock is None:
            return False
        return _fingerprint(data) == _fingerprint(fresh_mock)
    return True


# ---- provider resolution -------------------------------------------------

def _resolve_gemini_model() -> str:
    env_model = os.environ.get("GEMINI_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()
    return GEMINI_DEFAULT_MODEL


def _resolve_gemini_base_url() -> str:
    env_url = os.environ.get("GEMINI_BASE_URL")
    if env_url and env_url.strip():
        return env_url.strip()
    return GEMINI_DEFAULT_BASE_URL


# ---- entry point ---------------------------------------------------------

def run(
    paths: JobPaths,
    provider: str = VLM_DEFAULT_PROVIDER,
    force: bool = False,
) -> dict:
    if provider not in ("mock", "gemini"):
        raise RuntimeError(f"unsupported VLM provider: {provider!r}")

    # Load and fingerprint the three JSON inputs up front so the skip
    # contract can evaluate without any network or image work.
    shortlist_raw = _load_json_raw(
        paths.frame_shortlist_json, "frame_shortlist.json"
    )
    chapters_raw = _load_json_raw(
        paths.chapter_candidates_json, "chapter_candidates.json"
    )
    windows_raw = _load_json_raw(
        paths.frame_windows_json, "frame_windows.json"
    )
    fingerprints = {
        "frame_shortlist.json": _fingerprint(shortlist_raw),
        "chapter_candidates.json": _fingerprint(chapters_raw),
        "frame_windows.json": _fingerprint(windows_raw),
    }

    # Validate shortlist up front so malformed input never masquerades as a
    # skip, and so the skip path has access to the kept-frame set.
    shortlist_chapters = _validate_shortlist(shortlist_raw)

    # Build the window lookup up front so the skip path can validate
    # stored `window_text` against the current inputs without re-running
    # the VLM. Errors here are recoverable into the recompute path,
    # where `_compute()` will raise the same message cleanly.
    try:
        window_text_by_scene = _index_window_text(windows_raw)
    except RuntimeError:
        window_text_by_scene = {}

    if provider == "mock":
        model_id: str | None = None
        caption_mode = "off"
    else:
        model_id = _resolve_gemini_model()
        caption_mode = "short"

    # Mock is deterministic and no-network, so for a mock skip we can
    # recompute the artifact and compare byte-for-byte. If the recompute
    # itself errors (e.g. missing image), skip fails and the error path
    # below will surface the same error during the real compute.
    fresh_mock: dict | None = None
    if (
        provider == "mock"
        and not force
        and paths.selected_frames_json.exists()
    ):
        try:
            fresh_mock = _compute(
                paths,
                shortlist_raw,
                chapters_raw,
                windows_raw,
                provider="mock",
                model_id=None,
                caption_mode="off",
                fingerprints=fingerprints,
                verify_fn=_verify_mock,
            )
        except Exception:
            fresh_mock = None

    if not force and _stored_matches(
        paths,
        provider,
        model_id,
        caption_mode,
        fingerprints,
        shortlist_chapters,
        window_text_by_scene,
        fresh_mock,
    ):
        with open(paths.selected_frames_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        update_stage(
            paths,
            "verify",
            COMPLETED,
            extra={
                "provider": data.get("provider"),
                "model": data.get("model"),
                "chapter_count": data.get("chapter_count"),
                "frame_count": data.get("frame_count"),
                "verified_count": data.get("verified_count"),
                "selected_count": data.get("selected_count"),
                "rejected_count": data.get("rejected_count"),
                "provider_version": VLM_PROVIDER_VERSION,
                "policy_version": VLM_POLICY_VERSION,
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "verify", RUNNING)
    tmp = paths.selected_frames_json.with_suffix(".json.tmp")
    try:
        if force and paths.selected_frames_json.exists():
            paths.selected_frames_json.unlink()

        if provider == "mock":
            verify_fn = _verify_mock
        else:  # gemini
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key or not api_key.strip():
                raise RuntimeError("GEMINI_API_KEY is not set")
            base_url = _resolve_gemini_base_url()
            api_key_clean = api_key.strip()

            def verify_fn(frame, chapter_text, window_text, image_bytes):
                return _verify_gemini(
                    frame,
                    chapter_text,
                    window_text,
                    image_bytes,
                    model=model_id,
                    base_url=base_url,
                    api_key=api_key_clean,
                )

        fresh = _compute(
            paths,
            shortlist_raw,
            chapters_raw,
            windows_raw,
            provider=provider,
            model_id=model_id,
            caption_mode=caption_mode,
            fingerprints=fingerprints,
            verify_fn=verify_fn,
        )

        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(fresh, f, indent=2, sort_keys=True, ensure_ascii=False)
        tmp.replace(paths.selected_frames_json)

        update_stage(
            paths,
            "verify",
            COMPLETED,
            extra={
                "provider": fresh["provider"],
                "model": fresh["model"],
                "chapter_count": fresh["chapter_count"],
                "frame_count": fresh["frame_count"],
                "verified_count": fresh["verified_count"],
                "selected_count": fresh["selected_count"],
                "rejected_count": fresh["rejected_count"],
                "provider_version": VLM_PROVIDER_VERSION,
                "policy_version": VLM_POLICY_VERSION,
            },
        )
        return fresh
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(paths, "verify", FAILED, error=f"{type(e).__name__}: {e}")
        raise
