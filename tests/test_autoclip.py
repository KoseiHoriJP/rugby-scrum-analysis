"""End-to-end local export checks; synthetic media is not a real scrum test."""

import copy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from autoclip import ClipError, export_clips, load_json, probe, scan, validate_manifest, write_json


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg/FFprobe required')
class AutoclipIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_temp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.media_temp.name) / 'synthetic_match.mp4'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=10',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000', '-t', '40',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', str(cls.video),
        ], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.media_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.transcript = self.base / 'transcript.json'
        write_json(self.transcript, {'words': [
            {'word': 'Crouch', 'start': 20., 'end': 20.4, 'probability': .9},
            {'word': 'bind', 'start': 22., 'end': 22.5, 'probability': .8},
            {'word': 'set!', 'start': 24., 'end': 24.5, 'probability': .9},
        ]})

    def scanned(self):
        return scan(self.video, self.base / 'run', transcript=self.transcript)

    def reviewed(self):
        manifest = self.scanned()
        event = manifest['events'][0]
        event.update(end_s=30., end_status='reviewed', camera_view='side', view_status='reviewed')
        path = self.base / 'reviewed.json'
        write_json(path, manifest)
        return manifest, path

    def test_scan_has_exact_lead_in_and_never_guesses_scrum_end(self):
        manifest = self.scanned()
        self.assertEqual(len(manifest['events']), 1)
        event = manifest['events'][0]
        self.assertEqual(event['start_s'], 5.)
        self.assertIsNone(event['end_s'])
        self.assertEqual(event['camera_view'], 'unknown')
        self.assertEqual(event['end_status'], 'needs_review')
        self.assertTrue((self.base / 'run' / 'review.html').is_file())

    def test_export_cuts_reviewed_interval_and_preserves_audio(self):
        _, path = self.reviewed()
        result = export_clips(self.video, path, self.base / 'export')
        self.assertEqual(result['clips_exported'], 1)
        clip = self.base / 'export' / 'side' / 'scrum_001.mp4'
        media = probe(clip)
        self.assertAlmostEqual(media['duration_s'], 25., delta=.15)
        self.assertTrue(media['audio_present'])
        with (self.base / 'export' / 'clips.csv').open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]['clip_path'], 'side/scrum_001.mp4')
        self.assertEqual(float(rows[0]['start_s']), 5.)
        self.assertEqual(float(rows[0]['end_s']), 30.)
        # Verify the retained picture begins at source time 5, not only that
        # the exported file has the requested length or metadata.
        def first_frame(path, time):
            return subprocess.check_output([
                'ffmpeg', '-v', 'error', '-ss', str(time), '-i', str(path),
                '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1',
            ])
        expected, actual = first_frame(self.video, 5), first_frame(clip, 0)
        self.assertEqual(len(expected), len(actual))
        self.assertLess(sum(abs(a - b) for a, b in zip(expected, actual)) / len(expected), 8.)

    def test_unreviewed_ends_prevent_exports_and_leave_no_output(self):
        self.scanned()
        with self.assertRaises(ClipError):
            export_clips(self.video, self.base / 'run/events.json', self.base / 'export')
        self.assertFalse((self.base / 'export').exists())

    def test_mixed_view_is_held_instead_of_misfiled_as_aerial(self):
        manifest, path = self.reviewed()
        manifest['events'][0]['camera_view'] = 'mixed'
        write_json(path, manifest)
        with self.assertRaises(ClipError):
            export_clips(self.video, path, self.base / 'export')
        self.assertFalse((self.base / 'export').exists())

    def test_wrong_source_hash_prevents_export(self):
        manifest, path = self.reviewed()
        manifest['source']['sha256'] = '0' * 64
        write_json(path, manifest)
        with self.assertRaisesRegex(ClipError, 'SHA-256'):
            export_clips(self.video, path, self.base / 'export')

    def test_rejects_unsafe_event_ids_and_invalid_endpoints(self):
        original, _ = self.reviewed()
        changes = [{'event_id': '../escaped'}, {'end_s': float('nan')}, {'end_s': 41.},
                   {'end_s': 23.}, {'start_s': 10.}, {'include': 'false'}]
        for change in changes:
            with self.subTest(change=change):
                manifest = copy.deepcopy(original)
                manifest['events'][0].update(change)
                with self.assertRaises(ClipError):
                    validate_manifest(manifest)

    def test_duplicate_events_rejected(self):
        manifest = self.scanned()
        manifest['events'].append(dict(manifest['events'][0]))
        with self.assertRaisesRegex(ClipError, 'Duplicate'):
            validate_manifest(manifest)

    def test_existing_scan_output_preserved(self):
        self.scanned()
        old = (self.base / 'run/events.json').read_bytes()
        with self.assertRaises(ClipError):
            scan(self.video, self.base / 'run', transcript=self.transcript)
        self.assertEqual((self.base / 'run/events.json').read_bytes(), old)

    def test_no_commands_produces_zero_candidates_without_claiming_no_scrums(self):
        write_json(self.transcript, {'words': []})
        manifest = self.scanned()
        self.assertEqual(manifest['events'], [])

    def test_early_crouch_marks_truncated_lead_in(self):
        speech = load_json(self.transcript)
        for word in speech['words']:
            word['start'] -= 15
            word['end'] -= 15
        write_json(self.transcript, speech)
        event = self.scanned()['events'][0]
        self.assertEqual(event['start_s'], 0.)
        self.assertTrue(event['lead_in_truncated'])


if __name__ == '__main__':
    unittest.main()
