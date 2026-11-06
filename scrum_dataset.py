"""Validate and package the scrum pilot. Requires Python 3.10+; no pip packages."""

from __future__ import annotations

import argparse
import collections
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile


VERSION = "0.1.0"
JOINTS = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
    "right_knee", "left_ankle", "right_ankle",
)
PHASES = ("formation", "engagement", "drive", "release", "not_scrum", "uncertain")
SCHEMAS = {
    "clips": "clip_id match_group match camera_view video_path duration_s width_px height_px fps frame_count pose_start_s pose_end_s_exclusive roi_x_min_px roi_y_min_px roi_x_max_px_exclusive roi_y_max_px_exclusive source_url source_creator source_license notes".split(),
    "sampled_frames": "clip_id sample_index source_frame_index time_s detection_count".split(),
    "detections": "clip_id source_frame_index detection_index detection_confidence x_min_px y_min_px x_max_px y_max_px".split(),
    "yolo_keypoints": "clip_id source_frame_index detection_index joint_index joint_name x_px y_px joint_confidence".split(),
}


class DatasetError(ValueError):
    """An input does not satisfy the dataset contract."""


def require(condition, message):
    if not condition:
        raise DatasetError(message)


def number(row, name):
    try:
        value = float(row[name])
    except (ValueError, TypeError, KeyError) as exc:
        raise DatasetError(f"Invalid number {name}: {row.get(name)!r}") from exc
    require(math.isfinite(value), f"Nonfinite {name}: {value}")
    return value


def integer(row, name):
    value = number(row, name)
    require(value.is_integer() and value >= 0, f"Invalid nonnegative integer {name}: {value}")
    return int(value)


def relative_path(value):
    path = PurePosixPath(value)
    require(bool(value) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in value and ":" not in value,
            f"Unsafe relative path: {value!r}")
    return path


def safe_input(root, relative):
    target = root / relative_path(relative)
    require(target.resolve().is_relative_to(root.resolve()), f"Path escapes input: {relative}")
    return target


def read_table(root, name):
    path = root / f"{name}.csv"
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            require(reader.fieldnames is not None and
                    len(reader.fieldnames) == len(set(reader.fieldnames)), f"Invalid header in {path.name}")
            require(set(SCHEMAS[name]) <= set(reader.fieldnames), f"Missing columns in {path.name}")
            rows = list(reader)
            require(all(None not in row and all(v is not None for v in row.values()) for row in rows),
                    f"Malformed row in {path.name}")
            return rows
    except OSError as exc:
        raise DatasetError(f"Cannot read {path}: {exc}") from exc


def keyed(rows, fields, table):
    result = {}
    for row in rows:
        key = tuple(row[f] if f in {"clip_id", "match_group"} else integer(row, f) for f in fields)
        require(key not in result, f"Duplicate key in {table}: {key}")
        result[key] = row
    return result


