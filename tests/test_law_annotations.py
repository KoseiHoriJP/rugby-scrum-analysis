"""Runtime table integrity and lossless collection migration."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from law_annotations import (AnnotationError, STATUS_DEFAULTS, export_tables,
                             load_assets, upgrade_manifest, validate_document)


class LawAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.legacy = {'schema_version': 1, 'source': {'filename': 'synthetic.mp4',
                       'sha256': 'a' * 64, 'duration_s': 100.},
                       'custom': {'keep': [True, None, '日本語']}, 'events': [{
                           'event_id': 's1', 'crouch_s': 20., 'bind_s': 22., 'set_s': 24.,
                           'start_s': 5., 'end_s': 30., 'include': True, 'end_status': 'reviewed',
                           'camera_view': 'side', 'view_status': 'reviewed',
                           'cue_status': 'automatic_candidate', 'notes': '',
                           'custom_rule_data': {'retain': True}}]}
        self.doc = upgrade_manifest(self.legacy)
        self.schema = load_assets()['schema']

    def row(self, table, **values):
        row = {name: None for name in self.schema['tables'][table]['columns']}
        row.update({key: value for key, value in STATUS_DEFAULTS.items() if key in row})
        row.update(values)
        return row

    def test_migration_preserves_full_legacy_and_starts_law_review_unreviewed(self):
        self.assertEqual(self.doc['extensions']['legacy_collection_manifest'], self.legacy)
        self.assertEqual(self.doc['tables']['events'][0]['cue_status'], 'unverified')
        self.assertEqual(self.doc['tables']['events'][0]['review_status'], 'unreviewed')
        self.assertIsNone(self.doc['tables']['events'][0]['explanation_end_s'])
        self.doc['extensions']['legacy_collection_manifest']['custom']['keep'].append('new')
        self.assertEqual(len(self.legacy['custom']['keep']), 3)

    def test_all_source_materials_are_available_to_runtime(self):
        assets = load_assets()
        self.assertEqual(len(assets['clauses']), 88)
        self.assertEqual(len(assets['restart_cases']), 17)
        self.assertEqual(len(assets['videos']), 31)
        self.assertEqual(len(assets['observation_fields']['fields']), 179)
        self.assertIn('document', assets)

    def test_mixed_view_can_be_reviewed_without_becoming_clip_ready(self):
        self.doc['tables']['events'][0]['camera_view'] = 'mixed'
        validate_document(self.doc)

    def test_validation_is_nonmutating(self):
        before = copy.deepcopy(self.doc)
        self.assertIs(validate_document(self.doc), self.doc)
        self.assertEqual(self.doc, before)

    def test_rejects_path_ids_duplicates_unknown_columns_and_missing_tables(self):
        for bad_id in ('../outside', '/workspace/outside', 'a/b', ''):
            with self.subTest(bad_id=bad_id):
                doc = copy.deepcopy(self.doc)
                doc['tables']['events'][0]['event_id'] = bad_id
                with self.assertRaises(AnnotationError): validate_document(doc)
        doc = copy.deepcopy(self.doc)
        doc['tables']['events'].append(copy.deepcopy(doc['tables']['events'][0]))
        with self.assertRaisesRegex(AnnotationError, 'Duplicate'): validate_document(doc)
        doc = copy.deepcopy(self.doc)
        doc['tables']['events'][0]['new_data'] = 'must preserve explicitly'
        with self.assertRaisesRegex(AnnotationError, 'extras'): validate_document(doc)
        del self.doc['tables']['teams']
        with self.assertRaises(AnnotationError): validate_document(self.doc)

    def test_rejects_invalid_types_bounds_and_statuses(self):
        for change in ({'include': 'true'}, {'attempt_end_s': float('nan')},
                       {'clip_end_s': 101.}, {'clip_start_s': 9.}, {'cue_status': 'automatic_candidate'},
                       {'context_status': 'verified'}, {'attempt_end_s': 23.}):
            doc = copy.deepcopy(self.doc)
            doc['tables']['events'][0].update(change)
            with self.subTest(change=change), self.assertRaises(AnnotationError): validate_document(doc)

    def test_reviewed_compliance_requires_verified_context_and_reviewed_source_evidence(self):
        assessment = self.row('rule_assessments', assessment_id='a1', event_id='s1',
                              law_clause='19.17', assessment_status='not_satisfied',
                              applicability_status='applicable', review_status='reviewed',
                              source_law_sha256=self.schema['source']['sha256'])
        self.doc['tables']['rule_assessments'].append(assessment)
        with self.assertRaisesRegex(AnnotationError, 'context'): validate_document(self.doc)
        self.doc['tables']['events'][0].update(context_status='verified',
                                              ruleset_id='synthetic_ruleset', law_edition='synthetic_edition')
        with self.assertRaisesRegex(AnnotationError, 'supporting'): validate_document(self.doc)
        obs = self.row('observations', observation_id='o1', event_id='s1',
                       observation_type='push_start_time_s', observed_value_json=25.,
                       evidence_type='video', evidence_path='synthetic.mp4#t=25',
                       observability='observable', review_status='reviewed')
        self.doc['tables']['observations'].append(obs)
        assessment['supporting_observation_ids'] = ['o1']
        validate_document(self.doc)
        obs['review_status'] = 'draft'
        with self.assertRaisesRegex(AnnotationError, 'reviewed observable'): validate_document(self.doc)

    def test_foreign_keys_and_clause_vocabulary_are_checked(self):
        self.doc['tables']['observations'].append(self.row(
            'observations', observation_id='o1', event_id='missing', observation_type='push_start_time_s'))
        with self.assertRaises(AnnotationError): validate_document(self.doc)
        self.doc['tables']['observations'][0]['event_id'] = 's1'
        self.doc['tables']['events'][0]['evidence_ids'] = ['missing']
        with self.assertRaises(AnnotationError): validate_document(self.doc)
        self.doc['tables']['events'][0]['evidence_ids'] = ['o1']
        self.doc['tables']['observations'][0]['observation_type'] = 'invented'
        with self.assertRaisesRegex(AnnotationError, 'observation_type'): validate_document(self.doc)

    def test_retains_every_decision_explanation_and_rejects_unsupported_attribution(self):
        decision = self.row('decisions', decision_id='d1', event_id='s1', explanation_end_s=34.)
        self.doc['tables']['decisions'].append(decision)
        with self.assertRaisesRegex(AnnotationError, 'explanation'): validate_document(self.doc)
        self.doc['tables']['events'][0]['clip_end_s'] = 34.
        validate_document(self.doc)
        decision['offending_player_number'] = 3
        with self.assertRaisesRegex(AnnotationError, 'attribution_basis'): validate_document(self.doc)

    def test_export_all_tables_and_full_json_atomically_without_overwriting(self):
        self.doc['extensions']['custom'] = {'日本語': [1, False, None]}
        obs = self.row('observations', observation_id='o1', event_id='s1',
                       observation_type='push_start_time_s', observed_value_json={'time_s': 25., 'visible': False})
        self.doc['tables']['observations'].append(obs)
        self.doc['tables']['events'][0]['evidence_ids'] = ['o1']
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'export'
            result = export_tables(self.doc, output)
            self.assertFalse(result['training_approved'])
            self.assertEqual(json.loads((output / 'manifest.json').read_text()), self.doc)
            for table in self.doc['tables']:
                with (output / f'{table}.csv').open() as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, self.schema['tables'][table]['columns'])
            with (output / 'observations.csv').open() as handle:
                stored = next(csv.DictReader(handle))
            self.assertEqual(json.loads(stored['observed_value_json']), obs['observed_value_json'])
            with self.assertRaises(AnnotationError): export_tables(self.doc, output)
            self.assertEqual(json.loads((output / 'manifest.json').read_text()), self.doc)

    def test_source_fingerprint_is_checked(self):
        wrong = dict(self.doc['source'], sha256='b' * 64)
        with self.assertRaisesRegex(AnnotationError, 'SHA-256'): validate_document(self.doc, wrong)


if __name__ == '__main__': unittest.main()
