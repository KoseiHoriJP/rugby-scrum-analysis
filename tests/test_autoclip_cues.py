"""Cue logic and ASR adapter tests; no model or network access is required."""

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from automation.cues import detect_sequences, transcribe_video


def words(tokens, starts=None, probability=0.9):
    if starts is None:
        starts = list(range(len(tokens)))
    return [{"word": token, "start": start, "end": start + 0.2,
             "probability": probability} for token, start in zip(tokens, starts)]


class CueDetectionTests(unittest.TestCase):
    def test_ordered_exact_sequence_preserves_time_and_candidate_status(self):
        found = detect_sequences(words(["Crouch", "bind", "set"], [35, 38, 41]))
        self.assertEqual(found, [{"crouch_s": 35.0, "bind_s": 38.0, "set_s": 41.0,
                                  "cue_confidence": 0.9, "cue_status": "automatic_candidate"}])
        self.assertNotIn("end_s", found[0])

    def test_punctuation_case_and_intervening_words(self):
        found = detect_sequences(words([" ‘CROUCH,’ ", "hold", "BIND!", "and", "Set."]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["bind_s"], 2)

    def test_does_not_repair_plural_or_fuzzy_commands(self):
        for tokens in (["crouches", "bind", "set"], ["crouch", "binds", "set"],
                       ["crouch", "bind", "sets"], ["crouch-bind-set"],
                       ["crouch bind set"], ["crouch", "blind", "set"]):
            with self.subTest(tokens=tokens):
                self.assertEqual(detect_sequences(words(tokens)), [])

    def test_missing_or_out_of_order_commands_are_not_sequences(self):
        for tokens in (["crouch", "set"], ["bind", "crouch", "set"],
                       ["set", "bind", "crouch"], ["crouch", "bind"]):
            with self.subTest(tokens=tokens):
                self.assertEqual(detect_sequences(words(tokens)), [])

    def test_sequence_window_is_inclusive_by_command_start(self):
        self.assertEqual(len(detect_sequences(words(["crouch", "bind", "set"], [0, 10, 20]))), 1)
        self.assertEqual(detect_sequences(words(["crouch", "bind", "set"], [0, 10, 20.1])), [])

    def test_resets_are_separate_and_set_is_not_reused(self):
        found = detect_sequences(words(["crouch", "bind", "set", "set", "crouch", "bind", "set"]))
        self.assertEqual([r["crouch_s"] for r in found], [0, 4])
        self.assertEqual([r["set_s"] for r in found], [2, 6])

    def test_latest_crouch_restarts_incomplete_sequence(self):
        found = detect_sequences(words(["crouch", "bind", "crouch", "bind", "set"]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["crouch_s"], 2)

    def test_missing_probability_produces_null_confidence(self):
        sample = words(["crouch", "bind", "set"])
        sample[1].pop("probability")
        self.assertIsNone(detect_sequences(sample)[0]["cue_confidence"])

    def test_confidence_is_minimum_not_a_ground_truth_claim(self):
        sample = words(["crouch", "bind", "set"])
        for row, confidence in zip(sample, [0.95, 0.4, 0.8]):
            row["probability"] = confidence
        self.assertEqual(detect_sequences(sample)[0]["cue_confidence"], 0.4)

    def test_rejects_malformed_times_and_confidences(self):
        for field, value in [("start", -1), ("start", float("nan")),
                             ("end", float("inf")), ("end", -0.1),
                             ("start", "0"), ("start", True),
                             ("probability", 1.1), ("probability", float("nan"))]:
            with self.subTest(field=field, value=value):
                sample = words(["crouch", "bind", "set"])
                sample[0][field] = value
                with self.assertRaises(ValueError):
                    detect_sequences(sample)

    def test_rejects_overlapping_or_unsorted_word_chronology(self):
        for starts in ([0, 0.1, 2], [1, 0, 2]):
            with self.subTest(starts=starts):
                with self.assertRaises(ValueError):
                    detect_sequences(words(["crouch", "bind", "set"], starts))

    def test_validates_all_words_even_when_not_commands(self):
        sample = words(["hello", "there"])
        sample[1]["end"] = float("nan")
        with self.assertRaises(ValueError):
            detect_sequences(sample)

    def test_rejects_invalid_window_and_input_shape(self):
        for maximum in [0, -1, float("nan"), float("inf"), True, "20"]:
            with self.subTest(maximum=maximum):
                with self.assertRaises(ValueError):
                    detect_sequences([], maximum)
        for invalid in [None, {}, [None], [{"word": None, "start": 0, "end": 1}]]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    detect_sequences(invalid)

    def test_does_not_mutate_source_words(self):
        sample = words(["Crouch,", "Bind,", "Set!"])
        before = [dict(r) for r in sample]
        detect_sequences(sample)
        self.assertEqual(sample, before)

    def test_empty_audio_words_yield_no_candidates(self):
        self.assertEqual(detect_sequences([]), [])


class TranscriptionAdapterTests(unittest.TestCase):
    def test_adapter_uses_real_word_timestamps_without_cue_prompt_or_vad(self):
        calls = {}

        class Model:
            def __init__(self, name, **options):
                calls["model"] = (name, options)

            def transcribe(self, path, **options):
                calls["transcribe"] = (path, options)
                segment = types.SimpleNamespace(
                    start=0, end=3, text="Crouch, bind, set.",
                    words=[types.SimpleNamespace(**r) for r in words(["Crouch,", "bind,", "set."])],
                )
                return iter([segment]), types.SimpleNamespace(language="en")

        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "match.mp4"
            video.write_bytes(b"fixture; model mocked")
            with patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=Model)}):
                result = transcribe_video(video, model_dir=Path(temporary) / "models")
        self.assertEqual(calls["transcribe"][1], {
            "language": "en", "word_timestamps": True, "vad_filter": False, "beam_size": 5,
        })
        self.assertEqual(calls["model"][0], "small.en")
        self.assertEqual(result["language"], "en")
        self.assertEqual(len(result["words"]), 3)
        self.assertEqual(len(detect_sequences(result["words"])), 1)

    def test_missing_local_video_does_not_attempt_model_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                transcribe_video(Path(temporary) / "missing.mp4")


if __name__ == "__main__":
    unittest.main()
