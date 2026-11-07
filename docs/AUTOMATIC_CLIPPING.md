# Automatic scrum candidates and batch clipping on a Mac

The local workflow automates speech transcription, finding ordered **Crouch →
bind → set** sequences, and cutting reviewed events in a batch. You confirm the
actual scrum end and camera view in an offline browser page. Speech alone does
not reliably establish the end of the scrum; this tool never replaces the end
with a fixed number of seconds after Set.

No API key or paid service is needed. The first ASR run downloads a model. Video
files and transcripts stay on your computer; acquiring a remote source video
and downloading model weights use your normal Internet connection.

## One-time setup

Install [Homebrew](https://brew.sh/) if needed, then run in Terminal:

```sh
brew install python@3.12 ffmpeg yt-dlp
git clone https://github.com/KoseiHoriJP/rugby-scrum-analysis.git
cd rugby-scrum-analysis
python3.12 -m venv .venv-auto
source .venv-auto/bin/activate
python -m pip install -r requirements-autoclip.txt
```

If you already cloned the repository, update it instead of cloning a second
copy. The cloud task itself should keep its existing isolated checkout; no
extra Git worktree is needed.

For a guided local run with file dialogs, use:

```sh
bash scripts/label_match_macos.command
```

It selects a local match, scans its audio, opens the browser review page, then
asks you to select the reviewed JSON and exports the approved clips. The first
run installs the pinned speech dependency in `.venv-auto`. You still need to
mark actual endings and review camera views. The guided launcher targets Men's
Rugby World Cup 2023 with unverified historical rules context. Use the individual
commands below without that preset for other competitions. These commands
provide the same workflow with more control.

## 1. Supply a playable full match

Use a local MP4 you have access to, or download an accessible source:

```sh
python autoclip.py download --url "PASTE_THE_FULL_MATCH_YOUTUBE_URL_HERE" --output media/match01
```

Replace the placeholder with an actual video URL, not a channel search. The
download command requests a browser-compatible H.264 MP4 up to 1080p and keeps
audio. Downloads may fail if the source requires unavailable formats, login,
or geographic access; the tool does not bypass those restrictions. Official
All Blacks watch pages are not assumed to be downloadable with yt-dlp.

You can skip downloading and point the next commands at an existing MP4. Keep
that source file intact: the scanner records its SHA-256 and export rejects a
different file, even if its name matches.

## 2. Scan the referee commands automatically

```sh
python autoclip.py scan --video media/match01/match.mp4 --output runs/match01
open runs/match01/review.html
```

`small.en` is the default English speech model, using CPU/int8. Larger models
can be selected with `--model medium.en` if needed; a local model folder is
also accepted. Models consume disk space and a full-match scan can take time.
No accuracy or processing-speed benchmark is claimed for this footage.

The scan saves word-timestamped `transcript.json`, draft `events.json` and the
offline review page. Candidates require all three exact commands in order
within 20 seconds; a new Crouch restarts a pending sequence. The start is
15 seconds before Crouch, clamped at zero when the recording starts too late.
It is a source-video timestamp, not the scoreboard's match clock.

Background noise may hide a command; commentators may repeat the same words.
ASR confidence does not identify the referee. Candidates are not verified
scrums, and zero detections do not prove there are no scrums in the video.
Inspect for missed events; if needed correct the word timestamps in a copy of
the transcript and rescan into a new output directory with:

```sh
python autoclip.py scan --video media/match01/match.mp4 --transcript corrected-transcript.json --output runs/match01-corrected
```

## 3. Review the event and Law 19 evidence

In `review.html`, select the same local video, inspect each proposed event, and
reject any false positive. Play through the scrum and mark its observed end.
Whistles may signal resets, so judge the visible event and audio together.
Confirm the speech cues, choose its camera view and explicitly mark it reviewed.
The default page now supports [all seven Law 19 tables](LAW19_WORKFLOW.md),
including rules context, observations, assessments and actual referee decisions.
Mark the physical scrum end separately from any later referee explanation,
and set the retained clip end to cover both. Save `law19_reviewed_events.json`
before closing the tab. Browser memory alone is not persistent storage.

`aerial` means an overhead view of the scrum. `side` means a sideline/oblique
view. If a broadcast changes between these during the event window, use
`mixed`; do not label an entire event aerial because one replay is overhead.
An overhead replay without the lead-in and referee commands is a separate
sample, not a replacement for the requested complete event.

## 4. Export every reviewed clip automatically

Use the actual path/name of the JSON downloaded by the review page:

```sh
python autoclip.py export --video media/match01/match.mp4 --events "$HOME/Downloads/law19_reviewed_events.json" --output datasets/match01
```

Clips are encoded as H.264 MP4 with AAC audio, split into `aerial/` and `side/`.
Each runs from Crouch −15 seconds through the retained end, including any
recorded referee explanation. V2 exports also include all seven annotation
tables in `annotations/`. Existing
files/directories are never overwritten. Mixed/unknown views, rejected
candidates and unreviewed ends are held back, with reasons in
`export_report.json`. `clips.csv` records source/clip hashes and original
timestamps so cuts can be traced back to the match.

All clips from the same match must stay in one train/validation/test split.
The source-video hash groups clips from one file; alternate recordings of the
same match still require a shared `match_group` to avoid leakage.

## Optional: camera-view suggestions

After marking ends, an optional generic CLIP model can suggest views:

```sh
python -m pip install -r requirements-autoclip-vision.txt
python autoclip.py suggest-views --video media/match01/match.mp4 --events "$HOME/Downloads/law19_reviewed_events.json" --output runs/match01/view-suggestions.json
```

Resume that JSON in the review page and visually check its suggestions.
For older collection-only v1 JSON, run `review-laws` first to migrate it.
Already-reviewed views are preserved. Other results stay unverified and cannot
be exported until explicitly reviewed. This model is not trained or validated
for scrum camera classification. Seven sampled frames can miss a camera cut;
its softmax scores are not calibrated accuracy estimates. It does not verify
that all players are visible or that poses are anatomically correct.

## Validation and limits

```sh
python -m unittest discover -s tests -v
```

Tests exercise cue ordering, malformed timestamps, false/held candidates,
source identity, and actual FFmpeg extraction with synthetic video/audio.
Model adapters are tested separately from model accuracy. No new real-match
scrum clips or speech/vision accuracy results were produced in the cloud:
YouTube delivery remains inaccessible and model weights were not downloaded.
A fully automatic, trustworthy end/view classifier would require reviewed
scrum footage, model training and match-disjoint evaluation. This workflow
helps create those reviewed examples without silently inventing labels.
