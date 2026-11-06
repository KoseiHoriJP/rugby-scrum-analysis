#!/bin/bash
# Run locally on macOS: bash scripts/label_match_macos.command
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != Darwin ]]; then
  echo "This launcher requires macOS. Use autoclip.py directly on other systems."
  exit 1
fi
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Install the prerequisites first: brew install python@3.12 ffmpeg"
  exit 1
fi
if command -v python3.12 >/dev/null; then
  autoclip_python=python3.12
elif command -v python3 >/dev/null; then
  autoclip_python=python3
else
  echo "Install Python first: brew install python@3.12"
  exit 1
fi
"$autoclip_python" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required; install python@3.12"'
if [[ ! -x .venv-auto/bin/python ]]; then
  "$autoclip_python" -m venv .venv-auto
fi
.venv-auto/bin/python -m pip install --disable-pip-version-check -r requirements-autoclip.txt

if [[ $# -gt 0 ]]; then
  autoclip_video="$1"
else
  autoclip_video="$(osascript -e 'POSIX path of (choose file with prompt "Select your full-match MP4 with referee audio")')"
fi
autoclip_run="runs/match-$(date +%Y%m%d-%H%M%S)"
.venv-auto/bin/python autoclip.py scan --video "$autoclip_video" --output "$autoclip_run"
open "$autoclip_run/review.html"
echo "In the browser, select the same match file. Check the candidates, mark actual ends, confirm views, and save the reviewed JSON."
read -r -p "Press Return after you have saved your reviewed JSON (or Ctrl+C to export later): " autoclip_continue
autoclip_events="$(osascript -e 'POSIX path of (choose file with prompt "Select the reviewed scrum-events JSON you saved from the browser")')"
autoclip_output="datasets/match-$(date +%Y%m%d-%H%M%S)"
.venv-auto/bin/python autoclip.py export --video "$autoclip_video" --events "$autoclip_events" --output "$autoclip_output"
open "$autoclip_output"
echo "Finished. Aerial and side clips are in $autoclip_output. Mixed and unreviewed events remain held."
