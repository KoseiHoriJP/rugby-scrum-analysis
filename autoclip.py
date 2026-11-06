"""Find scrum speech cues, review real endings, and batch-export local clips."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from automation.cues import detect_sequences, transcribe_video


class ClipError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise ClipError(message)


def finite(value, name):
    check(not isinstance(value, bool) and isinstance(value, (int, float)), f"{name} must be numeric")
    check(math.isfinite(value), f"{name} must be finite")
    return float(value)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def run(command):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ClipError(f"Required tool is missing: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise ClipError(f"{command[0]} failed: {(exc.stderr or exc.stdout)[-2000:]}") from exc


def probe(video):
    path = Path(video).resolve()
    check(path.is_file(), f"Video does not exist: {path}")
    result = run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                  '-show_format', '-show_streams', '-of', 'json', str(path)])
    info = json.loads(result.stdout)
    check(any(s.get('codec_type') == 'video' for s in info.get('streams', [])), 'Input has no video stream')
    try:
        duration = float(info['format']['duration'])
    except (KeyError, ValueError, TypeError) as exc:
        raise ClipError('Input requires a known, finite duration') from exc
    check(math.isfinite(duration) and duration > 0, 'Invalid video duration')
    return {'duration_s': duration,
            'audio_present': any(s.get('codec_type') == 'audio' for s in info.get('streams', []))}


def source_info(video):
    return {'filename': Path(video).name, 'sha256': digest(video), 'duration_s': probe(video)['duration_s']}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ClipError(f"Cannot read JSON: {path}: {exc}") from exc


def validate_manifest(data, source=None):
    check(isinstance(data, dict) and type(data.get('schema_version')) is int and data['schema_version'] == 1,
          'Expected scrum manifest schema_version 1')
    src = data.get('source')
    check(isinstance(src, dict), 'Manifest is missing source metadata')
    check(isinstance(src.get('filename'), str) and src['filename'], 'Invalid source filename')
    check(isinstance(src.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', src['sha256']), 'Invalid source SHA-256')
    duration = finite(src.get('duration_s'), 'source.duration_s')
    check(duration > 0, 'Source duration must be positive')
    if source:
        check(src['sha256'] == source['sha256'], 'Selected video SHA-256 does not match the scanned match')
        check(abs(duration - source['duration_s']) <= 0.05, 'Source video duration mismatch')
    events = data.get('events')
    check(isinstance(events, list), 'events must be a list')
    ids = set()
    for e in events:
        check(isinstance(e, dict), 'Each event must be an object')
        eid = e.get('event_id')
        check(isinstance(eid, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', eid), 'Unsafe event_id')
        check(eid not in ids, f"Duplicate event_id: {eid}")
        ids.add(eid)
        crouch, bind, set_ = [finite(e.get(k), k) for k in ['crouch_s', 'bind_s', 'set_s']]
        check(0 <= crouch < bind < set_ < duration, f"Invalid cue order/bounds: {eid}")
        start = finite(e.get('start_s'), 'start_s')
        check(abs(start - max(0, crouch - 15)) < 1e-6, f"Start must be 15 seconds before Crouch (clamped at zero): {eid}")
        check(type(e.get('include')) is bool, f"include must be true/false: {eid}")
        check(e.get('end_status') in {'needs_review', 'reviewed'}, f"Invalid end_status: {eid}")
        check(e.get('view_status') in {'unverified', 'reviewed'}, f"Invalid view_status: {eid}")
        check(e.get('camera_view') in {'aerial', 'side', 'mixed', 'unknown'}, f"Invalid camera_view: {eid}")
        end = e.get('end_s')
        if end is not None:
            end = finite(end, 'end_s')
            check(set_ < end <= duration, f"End must be after Set and within the source video: {eid}")
        check(e['end_status'] != 'reviewed' or end is not None, f"Reviewed end needs an actual end time: {eid}")
        check(isinstance(e.get('notes', ''), str), f"notes must be text: {eid}")
    return data


def render_review(directory, manifest):
    template = Path(__file__).parent / 'templates' / 'scrum_review.html'
    check(template.is_file(), 'Scrum review template is missing')
    payload = json.dumps(manifest, ensure_ascii=False, allow_nan=False)
    payload = payload.replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    (directory / 'review.html').write_text(template.read_text(encoding='utf-8').replace('__SCRUM_EVENTS_JSON__', payload), encoding='utf-8')


def scan(video, output, transcript=None, model='small.en', max_sequence_seconds=20.0, model_dir=None):
    video, output = Path(video).resolve(), Path(output)
    check(not output.exists(), 'Output exists; use a new run directory to preserve prior work')
    details = probe(video)
    if transcript:
        speech = load_json(transcript)
        check(isinstance(speech, dict) and isinstance(speech.get('words'), list), 'Transcript JSON needs a words list with word/start/end timestamps')
        method = 'imported_word_transcript'
    else:
        check(details['audio_present'], 'Input has no audio; referee cue detection requires audio')
        print('Transcribing match audio. The first run may download model weights; a full match can take time.',
              file=sys.stderr, flush=True)
        speech = transcribe_video(video, model_name=model, model_dir=model_dir)
        method = 'faster_whisper'
    candidates = detect_sequences(speech['words'], max_sequence_seconds=max_sequence_seconds)
    events = []
    for i, cue in enumerate(candidates, 1):
        check(cue['set_s'] < details['duration_s'], 'Transcript contains cues outside the source video')
        events.append({**cue, 'event_id': f'scrum_{i:03}', 'start_s': max(0, cue['crouch_s'] - 15),
                       'lead_in_truncated': cue['crouch_s'] < 15, 'end_s': None, 'end_status': 'needs_review',
                       'camera_view': 'unknown', 'view_status': 'unverified', 'include': True, 'notes': ''})
    manifest = {'schema_version': 1, 'source': source_info(video),
                'detection': {'method': method, 'model': speech.get('model'), 'lead_seconds': 15,
                              'max_sequence_seconds': max_sequence_seconds}, 'events': events}
    validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.scrum-scan-', dir=output.parent) as temp:
        staging = Path(temp) / 'run'
        staging.mkdir()
        write_json(staging / 'transcript.json', speech)
        write_json(staging / 'events.json', manifest)
        render_review(staging, manifest)
        (staging / 'START_HERE.txt').write_text(
            'Open review.html in Safari/Chrome and select the same source match video.\n'
            'Listen to each candidate; reject commentary/false positives. Mark the observed scrum end and review the camera view.\n'
            'Save reviewed JSON before closing. Export clips with autoclip.py export.\n'
            'No real scrum endings or camera views have been inferred by the speech scan.\n', encoding='utf-8')
        check(not output.exists(), 'Output appeared during scan; refusing overwrite')
        staging.rename(output)
    return manifest


def ready_events(manifest):
    ready, held = [], []
    for event in manifest['events']:
        if not event['include']:
            held.append({'event_id': event['event_id'], 'reason': 'rejected_by_reviewer'})
        elif event['end_status'] != 'reviewed' or event['end_s'] is None:
            held.append({'event_id': event['event_id'], 'reason': 'scrum_end_needs_review'})
        elif event['view_status'] != 'reviewed':
            held.append({'event_id': event['event_id'], 'reason': 'camera_view_needs_review'})
        elif event['camera_view'] not in {'aerial', 'side'}:
            held.append({'event_id': event['event_id'], 'reason': 'mixed_or_unknown_view'})
        else:
            ready.append(event)
    return ready, held


def export_clips(video, events_path, output):
    video, output = Path(video).resolve(), Path(output)
    check(not output.exists(), 'Export output exists; use a new directory')
    source = source_info(video)
    source_has_audio = probe(video)['audio_present']
    manifest = validate_manifest(load_json(events_path), source=source)
    ready, held = ready_events(manifest)
    check(ready, 'No reviewed aerial/side events are ready; confirm actual scrum ends and camera views in review.html first')
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix='.scrum-export-', dir=output.parent) as temp:
        staging = Path(temp) / 'clips'
        staging.mkdir()
        for e in ready:
            relative = Path(e['camera_view']) / (e['event_id'] + '.mp4')
            target = staging / relative
            target.parent.mkdir(exist_ok=True)
            duration = e['end_s'] - e['start_s']
            run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-protocol_whitelist', 'file,pipe',
                 '-ss', str(e['start_s']), '-i', str(video), '-t', str(duration),
                 '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                 '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                 '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', '-map_metadata', '-1', str(target)])
            actual = probe(target)
            check(abs(actual['duration_s'] - duration) <= 0.25, f"Exported duration mismatch: {e['event_id']}")
            if source_has_audio:
                check(actual['audio_present'], f"Export lost source audio: {e['event_id']}")
            rows.append({'event_id': e['event_id'], 'source_video_sha256': source['sha256'],
                         'source_filename': source['filename'], 'clip_path': relative.as_posix(),
                         'camera_view': e['camera_view'], 'crouch_s': e['crouch_s'], 'set_s': e['set_s'],
                         'start_s': e['start_s'], 'end_s': e['end_s'],
                         'lead_in_truncated': e.get('lead_in_truncated', e['crouch_s'] < 15),
                         'duration_s': actual['duration_s'], 'clip_sha256': digest(target), 'status': 'reviewed'})
        with (staging / 'clips.csv').open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        write_json(staging / 'reviewed_events.json', manifest)
        write_json(staging / 'export_report.json', {'clips_exported': len(rows), 'held_events': held,
                                                   'audio_preserved': source_has_audio,
                                                   'split_guidance': 'Keep all clips from one match in the same split. The source SHA groups this file; alternate recordings of that match still need a common match_group.'})
        check(not output.exists(), 'Export output appeared; refusing overwrite')
        staging.rename(output)
    return {'clips_exported': len(rows), 'held_events': held}


def suggest_views(video, events_path, output, model='openai/clip-vit-base-patch32'):
    from automation.views import classify_view
    output = Path(output)
    check(not output.exists(), 'Suggestion JSON exists; use a new filename')
    manifest = validate_manifest(load_json(events_path), source=source_info(video))
    for e in manifest['events']:
        # Human-reviewed view labels are never overwritten by a model suggestion.
        if not e['include'] or e['end_s'] is None or e['view_status'] == 'reviewed':
            continue
        suggestion = classify_view(Path(video), e['start_s'], e['end_s'], model_name=model)
        e['view_suggestion'] = suggestion
        e['camera_view'] = suggestion['camera_view']
        e['view_status'] = 'unverified'
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, manifest)
    return manifest


def download_match(url, output):
    check(url.startswith(('https://', 'http://')), 'Supply an HTTP(S) match URL accessible to you')
    output = Path(output)
    check(not output.exists(), 'Download output exists; use a new directory')
    check(shutil.which('yt-dlp'), 'Install yt-dlp first (brew install yt-dlp)')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.scrum-download-', dir=output.parent) as temp:
        staging = Path(temp) / 'download'
        staging.mkdir()
        run(['yt-dlp', '--no-playlist', '--no-overwrites', '--no-progress',
             '-f', 'bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]',
             '--merge-output-format', 'mp4', '-o', str(staging / 'match.%(ext)s'), '--', url])
        check((staging / 'match.mp4').is_file(), 'No MP4 downloaded; use an accessible local match video')
        probe(staging / 'match.mp4')
        check(not output.exists(), 'Download output appeared; refusing overwrite')
        staging.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('download', help='Download a match URL through normal yt-dlp access')
    p.add_argument('--url', required=True)
    p.add_argument('--output', required=True, type=Path)
    p = commands.add_parser('scan', help='Propose ordered referee speech cues; ends remain unset')
    p.add_argument('--video', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--transcript', type=Path, help='Existing JSON with word/start/end records; skips ASR')
    p.add_argument('--model', default='small.en', help='Faster Whisper model name or local model folder')
    p.add_argument('--model-dir', type=Path)
    p.add_argument('--max-sequence-seconds', type=float, default=20.0)
    p = commands.add_parser('suggest-views', help='Optional unverified CLIP view suggestions for events with marked ends')
    p.add_argument('--video', required=True, type=Path)
    p.add_argument('--events', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--model', default='openai/clip-vit-base-patch32')
    p = commands.add_parser('export', help='Batch-export only human-reviewed aerial and side events')
    p.add_argument('--video', required=True, type=Path)
    p.add_argument('--events', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'scan':
            result = scan(args.video, args.output, args.transcript, args.model, args.max_sequence_seconds, args.model_dir)
            print(f"Found {len(result['events'])} automatic candidates. Open {args.output / 'review.html'} to review them.")
        elif args.command == 'export':
            print(json.dumps(export_clips(args.video, args.events, args.output), indent=2))
        elif args.command == 'suggest-views':
            suggest_views(args.video, args.events, args.output, args.model)
            print(f'Saved model suggestions for human review: {args.output}')
        elif args.command == 'download':
            download_match(args.url, args.output)
            print(f'Downloaded {args.output / "match.mp4"}')
    except (ClipError, ValueError, RuntimeError, OSError, ImportError) as exc:
        parser.exit(1, f'Autoclip error: {exc}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