def load_pilot(input_dir: Path):
    """Validate all CSV relations, keeping estimates and low confidence joints intact."""
    root = Path(input_dir)
    clips = read_table(root, "clips")
    frames = read_table(root, "sampled_frames")
    detections = read_table(root, "detections")
    keypoints = read_table(root, "yolo_keypoints")
    require(clips and frames, "Dataset must have clips and sampled frames")
    clip_map = keyed(clips, ["clip_id"], "clips")
    fps_map = {}
    warnings = []
    for clip in clips:
        cid = clip["clip_id"]
        require(cid and all(c.isalnum() or c in "_-" for c in cid), f"Unsafe clip_id: {cid!r}")
        require(all(clip[k].strip() for k in ["match_group", "match", "source_url", "source_creator", "source_license"]),
                f"Missing provenance for {cid}")
        try:
            fps = float(Fraction(clip["fps"]))
        except (ValueError, ZeroDivisionError) as exc:
            raise DatasetError(f"Invalid fps for {cid}") from exc
        require(math.isfinite(fps) and fps > 0, f"Invalid fps for {cid}")
        fps_map[cid] = fps
        width, height = integer(clip, "width_px"), integer(clip, "height_px")
        count = integer(clip, "frame_count")
        require(width > 0 and height > 0 and count > 0, f"Invalid video dimensions/count: {cid}")
        duration = number(clip, "duration_s")
        require(duration > 0, f"Invalid duration: {cid}")
        require(abs(duration - count / fps) < max(0.001, 1 / fps), f"Frame count/duration mismatch: {cid}")
        start, end = number(clip, "pose_start_s"), number(clip, "pose_end_s_exclusive")
        require(0 <= start < end <= duration + 1e-6, f"Invalid sampling interval: {cid}")
        x0, y0, x1, y1 = [integer(clip, f) for f in ["roi_x_min_px", "roi_y_min_px", "roi_x_max_px_exclusive", "roi_y_max_px_exclusive"]]
        require(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height, f"Invalid ROI: {cid}")
        if not safe_input(root, clip["video_path"]).is_file():
            warnings.append(f"Original video missing: {clip['video_path']}; clean-image training unavailable")
        if not safe_input(root, f"skeleton_previews/{cid}_pose.mp4").is_file():
            warnings.append(f"Preview missing: {cid}")

    frame_map = keyed(frames, ["clip_id", "source_frame_index"], "sampled_frames")
    keyed(frames, ["clip_id", "sample_index"], "sampled_frames samples")
    detection_map = keyed(detections, ["clip_id", "source_frame_index", "detection_index"], "detections")
    joint_map = keyed(keypoints, ["clip_id", "source_frame_index", "detection_index", "joint_index"], "keypoints")
    samples = collections.defaultdict(list)
    detections_by_frame = collections.defaultdict(list)
    joints_by_detection = collections.defaultdict(list)
    for frame in frames:
        cid, index = frame["clip_id"], integer(frame, "source_frame_index")
        require((cid,) in clip_map, f"Unknown clip in frame: {cid}")
        clip = clip_map[cid,]
        time = number(frame, "time_s")
        require(index < integer(clip, "frame_count"), f"Frame index outside source: {cid}/{index}")
        require(abs(time - index / fps_map[cid]) <= 1e-5, f"Timestamp/frame mismatch: {cid}/{index}")
        require(number(clip, "pose_start_s") <= time < number(clip, "pose_end_s_exclusive"),
                f"Frame outside sampling interval: {cid}/{index}")
        integer(frame, "detection_count")
        samples[cid].append(frame)
    for clip in clips:
        cid = clip["clip_id"]
        ordered = sorted(samples[cid], key=lambda r: integer(r, "sample_index"))
        require(ordered and [integer(r, "sample_index") for r in ordered] == list(range(len(ordered))),
                f"Noncontiguous samples: {cid}")
        indices = [integer(r, "source_frame_index") for r in ordered]
        require(indices == sorted(set(indices)), f"Sample order not chronological: {cid}")

    for key, row in detection_map.items():
        require(key[:2] in frame_map, f"Orphan detection: {key}")
        clip = clip_map[key[0],]
        require(0 <= number(row, "detection_confidence") <= 1, f"Invalid detection confidence: {key}")
        x0, y0, x1, y1 = [number(row, f) for f in ["x_min_px", "y_min_px", "x_max_px", "y_max_px"]]
        require(0 <= x0 < x1 <= integer(clip, "width_px") and 0 <= y0 < y1 <= integer(clip, "height_px"),
                f"Box outside image or degenerate: {key}")
        detections_by_frame[key[:2]].append(key[2])
    for key, frame in frame_map.items():
        indices = sorted(detections_by_frame[key])
        require(len(indices) == integer(frame, "detection_count"), f"Detection count mismatch: {key}")
        require(indices == list(range(len(indices))), f"Noncontiguous detection indices: {key}")

    for key, row in joint_map.items():
        require(key[:3] in detection_map, f"Orphan keypoint: {key}")
        j = key[3]
        require(j < len(JOINTS) and row["joint_name"] == JOINTS[j], f"Invalid COCO joint index/name: {key}")
        clip = clip_map[key[0],]
        x, y, confidence = [number(row, f) for f in ["x_px", "y_px", "joint_confidence"]]
        require(0 <= confidence <= 1, f"Invalid joint confidence: {key}")
        require(0 <= x < integer(clip, "width_px") and 0 <= y < integer(clip, "height_px"),
                f"Joint outside full image: {key}")
        if not (number(clip, "roi_x_min_px") <= x < number(clip, "roi_x_max_px_exclusive")
                and number(clip, "roi_y_min_px") <= y < number(clip, "roi_y_max_px_exclusive")):
            warnings.append(f"Joint at/outside exclusive ROI boundary (preserved): {key}; confidence={confidence}")
        joints_by_detection[key[:3]].append(j)
    for key in detection_map:
        require(sorted(joints_by_detection[key]) == list(range(17)), f"Expected 17 COCO joints: {key}")
    counts = {"clips": len(clips), "match_groups": len({r["match_group"] for r in clips}),
              "frames": len(frames), "detections": len(detections), "keypoints": len(keypoints),
              "zero_detection_frames": sum(integer(r, "detection_count") == 0 for r in frames)}
    return dict(clips=clips, frames=frames, detections=detections, keypoints=keypoints,
                stats=counts, warnings=warnings)


