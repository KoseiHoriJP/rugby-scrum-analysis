"""Full-law collection integration using synthetic media, not referee accuracy."""

import copy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from autoclip import (ClipError, apply_ruleset_preset, check_laws, export_clips, law_document, load_json,
                      probe, ready_events, review_laws, scan, write_json)
from law_annotations import AnnotationError, load_assets, validate_document


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class LawWorkflowTests(unittest.TestCase):
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
        transcript = self.base / 'transcript.json'
        write_json(transcript, {'words': [
            {'word': word, 'start': time, 'end': time + .4}
            for word, time in [('Crouch', 20.), ('bind', 22.), ('set', 24.)]
        ]})
        self.legacy = scan(self.video, self.base / 'scan', transcript=transcript)
        self.document = load_json(self.base / 'scan/events-law19.json')

    def row(self, table, **fields):
        row = {column: None for column in load_assets()['schema']['tables'][table]['columns']}
        defaults = {'review_status': 'unreviewed', 'mapping_status': 'unmapped',
                    'law_mapping_status': 'unmapped', 'applicability_status': 'unknown',
                    'assessment_status': 'unreviewed', 'observability': 'unreviewed',
                    'context_status': 'unknown', 'identity_status': 'unknown',
                    'track_review_status': 'unreviewed', 'referee_decision': 'unknown'}
        row.update({key: value for key, value in defaults.items() if key in row})
        row.update(fields)
        return row

    def reviewed_clip(self):
        event = self.document['tables']['events'][0]
        event.update(cue_status='reviewed', attempt_end_s=30., end_status='reviewed',
                     explanation_end_s=34., clip_end_s=34., camera_view='side', view_status='reviewed')
        return event

    def test_scan_defaults_to_full_review_and_retains_original_collection(self):
        self.assertEqual(self.document['schema_version'], 2)
        self.assertEqual(self.document['extensions']['legacy_collection_manifest'], self.legacy)
        event = self.document['tables']['events'][0]
        self.assertEqual(event['cue_status'], 'unverified')
        self.assertEqual(event['audio_status'], 'present')
        self.assertEqual(event['review_status'], 'unreviewed')
        self.assertEqual(len(self.document['tables']), 7)
        self.assertIn('Law 19', (self.base / 'scan/review.html').read_text())
        self.assertTrue((self.base / 'scan/legacy_clip_review.html').is_file())

    def test_rwc2023_preset_records_target_without_verifying_historical_rules(self):
        document = apply_ruleset_preset(self.document, 'rwc2023')
        event = document['tables']['events'][0]
        self.assertEqual(event['competition'], "Men's Rugby World Cup 2023")
        self.assertEqual(event['context_status'], 'unverified')
        self.assertIsNone(event['law_edition'])
        self.assertEqual(event['trial_context'], 'unknown')
        self.assertFalse(document['extensions']['ruleset_target']['reference_edition_verified_for_competition'])
        event['ruleset_id'] = 'other_competition'
        before = copy.deepcopy(document)
        with self.assertRaises(ClipError): apply_ruleset_preset(document, 'rwc2023')
        self.assertEqual(document, before)

    def test_law_suggestions_do_not_change_human_assessments(self):
        assessment = self.row('rule_assessments', assessment_id='a1', event_id='scrum_001',
                              law_clause='19.37(d)', assessment_status='not_observable',
                              review_status='reviewed', notes='Collapse is not proof of intent.')
        self.document['tables']['rule_assessments'].append(assessment)
        path = self.base / 'annotated.json'
        write_json(path, self.document)
        before = copy.deepcopy(self.document['tables'])
        result = check_laws(path, self.base / 'checked.json')
        self.assertEqual(result['tables'], before)
        self.assertEqual(len(result['extensions']['rule_check_suggestions']['items']), 88)
        with self.assertRaises(FileExistsError):
            check_laws(path, self.base / 'checked.json')
        self.assertEqual(load_json(self.base / 'checked.json')['tables'], before)

    def test_review_resumes_losslessly_and_escapes_embedded_source_text(self):
        self.document['tables']['events'][0]['notes'] = '</script><script>window.bad=true</script>'
        self.document['extensions']['custom'] = {'keep': [1, False, None]}
        path = self.base / 'annotated.json'
        write_json(path, self.document)
        result = review_laws(path, self.base / 'resume', self.video)
        self.assertEqual(result, self.document)
        self.assertEqual(load_json(self.base / 'resume/events-law19.json'), self.document)
        html = (self.base / 'resume/review.html').read_text()
        self.assertNotIn('</script><script>window.bad=true</script>', html)
        self.assertIn('\\u003c/script>', html)

    def test_full_export_retains_explanation_and_all_tables_without_approving_law_labels(self):
        self.reviewed_clip()
        self.document['tables']['decisions'].append(self.row(
            'decisions', decision_id='d1', event_id='scrum_001', decision_index=1,
            decision_time_s=30., referee_decision='reset', referee_reason_verbatim='Reset, no infringement.',
            reason_speaker='referee', explanation_end_s=34., review_status='draft'))
        path = self.base / 'annotated.json'
        write_json(path, self.document)
        result = export_clips(self.video, path, self.base / 'export')
        self.assertEqual(result['clips_exported'], 1)
        media = probe(self.base / 'export/side/scrum_001.mp4')
        self.assertAlmostEqual(media['duration_s'], 29., delta=.2)
        self.assertTrue(media['audio_present'])
        with (self.base / 'export/clips.csv').open() as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual(float(row['attempt_end_s']), 30.)
        self.assertEqual(float(row['clip_end_s']), 34.)
        self.assertEqual(row['status'], 'clip_reviewed')
        self.assertEqual(row['law_review_status'], 'unreviewed')
        exported = load_json(self.base / 'export/annotations/manifest.json')
        self.assertEqual(exported, self.document)
        for table in self.document['tables']:
            self.assertTrue((self.base / f'export/annotations/{table}.csv').is_file())
        self.assertEqual(exported['tables']['rule_assessments'], [])

    def test_unreviewed_speech_is_held_even_with_reviewed_clip_bounds(self):
        self.reviewed_clip()['cue_status'] = 'unverified'
        ready, held = ready_events(validate_document(self.document))
        self.assertEqual(ready, [])
        self.assertEqual(held[0]['reason'], 'speech_cues_need_review')

    def test_truncating_referee_explanation_is_rejected_before_output(self):
        self.reviewed_clip()['clip_end_s'] = 31.
        path = self.base / 'annotated.json'
        write_json(path, self.document)
        with self.assertRaises(AnnotationError):
            export_clips(self.video, path, self.base / 'invalid-export')
        self.assertFalse((self.base / 'invalid-export').exists())

    def test_different_source_is_rejected_before_creating_review(self):
        self.document['source']['sha256'] = '0' * 64
        self.document['tables']['events'][0]['source_video_sha256'] = '0' * 64
        path = self.base / 'wrong.json'
        write_json(path, self.document)
        with self.assertRaisesRegex(AnnotationError, 'SHA-256'):
            review_laws(path, self.base / 'invalid-review', self.video)
        self.assertFalse((self.base / 'invalid-review').exists())


if __name__ == '__main__':
    unittest.main()
