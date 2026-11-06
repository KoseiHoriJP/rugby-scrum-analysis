"""Behavioral checks for pilot validation and reproducible dataset preparation."""

import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scrum_dataset import DatasetError, build_dataset, extract_archive, load_pilot


JOINT_NAMES = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class PilotDatasetTests(unittest.TestCase):
    """Small fixtures exercise relational errors without the uploaded archive."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.raw = self.base / "raw"
        self.raw.mkdir()
        self.output = self.base / "prepared"
        self.splits = self.base / "splits.json"
        self.splits.write_text(json.dumps({
            "train": ["match_train"],
            "validation": ["match_validation"],
            "test": ["match_test"],
        }), encoding="utf-8")
        clips, frames, detections, keypoints = [], [], [], []
        for split in ("train", "validation", "test"):
            clip_id = f"clip_{split}"
            clips.append({
                "clip_id": clip_id,
                "match_group": f"match_{split}",
                "match": f"Fixture {split}",
                "camera_view": "side_on",
                "video_path": f"videos/{clip_id}.mp4",
                "duration_s": "1.000000",
                "width_px": "640",
                "height_px": "480",
                "fps": "30/1",
                "frame_count": "30",
                "pose_start_s": "0",
                "pose_end_s_exclusive": "0.4",
                "roi_x_min_px": "100",
                "roi_y_min_px": "100",
                "roi_x_max_px_exclusive": "500",
                "roi_y_max_px_exclusive": "400",
                "source_url": "https://example.org/fixture",
                "source_creator": "Fixture author",
                "source_license": "Public domain",
                "notes": "Synthetic validator fixture; no ground-truth labels.",
            })
            for sample_index, source_frame, time, count in (
                (0, 0, "0.000000", 1), (1, 6, "0.200000", 0),
            ):
                frames.append({
                    "clip_id": clip_id,
                    "sample_index": str(sample_index),
                    "source_frame_index": str(source_frame),
                    "time_s": time,
                    "detection_count": str(count),
                })
            detections.append({
                "clip_id": clip_id,
                "source_frame_index": "0",
                "detection_index": "0",
                "detection_confidence": "0.9",
                "x_min_px": "110",
                "y_min_px": "110",
                "x_max_px": "300",
                "y_max_px": "350",
            })
            for joint_index, name in enumerate(JOINT_NAMES):
                keypoints.append({
                    "clip_id": clip_id,
                    "source_frame_index": "0",
                    "detection_index": "0",
                    "joint_index": str(joint_index),
                    "joint_name": name,
                    "x_px": str(130 + joint_index),
                    "y_px": str(150 + joint_index),
                    "joint_confidence": "0.2" if joint_index == 0 else "0.9",
                })
        for name, rows in (
            ("clips.csv", clips), ("sampled_frames.csv", frames),
            ("detections.csv", detections), ("yolo_keypoints.csv", keypoints),
        ):
            write_rows(self.raw / name, rows)

    def edit(self, filename, mutate):
        path = self.raw / filename
        rows = read_rows(path)
        mutate(rows)
        write_rows(path, rows)

    def test_valid_metadata_does_not_require_optional_media(self):
        loaded = load_pilot(self.raw)
        self.assertEqual(len(loaded["clips"]), 3)
        self.assertEqual(len(loaded["frames"]), 6)
        self.assertEqual(len(loaded["detections"]), 3)
        self.assertEqual(len(loaded["keypoints"]), 51)
        self.assertTrue(loaded["warnings"], "Absent original media should be reported")

    def test_rejects_duplicate_primary_keys_in_each_table(self):
        for filename in ("clips.csv", "sampled_frames.csv", "detections.csv", "yolo_keypoints.csv"):
            with self.subTest(filename=filename):
                path = self.raw / filename
                original = path.read_bytes()
                self.edit(filename, lambda rows: rows.append(dict(rows[0])))
                try:
                    with self.assertRaises(DatasetError):
                        load_pilot(self.raw)
                finally:
                    path.write_bytes(original)

    def test_rejects_unknown_clip(self):
        self.edit("sampled_frames.csv", lambda rows: rows[0].update(clip_id="unknown"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_detection_without_sampled_frame(self):
        self.edit("detections.csv", lambda rows: rows[0].update(source_frame_index="3"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_keypoint_without_detection(self):
        self.edit("yolo_keypoints.csv", lambda rows: rows[0].update(detection_index="99"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_incomplete_joint_set(self):
        self.edit("yolo_keypoints.csv", lambda rows: rows.pop())
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_incorrect_joint_name(self):
        self.edit("yolo_keypoints.csv", lambda rows: rows[0].update(joint_name="left_ankle"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_nonfinite_coordinates(self):
        path = self.raw / "yolo_keypoints.csv"
        original = path.read_bytes()
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                path.write_bytes(original)
                self.edit("yolo_keypoints.csv", lambda rows: rows[0].update(x_px=value))
                with self.assertRaises(DatasetError):
                    load_pilot(self.raw)

    def test_rejects_confidence_outside_unit_interval(self):
        self.edit("yolo_keypoints.csv", lambda rows: rows[0].update(joint_confidence="1.1"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_declared_detection_count_mismatch(self):
        self.edit("sampled_frames.csv", lambda rows: rows[0].update(detection_count="2"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_rejects_timestamp_inconsistent_with_source_frame(self):
        self.edit("sampled_frames.csv", lambda rows: rows[0].update(time_s="0.1"))
        with self.assertRaises(DatasetError):
            load_pilot(self.raw)

    def test_build_preserves_all_frames_and_full_joint_sets(self):
        report = build_dataset(self.raw, self.output, self.splits)
        expected = {
            "clips": 3, "match_groups": 3, "frames": 6, "detections": 3,
            "keypoints": 51, "zero_detection_frames": 3,
        }
        for name, count in expected.items():
            self.assertEqual(report["counts"][name], count, name)
        records = [json.loads(line) for line in
                   (self.output / "poses.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 6)
        self.assertEqual(sum(not frame["detections"] for frame in records), 3)
        for frame in records:
            for detection in frame["detections"]:
                self.assertEqual(len(detection["keypoints"]), 17)
        for filename in (
            "frame_annotations.csv", "person_annotations.csv", "validation_report.json",
            "provenance.json", "clips.csv",
        ):
            self.assertTrue((self.output / filename).is_file(), filename)
        self.assertEqual(len(read_rows(self.output / "frame_annotations.csv")), 6)
        self.assertEqual(len(read_rows(self.output / "person_annotations.csv")), 3)
        for split in ("train", "validation", "test"):
            rows = read_rows(self.output / "splits" / f"{split}.csv")
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["match_group"] for row in rows}, {f"match_{split}"})
        for row in read_rows(self.output / "frame_annotations.csv"):
            self.assertEqual(row["label"], "")
            self.assertEqual(row["label_schema"], "scrum_phase_v1")
        for row in read_rows(self.output / "person_annotations.csv"):
            for field in ("player_track_id", "is_scrum_player", "pose_usable"):
                self.assertEqual(row[field], "")

    def test_rejects_match_group_leakage_across_splits(self):
        self.splits.write_text(json.dumps({
            "train": ["match_train"],
            "validation": ["match_train", "match_validation"],
            "test": ["match_test"],
        }), encoding="utf-8")
        with self.assertRaises(DatasetError):
            build_dataset(self.raw, self.output, self.splits)

    def test_rejects_unassigned_match_group(self):
        self.splits.write_text(json.dumps({
            "train": ["match_train"], "validation": ["match_validation"], "test": [],
        }), encoding="utf-8")
        with self.assertRaises(DatasetError):
            build_dataset(self.raw, self.output, self.splits)

    def test_refuses_to_overwrite_existing_output(self):
        self.output.mkdir()
        marker = self.output / "existing-work.txt"
        marker.write_text("preserve this", encoding="utf-8")
        with self.assertRaises((DatasetError, FileExistsError)):
            build_dataset(self.raw, self.output, self.splits)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve this")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_repeat_builds_have_identical_data_exports(self):
        second = self.base / "prepared-again"
        build_dataset(self.raw, self.output, self.splits)
        build_dataset(self.raw, second, self.splits)
        for filename in ("poses.jsonl", "clips.csv", "frame_annotations.csv", "person_annotations.csv"):
            self.assertEqual((self.output / filename).read_bytes(), (second / filename).read_bytes(), filename)

    def test_imports_self_contained_metadata_archive(self):
        archive = self.base / "pilot.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            for path in self.raw.glob("*.csv"):
                zipped.write(path, path.name)
            zipped.writestr("__MACOSX/._clips.csv", "ignored metadata")
        destination = self.base / "imported"
        extract_archive(archive, destination)
        self.assertEqual(len(load_pilot(destination)["frames"]), 6)
        self.assertFalse((destination / "__MACOSX").exists())

    def test_archive_import_rejects_path_traversal(self):
        archive = self.base / "traversal.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("../escaped.txt", "must not escape")
        destination = self.base / "imported"
        with self.assertRaises(DatasetError):
            extract_archive(archive, destination)
        self.assertFalse(destination.exists())
        self.assertFalse((self.base / "escaped.txt").exists())

    def test_archive_import_rejects_symlinks(self):
        archive = self.base / "symlink.zip"
        entry = zipfile.ZipInfo("linked.csv")
        entry.create_system = 3
        entry.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr(entry, "/etc/passwd")
        destination = self.base / "imported"
        with self.assertRaises(DatasetError):
            extract_archive(archive, destination)
        self.assertFalse(destination.exists())

    def test_archive_import_preserves_existing_destination(self):
        archive = self.base / "empty.zip"
        with zipfile.ZipFile(archive, "w"):
            pass
        with self.assertRaises(DatasetError):
            extract_archive(archive, self.raw)
        self.assertEqual(len(load_pilot(self.raw)["frames"]), 6)


if __name__ == "__main__":
    unittest.main()
