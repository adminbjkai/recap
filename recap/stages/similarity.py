"""Phase 3 slice: OpenCLIP frame-to-transcript-window similarity scoring.

Reads `scenes.json`, `frame_windows.json`, and the JPEGs in
`candidate_frames/`, and writes `frame_similarities.json`. For each
candidate frame that has non-empty `window_text`, computes the cosine
similarity between the OpenCLIP image embedding of the frame and the
OpenCLIP text embedding of the window text. Frames with empty
`window_text` record `clip_similarity: null`.

The model (`ViT-B-32` / `openai`), device (`cpu`), and image
preprocessing (the model's shipped transforms) are fixed code-level
constants. They are not exposed as CLI flags, env vars, or config.

This stage is marking-only: it does not threshold, rank, select, keep,
reject, or mutate any frame. It performs no chapter proposal and no
report changes. It is opt-in via `recap similarity` and is not invoked
by `recap run`.

Determinism: on a given machine with the same pinned model weights,
`ViT-B-32/openai` with `model.eval()` under `torch.no_grad()` produces
identical image and text embeddings for identical inputs; rerun cosine
similarities are stable to within ~1e-5 across invocations.

Skipped if `frame_similarities.json` already matches the current
`scenes.json` and `frame_windows.json` plus the pinned model/pretrained/
device/image_preprocess (unless `force=True`).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


MODEL = "ViT-B-32"
PRETRAINED = "openai"
DEVICE = "cpu"
IMAGE_PREPROCESS = "open_clip.default"


def _load_json(path: Path, label: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path}")
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return data


def _load_scenes(paths: JobPaths) -> tuple[dict, list[dict]]:
    data = _load_json(paths.scenes_json, "scenes.json")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError("scenes.json has no scenes")
    for s in scenes:
        if not isinstance(s, dict):
            raise RuntimeError("scenes.json has a non-object scene entry")
        if s.get("index") is None:
            raise RuntimeError("scenes.json scene is missing 'index'")
        if not s.get("frame_file"):
            raise RuntimeError(
                f"scenes.json scene {s.get('index')!r} has no frame_file"
            )
        if s.get("midpoint_seconds") is None:
            raise RuntimeError(
                f"scenes.json scene {s.get('index')!r} has no midpoint_seconds"
            )
    return data, scenes


def _load_windows(paths: JobPaths) -> tuple[dict, list[dict]]:
    data = _load_json(paths.frame_windows_json, "frame_windows.json")
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        raise RuntimeError("frame_windows.json has no frames")
    for f in frames:
        if not isinstance(f, dict):
            raise RuntimeError("frame_windows.json has a non-object frame entry")
        if f.get("scene_index") is None:
            raise RuntimeError("frame_windows.json frame is missing 'scene_index'")
        if not f.get("frame_file"):
            raise RuntimeError(
                f"frame_windows.json frame {f.get('scene_index')!r} has no frame_file"
            )
        if f.get("midpoint_seconds") is None:
            raise RuntimeError(
                f"frame_windows.json frame {f.get('scene_index')!r} has no midpoint_seconds"
            )
        if "window_start" not in f:
            raise RuntimeError(
                f"frame_windows.json frame {f.get('scene_index')!r} has no window_start"
            )
        if "window_end" not in f:
            raise RuntimeError(
                f"frame_windows.json frame {f.get('scene_index')!r} has no window_end"
            )
        if "window_text" not in f:
            raise RuntimeError(
                f"frame_windows.json frame {f.get('scene_index')!r} has no window_text"
            )
        if not isinstance(f["window_text"], str):
            raise RuntimeError(
                f"frame_windows.json frame {f.get('scene_index')!r} has a non-string window_text"
            )
    return data, frames


def _index_windows(frames: list[dict]) -> dict[int, dict]:
    by_index: dict[int, dict] = {}
    for f in frames:
        idx = f["scene_index"]
        if idx in by_index:
            raise RuntimeError(
                f"frame_windows.json has duplicate scene_index {idx!r}"
            )
        by_index[idx] = f
    return by_index


def _pair_scenes_with_windows(
    scenes: list[dict], windows_by_index: dict[int, dict]
) -> list[tuple[dict, dict]]:
    paired: list[tuple[dict, dict]] = []
    for s in scenes:
        w = windows_by_index.get(s["index"])
        if w is None:
            raise RuntimeError(
                f"frame_windows.json has no entry for scene_index {s['index']!r}"
            )
        if w.get("frame_file") != s.get("frame_file"):
            raise RuntimeError(
                "scenes.json and frame_windows.json disagree on frame_file for "
                f"scene_index {s['index']!r}: "
                f"{s.get('frame_file')!r} vs {w.get('frame_file')!r}"
            )
        if w.get("midpoint_seconds") != s.get("midpoint_seconds"):
            raise RuntimeError(
                "scenes.json and frame_windows.json disagree on midpoint_seconds "
                f"for scene_index {s['index']!r}: "
                f"{s.get('midpoint_seconds')!r} vs {w.get('midpoint_seconds')!r}"
            )
        paired.append((s, w))
    return paired


def _validate_frame_files(paths: JobPaths, scenes: list[dict]) -> None:
    if not paths.candidate_frames_dir.is_dir():
        raise FileNotFoundError(
            "candidate_frames/ not found; run `recap scenes` first"
        )
    missing: list[str] = []
    for s in scenes:
        name = s["frame_file"]
        if not (paths.candidate_frames_dir / name).is_file():
            missing.append(name)
    if missing:
        raise RuntimeError(
            "scenes.json and candidate_frames/ disagree; missing frame file(s): "
            + ", ".join(missing)
        )


def _compute(
    paths: JobPaths,
    scenes_data: dict,
    paired: list[tuple[dict, dict]],
) -> dict:
    import open_clip
    import torch
    from PIL import Image

    # `ViT-B-32 / openai` was trained with QuickGELU activations. open_clip's
    # default model config uses standard GELU, which silently produces
    # off-spec embeddings for this pretrained tag. Pinning the activation to
    # QuickGELU is a correctness fix for this specific (model, pretrained)
    # pair, not a tunable knob.
    model, _, preprocess = open_clip.create_model_and_transforms(
        MODEL, pretrained=PRETRAINED, device=DEVICE, force_quick_gelu=True
    )
    tokenizer = open_clip.get_tokenizer(MODEL)
    model.eval()

    entries: list[dict] = []
    frames_with_window_text_count = 0
    frames_scored_count = 0

    with torch.no_grad():
        for scene, window in paired:
            window_text = window.get("window_text", "") or ""
            has_window_text = bool(window_text)
            if has_window_text:
                frames_with_window_text_count += 1

            clip_similarity: float | None = None
            if has_window_text:
                frame_path = paths.candidate_frames_dir / scene["frame_file"]
                with Image.open(frame_path) as img:
                    image_tensor = preprocess(img.convert("RGB")).unsqueeze(0).to(DEVICE)
                image_features = model.encode_image(image_tensor)
                image_features = image_features / image_features.norm(
                    dim=-1, keepdim=True
                )

                tokens = tokenizer([window_text]).to(DEVICE)
                text_features = model.encode_text(tokens)
                text_features = text_features / text_features.norm(
                    dim=-1, keepdim=True
                )

                clip_similarity = float((image_features * text_features).sum(dim=-1).item())
                frames_scored_count += 1

            entries.append(
                {
                    "scene_index": scene["index"],
                    "frame_file": scene["frame_file"],
                    "midpoint_seconds": window["midpoint_seconds"],
                    "window_start": window.get("window_start"),
                    "window_end": window.get("window_end"),
                    "window_text": window_text,
                    "has_window_text": has_window_text,
                    "clip_similarity": clip_similarity,
                }
            )

    return {
        "video": scenes_data.get("video"),
        "frames_dir": paths.candidate_frames_dir.name,
        "windows_source": paths.frame_windows_json.name,
        "scenes_source": paths.scenes_json.name,
        "model": MODEL,
        "pretrained": PRETRAINED,
        "device": DEVICE,
        "image_preprocess": IMAGE_PREPROCESS,
        "frame_count": len(entries),
        "frames_with_window_text_count": frames_with_window_text_count,
        "frames_scored_count": frames_scored_count,
        "frames": entries,
    }


def _outputs_match(
    paths: JobPaths, paired: list[tuple[dict, dict]]
) -> bool:
    if not paths.frame_similarities_json.exists():
        return False
    try:
        with open(paths.frame_similarities_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("model") != MODEL:
        return False
    if data.get("pretrained") != PRETRAINED:
        return False
    if data.get("device") != DEVICE:
        return False
    if data.get("image_preprocess") != IMAGE_PREPROCESS:
        return False
    if data.get("windows_source") != paths.frame_windows_json.name:
        return False
    if data.get("scenes_source") != paths.scenes_json.name:
        return False
    entries = data.get("frames")
    if not isinstance(entries, list) or len(entries) != len(paired):
        return False
    for entry, (scene, window) in zip(entries, paired):
        if entry.get("scene_index") != scene.get("index"):
            return False
        if entry.get("frame_file") != scene.get("frame_file"):
            return False
        if entry.get("midpoint_seconds") != scene.get("midpoint_seconds"):
            return False
        if entry.get("window_start") != window.get("window_start"):
            return False
        if entry.get("window_end") != window.get("window_end"):
            return False
        if entry.get("window_text") != window.get("window_text"):
            return False
        expected_has_text = bool(window.get("window_text"))
        if entry.get("has_window_text") != expected_has_text:
            return False
    return True


def run(paths: JobPaths, force: bool = False) -> dict:
    scenes_data, scenes = _load_scenes(paths)
    # Validate frame_windows.json and candidate_frames/ on every invocation so
    # a stale frame_similarities.json cannot short-circuit past a missing or
    # malformed input.
    _, windows = _load_windows(paths)
    windows_by_index = _index_windows(windows)
    paired = _pair_scenes_with_windows(scenes, windows_by_index)
    _validate_frame_files(paths, scenes)

    if not force and _outputs_match(paths, paired):
        with open(paths.frame_similarities_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "similarity",
            COMPLETED,
            extra={
                "frame_count": data.get("frame_count", len(data.get("frames", []))),
                "frames_with_window_text_count": data.get(
                    "frames_with_window_text_count", 0
                ),
                "frames_scored_count": data.get("frames_scored_count", 0),
                "model": MODEL,
                "pretrained": PRETRAINED,
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "similarity", RUNNING)
    try:
        if force and paths.frame_similarities_json.exists():
            paths.frame_similarities_json.unlink()

        data = _compute(paths, scenes_data, paired)

        tmp = paths.frame_similarities_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(paths.frame_similarities_json)

        update_stage(
            paths,
            "similarity",
            COMPLETED,
            extra={
                "frame_count": data["frame_count"],
                "frames_with_window_text_count": data["frames_with_window_text_count"],
                "frames_scored_count": data["frames_scored_count"],
                "model": MODEL,
                "pretrained": PRETRAINED,
            },
        )
        return data
    except Exception as e:
        # Do not leave a partial frame_similarities.json behind.
        tmp = paths.frame_similarities_json.with_suffix(".json.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(paths, "similarity", FAILED, error=f"{type(e).__name__}: {e}")
        raise
