"""Optional, uncalibrated camera-view suggestions for locally available video.

The default CLIP model may download on first use. Nothing is downloaded merely
by importing this module. Suggestions need visual review: seven sampled frames
cannot establish that a whole clip is one camera view or that all players are
visible. This module does not identify scrum boundaries or referee commands.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile


VIEWS = ("aerial", "side", "unknown")
PROMPTS = {
    "aerial": (
        "An overhead top-down camera view of rugby players forming a scrum.",
        "An aerial camera looking down on a rugby scrum from above.",
        "A rugby scrum seen from a high camera directly over the players.",
    ),
    "side": (
        "A sideline camera view of a rugby scrum showing players from the side.",
        "A rugby scrum seen at ground level from the side of the pitch.",
        "A broadcast camera looking across the pitch at a rugby scrum.",
    ),
    "unknown": (
        "A close-up of a rugby referee, a player's face, or a spectator.",
        "A rugby broadcast showing a crowd, graphics, or a view without a scrum.",
        "An unclear rugby camera view with no identifiable scrum angle.",
    ),
}


class ViewClassificationError(ValueError):
    """Inputs, local media, or optional model dependencies are unavailable."""


def _number(value, name):
    if isinstance(value, bool):
        raise ViewClassificationError(f"{name} must be a finite number")
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise ViewClassificationError(f"{name} must be a finite number") from exc
    if not math.isfinite(value):
        raise ViewClassificationError(f"{name} must be a finite number")
    return value


def _unit(value, name):
    value = _number(value, name)
    if not 0 <= value <= 1:
        raise ViewClassificationError(f"{name} must be in [0, 1]")
    return value


def prediction_from_scores(scores, min_confidence=0.65, min_margin=0.15):
    """Threshold three CLIP class logits; returned probabilities are uncalibrated.

    ``scores`` maps aerial/side/unknown to mean CLIP prompt logits. The highest
    probability must meet both thresholds; otherwise its suggested view is
    unknown. An unknown winning class remains unknown regardless of confidence.
    """
    confidence_threshold = _unit(min_confidence, "min_confidence")
    margin_threshold = _unit(min_margin, "min_margin")
    if not isinstance(scores, dict) or set(scores) != set(VIEWS):
        raise ViewClassificationError("Scores must contain aerial, side and unknown")
    values = {name: _number(scores[name], f"{name} score") for name in VIEWS}
    highest = max(values.values())
    exponentials = {name: math.exp(value - highest) for name, value in values.items()}
    total = sum(exponentials.values())
    probabilities = {name: value / total for name, value in exponentials.items()}
    ranking = sorted(probabilities, key=lambda name: probabilities[name], reverse=True)
    predicted = ranking[0]
    confidence = probabilities[predicted]
    margin = confidence - probabilities[ranking[1]]
    suggested = predicted if confidence >= confidence_threshold and margin >= margin_threshold else "unknown"
    return {
        "view": suggested,
        "predicted_class": predicted,
        "confidence": confidence,
        "margin": margin,
        "class_probabilities": probabilities,
    }


def aggregate_views(predictions, min_fraction=0.6):
    """Combine thresholded per-frame suggestions without hiding observed cuts.

    Any confident aerial and side samples make the suggestion mixed, even if
    neither is the majority. With only one observed view, at least min_fraction
    of *all* samples must have that view. Unknown frames remain in the
    denominator. No frames produce unknown. This cannot detect unsampled cuts.
    """
    minimum = _unit(min_fraction, "min_fraction")
    if minimum == 0:
        raise ViewClassificationError("min_fraction must be greater than zero")
    if not isinstance(predictions, (list, tuple)):
        raise ViewClassificationError("Predictions must be a list of frame suggestions")
    counts = Counter()
    for prediction in predictions:
        if not isinstance(prediction, dict) or prediction.get("view") not in VIEWS:
            raise ViewClassificationError("Each frame view must be aerial, side or unknown")
        _unit(prediction.get("confidence"), "frame confidence")
        _unit(prediction.get("margin"), "frame margin")
        counts[prediction["view"]] += 1
    if counts["aerial"] and counts["side"]:
        return "mixed"
    for view in ("aerial", "side"):
        if predictions and counts[view] / len(predictions) >= minimum:
            return view
    return "unknown"


def _media_interval(video, start_s, end_s):
    video = Path(video)
    start, end = _number(start_s, "start_s"), _number(end_s, "end_s")
    if not 0 <= start < end:
        raise ViewClassificationError("Interval requires 0 <= start_s < end_s")
    if not video.is_file():
        raise ViewClassificationError(f"Video file is missing: {video}")
    if not shutil.which("ffprobe"):
        raise ViewClassificationError("FFprobe is required; install FFmpeg first")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(video.resolve())],
            capture_output=True, text=True, check=True, timeout=30,
        )
        metadata = json.loads(result.stdout)
        if not metadata.get("streams"):
            raise ViewClassificationError("Input has no video stream")
        duration = _number(metadata["format"]["duration"], "video duration")
        if end > duration + 0.001:
            raise ViewClassificationError(f"Interval ends after video duration ({duration:.3f}s)")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError) as exc:
        raise ViewClassificationError(f"Cannot inspect local video: {exc}") from exc
    return video.resolve(), start, end


def extract_sample_frames(video, start_s, end_s, directory, samples=7):
    """Decode evenly spaced interior frames; return their times and PNG paths.

    The caller owns directory lifetime. Both FFprobe and FFmpeg are restricted
    to file/pipe protocols, so a local playlist cannot trigger network fetches.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 60:
        raise ViewClassificationError("samples must be an integer from 1 to 60")
    video, start, end = _media_interval(video, start_s, end_s)
    if not shutil.which("ffmpeg"):
        raise ViewClassificationError("FFmpeg is required to sample camera views")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sampled = []
    for index in range(samples):
        time_s = start + (end - start) * (index + 0.5) / samples
        image_path = directory / f"view_{index:03d}.png"
        if image_path.exists():
            raise ViewClassificationError(f"Refusing to replace existing sampled image: {image_path}")
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-n", "-protocol_whitelist", "file,pipe",
                 "-ss", f"{time_s:.9f}", "-i", str(video), "-map", "0:v:0", "-frames:v", "1",
                 "-vf", "scale=w='min(640,iw)':h=-2", "-threads", "1", str(image_path)],
                capture_output=True, text=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ViewClassificationError(f"Cannot sample local video at {time_s:.3f}s: {exc}") from exc
        if not image_path.is_file() or image_path.stat().st_size == 0:
            raise ViewClassificationError(f"No frame decoded at {time_s:.3f}s")
        sampled.append({"time_s": time_s, "path": image_path})
    return sampled


