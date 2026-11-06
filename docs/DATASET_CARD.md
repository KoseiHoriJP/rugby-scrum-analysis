# Rugby Scrum Phase Pilot — dataset card

## Intended use

Small-scale manual annotation and feasibility work on rugby-union scrum phase
segmentation. The initial upload is a pose-analysis pilot, not an already
labeled phase benchmark. Do not use it to infer forces, player safety,
technical legality, persistent identities, or referee decisions.

## Contents of this version

- Five clips from three matches; side-on, sideline-oblique and elevated-oblique
  views. No verified true-overhead footage is included.
- 279 sampled frames, 1,378 automatic person detections, 23,426 keypoints.
- Three zero-detection frames are retained (Milano–Calvisano frames 69, 102, 108).
- Five cropped overlay videos, with verified 5 fps / sampled-frame counts.
- Blank manual phase annotation templates and an offline draft labeling tool.
- No original source MP4s in this upload; no clean frame images, model weights,
  manual pose corrections, phase labels, outcomes or referee decisions.
- Ten aerial candidate links are retained only as collection leads; one is
  rugby sevens. No rights or availability beyond the supplied metadata were
  verified and no candidate media was downloaded.

## Provenance and transformations

The user supplied `Archive.zip`, containing the pilot's CSVs, source README
and preview videos. macOS resource-fork metadata was omitted on import. The
builder validates and joins tables, adds match-level split assignments,
preserves all coordinates/confidences, adds a confidence mask, and copies
previews without re-encoding. It does not re-run pose estimation or add labels.
The generated `provenance.json` records input SHA-256 hashes and builder hash.

The source reports Ultralytics 8.3.221 / `yolo11s-pose.pt`, COCO 17 joints,
ROI inference at input size 640, confidence 0.25, NMS IoU 0.70, and preview
overlay confidence 0.50. These settings were not independently re-executed.
Frame indices are zero based; ROI right/bottom edges and interval end times
are exclusive. CSV coordinates already include the original ROI offset.

## Attribution supplied with the pilot

| Clip(s) | Creator | Source license |
| --- | --- | --- |
| `uruguay_argentina_01`, `uruguay_argentina_02` | NaBUru38 | CC BY-SA 4.0 |
| `italy_chile_01`, `italy_chile_02` | Superchilum | CC BY-SA 4.0 |
| `milano_calvisano` | Snowdog | Public domain |

Full per-clip Wikimedia Commons file-page URLs are preserved in `clips.csv`.
The source reports conversion to H.264 MP4 and preview crop/pose overlays;
this build adds manifests and review materials. Preserve those attributions,
source links, license notices and modification descriptions on redistribution.
CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/ . The media are
not relicensed by the repository's code or by packaging this dataset. The
source README is retained as `SOURCE_README.md` in the processed bundle.

## Quality and evaluation limits

All relational integrity checks pass. One low-confidence right-ear estimate
touches an exclusive ROI edge and is preserved with a warning. At confidence
threshold 0.5, 5,537 of 23,426 joints (23.6%) are below threshold. Confidence
does not verify correctness: occlusion can join different players' joints,
and detections may include referees, non-scrum players and duplicates.

Split membership is explicit and disjoint by match: Uruguay–Argentina XV
train (105 frames), Milano–Calvisano validation (48), Italy–Chile test (126).
This is a provisional three-match pilot with correlated frames, unequal split
sizes and strong camera/domain differences. It does not support reliable
claims about unseen matches, camera angles or competition levels.

Manual phase labels are initially absent. After annotation, independently
review boundaries, report class balance and reviewer agreement, retain an
untouched test group and collect more independent matches. Blank labels
must not be silently mapped to a class; draft labels must not be reported
as verified ground truth.
