"""Conservative speech-cue proposals for scrum collection.

An ordered spoken sequence is evidence for a candidate, not proof that the
speaker is a referee or that a scrum subsequently occurred. This module never
assigns a scrum end time, camera view, or a human-verified label.
"""

from __future__ import annotations

import math
from pathlib import Path
import unicodedata


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _token(text: str) -> str:
    """Strip edge punctuation only; do not fuzzy-match or split ASR words."""
    text = text.strip().casefold()
    while text and unicodedata.category(text[0]).startswith("P"):
        text = text[1:]
    while text and unicodedata.category(text[-1]).startswith("P"):
        text = text[:-1]
    return text


def _validated_words(words: list[dict]) -> list[dict]:
    if not isinstance(words, list):
        raise ValueError("words must be a list of word records")
    result = []
    previous_end = 0.0
    for index, word in enumerate(words):
        if not isinstance(word, dict) or not isinstance(word.get("word"), str):
            raise ValueError(f"Word {index} requires a string 'word'")
        start = _number(word.get("start"), f"Word {index} start")
        end = _number(word.get("end"), f"Word {index} end")
        if start < 0 or end < start:
            raise ValueError(f"Word {index} requires 0 <= start <= end")
        if start < previous_end:
            raise ValueError(f"Word {index} is out of order or overlaps the previous word")
        probability = word.get("probability")
        if probability is not None:
            probability = _number(probability, f"Word {index} probability")
            if not 0 <= probability <= 1:
                raise ValueError(f"Word {index} probability must lie in [0, 1]")
        result.append({"word": word["word"], "start": start, "end": end,
                       "probability": probability})
        previous_end = end
    return result


def detect_sequences(words: list[dict], max_sequence_seconds: float = 20.0) -> list[dict]:
    """Find exact ordered Crouch/Bind/Set tokens within a start-to-start span.

    Missing commands and fuzzy spellings are deliberately not repaired. A new
    Crouch restarts a pending sequence; a Set is consumed at most once. Resets
    with a complete new command sequence become separate candidates.

    ``cue_confidence`` is the minimum of the three ASR word probabilities when
    all are supplied, otherwise None. It does not estimate referee identity or
    the probability that the proposed event is actually a scrum.
    """
    maximum = _number(max_sequence_seconds, "max_sequence_seconds")
    if maximum <= 0:
        raise ValueError("max_sequence_seconds must be positive")
    validated = _validated_words(words)
    crouch = bind = None
    result = []
    for word in validated:
        if crouch is not None and word["start"] - crouch["start"] > maximum:
            crouch = bind = None
        token = _token(word["word"])
        if token == "crouch":
            crouch, bind = word, None
        elif token == "bind" and crouch is not None and bind is None:
            bind = word
        elif token == "set" and crouch is not None and bind is not None:
            probabilities = [cue["probability"] for cue in (crouch, bind, word)]
            confidence = min(probabilities) if all(p is not None for p in probabilities) else None
            result.append({"crouch_s": crouch["start"], "bind_s": bind["start"],
                           "set_s": word["start"], "cue_confidence": confidence,
                           "cue_status": "automatic_candidate"})
            crouch = bind = None
    return result


def transcribe_video(
    video: Path,
    model_name: str = "small.en",
    device: str = "cpu",
    compute_type: str = "int8",
    model_dir: Path | None = None,
) -> dict:
    """Transcribe a local video with optional faster-whisper word timestamps.

    Importing this module and detecting cues never loads an ASR dependency or
    downloads a model. This call can download the selected model through the
    normal faster-whisper mechanism if it is not cached. ``model_name`` may
    also name an existing local model directory; ``model_dir`` selects the
    optional download/cache directory.
    """
    path = Path(video)
    if not path.is_file():
        raise FileNotFoundError(f"Video does not exist: {path}")
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a nonempty model name or local path")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Audio transcription requires faster-whisper; install it with "
            "python -m pip install faster-whisper"
        ) from exc

    options = {"device": device, "compute_type": compute_type}
    if model_dir is not None:
        options["download_root"] = str(Path(model_dir))
    model = WhisperModel(model_name, **options)
    iterator, info = model.transcribe(
        str(path), language="en", word_timestamps=True, vad_filter=False,
        beam_size=5,
    )
    words, segments = [], []
    for segment in iterator:
        start = _number(segment.start, "Segment start")
        end = _number(segment.end, "Segment end")
        if start < 0 or end < start:
            raise ValueError("ASR segment requires 0 <= start <= end")
        segments.append({"start": start, "end": end, "text": segment.text})
        for word in segment.words or []:
            words.append({"word": word.word, "start": word.start, "end": word.end,
                          "probability": word.probability})
    words = _validated_words(words)
    return {"words": words, "segments": segments,
            "language": getattr(info, "language", "en"), "model": model_name}
