# Rugby scrum datasets and Law 19 annotation

[English](README.md) | [日本語](README.ja.md)

Collect new scrum clips and annotate their timeline, evidence, applicable laws
and referee decisions with the full Law 19 workflow below.
For downloading and opening this version on a Mac, see the
[Japanese Mac start guide](docs/MAC_START.ja.md).

Prepare the supplied **Rugby Scrum Pilot Dataset** for manual scrum-phase annotation.
The first build preserves 279 sampled frames from five clips / three matches,
1,378 automatic person detections and 23,426 COCO keypoints. It does **not**
invent phase labels or treat YOLO estimates as verified human poses.

## Full Law 19 annotation workflow

For the new dataset, see the [full annotation specification](data/source_catalog/scrum_full_annotation_plan.md),
[clause-by-clause coverage](data/source_catalog/law19_rule_coverage.md), and
[blank annotation tables](data/source_catalog/annotation_templates_full/).
The new offline review page supports all seven tables, all 88 numbered
records, the restart table and source reference metadata. See the
[Law 19 workflow](docs/LAW19_WORKFLOW.md) for validation, evidence-based draft
checks and CSV export. Referenced image/video contents remain unreviewed.
Enter the match's competition, law edition and trial applicability; the supplied
World Rugby page does not establish a particular World Cup's regulations.

## Automate new scrum clips

Use [the Mac automatic clipping workflow](docs/AUTOMATIC_CLIPPING.md) to find
referee Crouch/Bind/Set candidates, confirm each actual scrum ending and camera
view in a browser, and batch-export clips into `aerial/` and `side/`. Every clip
starts 15 seconds before Crouch and retains the reviewed end and any marked
referee explanation; there is no
fixed ten-second cutoff. Optional camera-model suggestions remain unverified.

## Download

- [Dataset and offline labeling tool (5.2 MB)](https://github.com/KoseiHoriJP/rugby-scrum-analysis/raw/refs/heads/main/artifacts/Rugby_Scrum_Phase_Pilot_v1.zip)
- [Preparation code and original pilot metadata/previews (5.1 MB)](https://github.com/KoseiHoriJP/rugby-scrum-analysis/raw/refs/heads/main/artifacts/Rugby_Scrum_Dataset_Tools_v1.zip)
- [SHA-256 checksums](artifacts/SHA256SUMS)

Extract the dataset ZIP, open its `review.html` in Safari or Chrome, and label
the sampled frames. Keep `review.html` beside the bundled `previews/` folder.
Save drafts as JSON before closing or reloading the page. No installation is
needed to use the prebuilt labeling tool; labels are initially blank.

The tools ZIP contains a separate `rugby-scrum-analysis/` folder with the builder,
tests, documentation, and imported raw metadata/previews. To rebuild from that
folder, run `python scrum_dataset.py` (Python 3.10+ and FFprobe recommended).

## Build

Python 3.10+ is sufficient; no Python dependencies to install. FFprobe (from
FFmpeg) verifies preview frame counts and 5 fps timing. Without FFprobe,
metadata exports work but frame-aligned video annotation is disabled.

Run commands from this checkout (use the existing isolated checkout; no Git
worktree is needed):

```sh
# Import a fresh uploaded archive, validate, and build.
python scrum_dataset.py --archive /path/to/Archive.zip

# Or rebuild from the existing imported files into a NEW output version.
python scrum_dataset.py --input data/raw/pilot --output data/processed/pilot-v2

python -m unittest discover -s tests -v
```

The importer ignores macOS metadata and refuses unsafe paths and overwrites.
Raw working directories and generated exports are ignored by Git; the two
curated download ZIPs and their checksums are tracked. Original CSVs and their
coordinates remain unchanged. Input hashes and model provenance are recorded.

## Annotate scrum phases

Open `data/processed/pilot-v1/review.html` in a browser. Preview videos are bundled
in the adjacent `previews/` folder; keep the folder together. No upload, login,
server, or external library is needed. For a downloaded ZIP, extract it first.

Follow [the annotation guide](docs/ANNOTATION_GUIDE.md), enter a reviewer name,
watch the preview context and label the sampled frame. Labels are **drafts**
until independently reviewed. Export both JSON (to resume) and CSV (for analysis)
before leaving the page. Drafts are held in tab memory and are lost on reload;
resume from an exported JSON file.

The four target phases are `formation`, `engagement`, `drive`, `release`.
Use `not_scrum` or `uncertain` when appropriate; an empty field is unannotated.
Never assign a phase from YOLO detection confidence. Frame-level phase labels
apply to the scrum event, not to an individual person detection.

## Outputs

| File | Meaning |
| --- | --- |
| `frames.csv` | All sampled frames, time mappings, media availability and split |
| `splits/*.csv` | Match-disjoint train/validation/test frame manifests |
| `poses.jsonl` | One record per frame, including empty detection lists; 17 joints per detection |
| `frame_annotations.csv` | 279 blank manual phase labels with review fields |
| `phase_schema.json` | Label vocabulary, stable frame key and review-status semantics |
| `person_annotations.csv` | Optional person/pose review; no invented tracks |
| `review.html`, `previews/` | Offline draft annotation tool and five overlay videos |
| `validation_report.json` | Counts, confidence statistics, warnings and split sizes |
| `provenance.json`, `clips.csv` | Input checksums, processing metadata and original attribution |

`confidence_mask` means a model confidence at least the configured threshold
(default 0.5); it is **not** a visibility, correctness, or human review label.
Coordinates in `poses.jsonl` remain in full original-video pixels. Subtract ROI
offsets to map to crop coordinates; previews can have encoder padding on the
right/bottom and must not be resized as a substitute for the original image.
`detection_index` is local to a frame; `track_id` remains null.

## Pilot split and limitations

| Split | Match group | Clips | Frames |
| --- | --- | ---: | ---: |
| Train | Uruguay–Argentina XV, 2018 | 2 | 105 |
| Validation | Milano–Calvisano, 2010 | 1 | 48 |
| Test | Italy–Chile, 2025 | 2 | 126 |

The split is an explicit, provisional match-level holdout in
`configs/pilot_splits.json`, not a claimed 80/10/10 distribution. Only three
matches are available, with strong viewpoint/resolution differences. Do not
tune against the test match. This is an annotation/research pilot, not a basis
for reliable generalization claims.

The uploaded archive contains overlay previews but **no original videos**.
Those previews support phase review, not clean pose-training images. Place
original MP4s at the paths listed in `data/raw/pilot/clips.csv` when available.
They are needed before extracting clean images or re-running pose inference.
No pose inference or model training is performed by this builder. There are
currently **zero manually labeled frames**.

See [the dataset card](docs/DATASET_CARD.md) for scope and attribution. The
ten aerial candidate links are not downloaded or included as training data.