def load_splits(path, groups):
    try:
        config = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise DatasetError(f"Cannot read split config: {exc}") from exc
    require(isinstance(config, dict) and set(config) == {"train", "validation", "test"},
            "Splits must define train, validation and test")
    lookup = {}
    for split, items in config.items():
        require(isinstance(items, list) and items and all(isinstance(v, str) and v for v in items),
                f"Split {split} requires a nonempty group list")
        for group in items:
            require(group not in lookup, f"Match group occurs in multiple splits: {group}")
            lookup[group] = split
    require(set(lookup) == groups, "Split groups must match all dataset groups exactly")
    return lookup


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preview_info(path, expected_count, warnings):
    """Verify preview order/count before enabling sampled-frame seeking."""
    if not shutil.which("ffprobe"):
        warnings.append(f"ffprobe absent: preview alignment unverified: {path.name}")
        return None
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                 "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                                 "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
        stream = json.loads(result.stdout)["streams"][0]
        require(int(stream["nb_frames"]) == expected_count, f"Preview frame-count mismatch: {path.name}")
        fps = float(Fraction(stream["r_frame_rate"]))
        require(fps == 5, f"Expected documented 5 fps preview: {path.name}")
        return dict(width_px=stream["width"], height_px=stream["height"], fps=fps, frame_count=expected_count)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as exc:
        if isinstance(exc, DatasetError):
            raise
        raise DatasetError(f"Cannot verify preview {path.name}: {exc}") from exc


