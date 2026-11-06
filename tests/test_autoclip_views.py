"""Model-free checks for draft camera labels and actual local frame decoding."""

import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from automation.views import (
    ViewClassificationError, aggregate_views, classify_view,
    extract_sample_frames, prediction_from_scores,
)


def frame(view, confidence=0.9, margin=0.8):
    return {"view": view, "confidence": confidence, "margin": margin}


class ViewSuggestionTests(unittest.TestCase):
    def test_clear_aerial_score_suggests_aerial(self):
        result = prediction_from_scores({"aerial": 5, "side": 0, "unknown": 0})
        self.assertEqual(result["view"], "aerial")
        self.assertAlmostEqual(sum(result["class_probabilities"].values()), 1)

    def test_similar_scores_remain_unknown(self):
        result = prediction_from_scores({"aerial": 1.0, "side": 0.9, "unknown": 0.8})
        self.assertEqual(result["view"], "unknown")
        self.assertEqual(result["predicted_class"], "aerial")

    def test_margin_threshold_can_reject_winning_class(self):
        result = prediction_from_scores(
            {"aerial": 3.0, "side": 2.0, "unknown": -10},
            min_confidence=0.5, min_margin=0.8,
        )
        self.assertEqual(result["view"], "unknown")

    def test_closeups_or_non_scrum_can_remain_unknown_with_high_score(self):
        result = prediction_from_scores({"aerial": 0, "side": 0, "unknown": 20})
        self.assertEqual(result["view"], "unknown")
        self.assertEqual(result["predicted_class"], "unknown")

    def test_large_logits_do_not_overflow(self):
        result = prediction_from_scores({"aerial": 10000, "side": 9990, "unknown": -10000})
        self.assertEqual(result["view"], "aerial")
        self.assertTrue(math.isfinite(result["confidence"]))

    def test_invalid_scores_and_thresholds_are_rejected(self):
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value):
                with self.assertRaises(ViewClassificationError):
                    prediction_from_scores({"aerial": value, "side": 0, "unknown": 0})
        with self.assertRaises(ViewClassificationError):
            prediction_from_scores({"aerial": 1, "side": 0})
        for threshold in (-0.1, 1.1, float("nan")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ViewClassificationError):
                    prediction_from_scores({"aerial": 1, "side": 0, "unknown": 0}, min_confidence=threshold)

    def test_camera_change_is_mixed_even_with_a_dominant_view(self):
        self.assertEqual(aggregate_views([frame("aerial")] * 6 + [frame("side")]), "mixed")

    def test_confident_opposite_views_not_hidden_by_unknown_frames(self):
        self.assertEqual(aggregate_views([frame("aerial"), frame("side")] + [frame("unknown")] * 5), "mixed")

    def test_unknown_samples_count_against_single_view_fraction(self):
        self.assertEqual(aggregate_views([frame("aerial")] * 4 + [frame("unknown")] * 3), "unknown")
        self.assertEqual(aggregate_views([frame("aerial")] * 5 + [frame("unknown")] * 2), "aerial")

    def test_side_and_empty_aggregation(self):
        self.assertEqual(aggregate_views([frame("side")] * 4 + [frame("unknown")]), "side")
        self.assertEqual(aggregate_views([]), "unknown")

    def test_invalid_frame_suggestions_are_rejected(self):
        for prediction in (frame("mixed"), frame("side", float("nan")), {"view": "side"}):
            with self.subTest(prediction=prediction):
                with self.assertRaises(ViewClassificationError):
                    aggregate_views([prediction])
        with self.assertRaises(ViewClassificationError):
            aggregate_views([], min_fraction=0)

    def test_input_validation_precedes_optional_model_loading(self):
        with self.assertRaisesRegex(ViewClassificationError, "Video file is missing"):
            classify_view(Path("/nonexistent/rugby.mp4"), 0, 10)
        for start, end in ((-1, 3), (3, 3), (0, float("inf"))):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ViewClassificationError):
                    classify_view(Path("/nonexistent/rugby.mp4"), start, end)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe required")
class FrameDecodingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "fixture.mp4"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
             "testsrc=size=320x180:rate=10:duration=2", "-c:v", "mpeg4", "-threads", "1", str(self.video)],
            capture_output=True, check=True, timeout=30,
        )

    def test_decodes_samples_at_expected_interior_timestamps(self):
        samples = extract_sample_frames(self.video, 0.25, 1.75, self.root / "frames", samples=3)
        self.assertEqual([s["time_s"] for s in samples], [0.5, 1.0, 1.5])
        for sample in samples:
            self.assertTrue(sample["path"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_interval_beyond_source_and_existing_output_are_rejected(self):
        with self.assertRaisesRegex(ViewClassificationError, "after video duration"):
            extract_sample_frames(self.video, 0, 3, self.root / "frames")
        directory = self.root / "frames"
        directory.mkdir()
        protected = directory / "view_000.png"
        protected.write_bytes(b"preserve")
        with self.assertRaisesRegex(ViewClassificationError, "Refusing to replace"):
            extract_sample_frames(self.video, 0, 1, directory)
        self.assertEqual(protected.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