@lru_cache(maxsize=1)
def _load_clip(model_name, device):
    try:
        from transformers import CLIPModel, CLIPProcessor
        import torch  # noqa: F401 - checks the optional runtime before loading weights
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise ViewClassificationError(
            "Camera suggestions require optional torch, transformers and Pillow dependencies"
        ) from exc
    processor = CLIPProcessor.from_pretrained(model_name)
    model = CLIPModel.from_pretrained(model_name).to(device)
    model.eval()
    return processor, model


def classify_view(video: Path, start_s: float, end_s: float,
                  model_name="openai/clip-vit-base-patch32", device="cpu",
                  min_confidence=0.65, min_margin=0.15):
    """Suggest aerial/side/mixed/unknown from seven frames using optional CLIP.

    First model use can download public weights. No accuracy is established on
    rugby scrum footage; softmax scores are not calibrated probabilities of a
    correct camera label. Treat every result as a draft, including high scores.
    """
    _unit(min_confidence, "min_confidence")
    _unit(min_margin, "min_margin")
    # Inspect input before any optional model import/download.
    video, start, end = _media_interval(video, start_s, end_s)
    try:
        import torch
        from PIL import Image
    except ImportError as exc:
        raise ViewClassificationError(
            "Camera suggestions require optional torch, transformers and Pillow dependencies"
        ) from exc
    processor, model = _load_clip(str(model_name), str(device))
    prompts = [prompt for name in VIEWS for prompt in PROMPTS[name]]
    predictions = []
    with tempfile.TemporaryDirectory(prefix="scrum-views-") as temporary:
        samples = extract_sample_frames(video, start, end, Path(temporary))
        images = []
        try:
            for sample in samples:
                with Image.open(sample["path"]) as image:
                    images.append(image.convert("RGB"))
            inputs = processor(text=prompts, images=images, return_tensors="pt", padding=True)
            inputs = {name: tensor.to(device) for name, tensor in inputs.items()}
            with torch.inference_mode():
                logits = model(**inputs).logits_per_image.detach().float().cpu().tolist()
            for sample, frame_logits in zip(samples, logits):
                group_scores, offset = {}, 0
                for name in VIEWS:
                    size = len(PROMPTS[name])
                    group_scores[name] = sum(frame_logits[offset:offset + size]) / size
                    offset += size
                predictions.append({
                    "time_s": sample["time_s"],
                    **prediction_from_scores(group_scores, min_confidence, min_margin),
                })
        finally:
            for image in images:
                image.close()
    return {
        "camera_view": aggregate_views(predictions),
        "status": "model_suggestion",
        "model": str(model_name),
        "interval_start_s": start,
        "interval_end_s": end,
        "sample_count": len(predictions),
        "min_confidence": float(min_confidence),
        "min_margin": float(min_margin),
        "sample_predictions": predictions,
        "score_semantics": "softmax of mean CLIP prompt logits; uncalibrated",
        "review_required": True,
        "limitations": [
            "Zero-shot camera suggestions have not been validated for rugby scrums",
            "Sparse samples may miss camera cuts or short overhead replays",
            "Aerial view does not establish complete player visibility or pose correctness",
        ],
    }