def build_dataset(input_dir: Path, output_dir: Path, split_path: Path, threshold: float = 0.5):
    """Build reproducible exports atomically; never overwrite an existing output."""
    root, output = Path(input_dir), Path(output_dir)
    require(not output.exists(), f"Output already exists: {output}; use a new version directory")
    require(not output.resolve().is_relative_to(root.resolve()), "Output must be outside the raw input")
    require(math.isfinite(threshold) and 0 <= threshold <= 1, "Threshold must be finite in [0,1]")
    data = load_pilot(root)
    groups = {r["match_group"] for r in data["clips"]}
    split_lookup = load_splits(split_path, groups)
    clips = {r["clip_id"]: r for r in data["clips"]}
    frames = sorted(data["frames"], key=lambda r: (r["clip_id"], integer(r, "sample_index")))
    by_frame, by_detection = collections.defaultdict(list), collections.defaultdict(list)
    for d in data["detections"]:
        by_frame[d["clip_id"], integer(d, "source_frame_index")].append(d)
    for p in data["keypoints"]:
        by_detection[p["clip_id"], integer(p, "source_frame_index"), integer(p, "detection_index")].append(p)
    warnings = list(data["warnings"])
    report = {"schema_version": VERSION, "validation": "passed", "counts": data["stats"],
              "phase_schema": list(PHASES), "manual_phase_labels": 0,
              "confidence_threshold": threshold,
              "low_confidence_keypoints": sum(number(p, "joint_confidence") < threshold for p in data["keypoints"]),
              "warnings": warnings, "splits": {}}
    output.parent.mkdir(parents=True, exist_ok=True)
    # Stage next to destination so a failed build leaves no partially usable dataset.
    with tempfile.TemporaryDirectory(prefix=".scrum-build-", dir=output.parent) as temporary:
        staging = Path(temporary) / "dataset"
        staging.mkdir()
        preview_meta, ui_clips = {}, []
        for cid in sorted(clips):
            source = safe_input(root, f"skeleton_previews/{cid}_pose.mp4")
            metadata = None
            if source.is_file():
                metadata = preview_info(source, sum(r["clip_id"] == cid for r in frames), warnings)
                (staging / "previews").mkdir(exist_ok=True)
                shutil.copyfile(source, staging / "previews" / source.name)
            preview_meta[cid] = metadata
            ui_clips.append({"clip_id": cid, "preview_path": f"previews/{source.name}" if source.is_file() else None,
                             "preview_fps": metadata["fps"] if metadata else None})
        manifest, person_rows, pose_rows = [], [], []
        for frame in frames:
            cid, index = frame["clip_id"], integer(frame, "source_frame_index")
            clip = clips[cid]
            group = clip["match_group"]
            base = {"clip_id": cid, "match_group": group, "split": split_lookup[group],
                    "sample_index": integer(frame, "sample_index"), "source_frame_index": index,
                    "time_s": number(frame, "time_s"), "detection_count": integer(frame, "detection_count"),
                    "video_path": clip["video_path"], "original_video_available": safe_input(root, clip["video_path"]).is_file(),
                    "preview_time_s": integer(frame, "sample_index") / preview_meta[cid]["fps"] if preview_meta[cid] else None}
            manifest.append(base)
            persons = []
            for d in sorted(by_frame[cid, index], key=lambda r: integer(r, "detection_index")):
                di = integer(d, "detection_index")
                points = sorted(by_detection[cid, index, di], key=lambda r: integer(r, "joint_index"))
                persons.append({"detection_index": di, "track_id": None,
                                "detection_confidence": number(d, "detection_confidence"),
                                "bbox_xyxy_px": [number(d, f) for f in ["x_min_px", "y_min_px", "x_max_px", "y_max_px"]],
                                "keypoints": [{"joint_index": integer(p, "joint_index"), "joint_name": p["joint_name"],
                                               "x_px": number(p, "x_px"), "y_px": number(p, "y_px"),
                                               "confidence": number(p, "joint_confidence"),
                                               "confidence_mask": number(p, "joint_confidence") >= threshold} for p in points]})
                person_rows.append({"clip_id": cid, "source_frame_index": index, "detection_index": di,
                                    "player_track_id": "", "is_scrum_player": "", "pose_usable": "",
                                    "review_status": "unreviewed", "annotator": "", "notes": ""})
            pose_rows.append({**base, "coordinate_space": "original_video_pixels", "pose_origin": "automatic_yolo11s_pose",
                              "phase": None, "detections": persons})
        manifest_fields = list(manifest[0])
        write_csv(staging / "frames.csv", manifest_fields, manifest)
        for split in ["train", "validation", "test"]:
            subset = [r for r in manifest if r["split"] == split]
            write_csv(staging / "splits" / f"{split}.csv", manifest_fields, subset)
            report["splits"][split] = {"match_groups": sorted(g for g in groups if split_lookup[g] == split),
                                       "clips": len({r["clip_id"] for r in subset}), "frames": len(subset),
                                       "detections": sum(r["detection_count"] for r in subset)}
        frame_rows = [{**{k: r[k] for k in ["clip_id", "match_group", "split", "source_frame_index", "sample_index", "time_s"]},
                       "label_schema": "scrum_phase_v1", "label": "", "review_status": "unreviewed", "annotator": "", "notes": ""}
                      for r in manifest]
        write_csv(staging / "frame_annotations.csv", list(frame_rows[0]), frame_rows)
        write_json(staging / "phase_schema.json", {
            "name": "scrum_phase_v1", "unit": "sampled_frame",
            "primary_key": ["clip_id", "source_frame_index"],
            "allowed_labels": list(PHASES), "blank_label_means": "unannotated",
            "review_statuses": ["unreviewed", "draft", "reviewed"],
            "instruction": "Use ANNOTATION_GUIDE.md; independently review drafts before treating them as ground truth",
        })
        person_fields = "clip_id source_frame_index detection_index player_track_id is_scrum_player pose_usable review_status annotator notes".split()
        write_csv(staging / "person_annotations.csv", person_fields, person_rows)
        with (staging / "poses.jsonl").open("w", encoding="utf-8") as handle:
            for record in pose_rows:
                handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        shutil.copyfile(root / "clips.csv", staging / "clips.csv")
        for filename in ["README.md", "aerial_candidates.csv"]:
            if (root / filename).is_file():
                shutil.copyfile(root / filename, staging / ("SOURCE_README.md" if filename == "README.md" else filename))
        source_files = sorted({str(p.relative_to(root)): p for p in root.rglob("*") if p.is_file()
                               and (p.suffix in {".csv", ".md"} or p.parent.name == "skeleton_previews")}.items())
        provenance = {"builder_version": VERSION, "builder_sha256": sha256(Path(__file__)),
                      "supporting_assets_sha256": {
                          str(p.relative_to(Path(__file__).parent)): sha256(p)
                          for p in sorted([Path(__file__).parent / "templates" / "review.html",
                                           *list((Path(__file__).parent / "docs").glob("*.md"))]) if p.is_file()
                      },
                      "inputs_sha256": {name: sha256(path) for name, path in source_files},
                      "split_config": {s: sorted(g for g in groups if split_lookup[g] == s) for s in ["train", "validation", "test"]},
                      "pose_model_reported_by_source": {"model": "yolo11s-pose.pt", "ultralytics": "8.3.221",
                           "input_size": 640, "confidence": 0.25, "nms_iou": 0.70, "rerun_in_this_build": False},
                      "previews": preview_meta, "coordinates": "Full original-video pixels; ROI offsets already included",
                      "labels": "Empty manual templates; model confidence is not ground truth or visibility"}
        write_json(staging / "provenance.json", provenance)
        write_json(staging / "validation_report.json", report)
        template = Path(__file__).parent / "templates" / "review.html"
        require(template.is_file(), "Review UI template missing")
        ui_json = json.dumps({"clips": ui_clips, "frames": manifest, "schema": list(PHASES)}, ensure_ascii=False)
        ui_json = ui_json.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        (staging / "review.html").write_text(template.read_text(encoding="utf-8").replace("__DATASET_JSON__", ui_json), encoding="utf-8")
        for doc in ["DATASET_CARD.md", "ANNOTATION_GUIDE.md"]:
            path = Path(__file__).parent / "docs" / doc
            if path.is_file():
                shutil.copyfile(path, staging / doc)
        require(not output.exists(), f"Output appeared during build: {output}")
        staging.rename(output)
    return report


def extract_archive(archive, destination):
    """Import a user-supplied archive without overwrites, links or traversal."""
    require(not destination.exists(), f"Raw destination exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".scrum-import-", dir=destination.parent) as tmp:
        staging = Path(tmp) / "raw"
        staging.mkdir()
        with zipfile.ZipFile(archive) as source:
            entries = [f for f in source.infolist() if not f.is_dir()
                       and not f.filename.startswith("__MACOSX/") and PurePosixPath(f.filename).name != ".DS_Store"]
            require(sum(f.file_size for f in entries) < 2 * 1024**3, "Archive expands beyond 2 GiB")
            for entry in entries:
                relative_path(entry.filename)
                require((entry.external_attr >> 16) & 0o170000 != 0o120000, "Archive contains a symlink")
                path = staging / entry.filename
                path.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as inp, path.open("xb") as out:
                    shutil.copyfileobj(inp, out)
        load_pilot(staging)
        staging.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/raw/pilot"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/pilot-v1"))
    parser.add_argument("--splits", type=Path, default=Path("configs/pilot_splits.json"))
    parser.add_argument("--archive", type=Path, help="Import archive into a NEW --input directory before building")
    parser.add_argument("--confidence-threshold", type=float, default=0.5)
    args = parser.parse_args()
    try:
        if args.archive:
            extract_archive(args.archive, args.input)
        report = build_dataset(args.input, args.output, args.splits, args.confidence_threshold)
    except (DatasetError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Dataset error: {exc}\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
