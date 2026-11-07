"""Offline browser checks for lossless annotations and atomic resume imports."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from law_annotations import load_assets, review_payload, validate_document


ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_AVAILABLE = importlib.util.find_spec("playwright") is not None
CHROMIUM = shutil.which("chromium")


def annotation_fixture():
    schema = load_assets()["schema"]
    defaults = {
        "review_status": "unreviewed", "track_review_status": "unreviewed",
        "context_status": "unknown", "identity_status": "unknown",
        "applicability_status": "unknown", "assessment_status": "unreviewed",
        "mapping_status": "unmapped", "law_mapping_status": "unmapped",
        "end_status": "needs_review", "view_status": "unverified",
        "cue_status": "unverified", "camera_view": "unknown",
        "audio_status": "unknown", "observability": "unreviewed",
        "referee_decision": "unknown",
    }

    def row(table, **fields):
        result = {key: defaults.get(key) for key in schema["tables"][table]["columns"]}
        result.update(fields)
        return result

    sha = "b" * 64
    tables = {table: [] for table in schema["tables"]}
    tables["events"].append(row(
        "events", event_id="scrum_001", source_video_sha256=sha,
        crouch_s=20., bind_s=22., set_s=24., clip_start_s=5.,
        attempt_end_s=30., explanation_end_s=34., clip_end_s=34.,
        include=True, competition="Unverified competition", evidence_ids=["obs_1"],
        notes="Literal text: </script><script>window.bad=true</script>",
    ))
    tables["teams"].append(row(
        "teams", team_observation_id="team_1", event_id="scrum_001",
        team_id="blue", players_in_scrum=8, evidence_ids=["obs_1"],
    ))
    tables["participants"].append(row(
        "participants", participant_observation_id="participant_1", event_id="scrum_001",
        participant_id="player_candidate", identity_status="candidate", jersey_number=3,
    ))
    tables["restarts"].append(row(
        "restarts", restart_id="restart_1", event_id="scrum_001",
        restart_table_row_id="restart_01", restart_reason_text="Reviewed separately",
    ))
    tables["observations"].append(row(
        "observations", observation_id="obs_1", event_id="scrum_001",
        observation_type="actor_player_id", start_s=25., end_s=28.,
        observed_value_json={"visible": False, "candidate": None, "labels": [1, "two"]},
        evidence_type="video", observability="partly_observable", review_status="draft",
    ))
    tables["rule_assessments"].append(row(
        "rule_assessments", assessment_id="assessment_1", event_id="scrum_001",
        law_clause="19.37(d)", assessment_status="not_observable", review_status="draft",
        supporting_observation_ids=["obs_1"], rule_context={"intent_established": False},
        source_law_sha256=schema["source"]["sha256"],
    ))
    tables["decisions"].append(row(
        "decisions", decision_id="decision_1", event_id="scrum_001", decision_index=1,
        referee_decision="reset", referee_reason_verbatim="Reset", explanation_end_s=34.,
        review_status="draft",
    ))
    document = {
        "schema_version": 2, "schema_id": "law19_full_annotation_v2",
        "source": {"filename": "synthetic_match.mp4", "sha256": sha, "duration_s": 40.},
        "tables": tables,
        "extensions": {"custom": {"preserve": [None, False, 0, {"unicode": "日本語"}] }},
    }
    return validate_document(document)


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE and CHROMIUM, "Playwright and Chromium required")
class Law19BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(
                executable_path=CHROMIUM, headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as error:
            cls.playwright.stop()
            raise unittest.SkipTest(f"Chromium could not launch: {str(error).splitlines()[0]}") from error

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.document = annotation_fixture()
        self.page = self.browser.new_page(accept_downloads=True)
        self.addCleanup(self.page.close)
        self.render(self.document)

    def render(self, document):
        payload = review_payload(document)
        payload.setdefault("document", json.loads(
            (ROOT / "data/source_catalog/law19_full/law19_document.json").read_text()))
        payload.setdefault("observation_fields", json.loads(
            (ROOT / "data/source_catalog/annotation_templates_full/observation_field_registry.json").read_text()))
        payload.setdefault("suggestions", [])
        encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
        template = (ROOT / "templates/law19_review.html").read_text()
        self.page.set_content(template.replace("__LAW19_REVIEW_DATA__", encoded))
        self.page.wait_for_function("window.Law19Review && window.Law19Review.getManifest")

    def imported(self, document):
        old_message = self.page.locator("#message").inner_text()
        self.page.locator("#import-json").set_input_files({
            "name": "annotations.json", "mimeType": "application/json",
            "buffer": json.dumps(document).encode(),
        })
        self.page.wait_for_function(
            "old => document.querySelector('#message').textContent !== old", arg=old_message)

    def test_download_and_resume_preserve_all_tables_and_extensions(self):
        self.assertEqual(self.page.evaluate("window.Law19Review.getManifest()"), self.document)
        self.assertFalse(self.page.evaluate("Boolean(window.bad)"))
        self.assertEqual(self.page.locator('#law-select option[value^="19."]').count(), 88)
        with self.page.expect_download() as download_info:
            self.page.locator("#save-json").click()
        download = download_info.value
        self.assertEqual(download.suggested_filename, "law19_reviewed_events.json")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "saved.json"
            download.save_as(target)
            saved = json.loads(target.read_text())
        self.assertEqual(saved, self.document)
        self.assertEqual(validate_document(saved), self.document)
        resumed = copy.deepcopy(saved)
        resumed["extensions"]["resume_marker"] = {"all_seven_tables": True}
        self.imported(resumed)
        self.assertEqual(self.page.evaluate("window.Law19Review.getManifest()"), resumed)

    def test_invalid_import_is_atomic_for_row_keys_references_times_and_enums(self):
        invalid_documents = []
        unknown_key = copy.deepcopy(self.document)
        unknown_key["tables"]["events"][0]["surprise"] = "must not disappear"
        invalid_documents.append(unknown_key)
        missing_reference = copy.deepcopy(self.document)
        missing_reference["tables"]["teams"][0]["event_id"] = "missing_event"
        invalid_documents.append(missing_reference)
        bad_time = copy.deepcopy(self.document)
        bad_time["tables"]["events"][0]["bind_s"] = 19.
        invalid_documents.append(bad_time)
        bad_enum = copy.deepcopy(self.document)
        bad_enum["tables"]["decisions"][0]["referee_decision"] = "inferred_penalty"
        invalid_documents.append(bad_enum)
        unsafe_id = copy.deepcopy(self.document)
        unsafe_id["tables"]["events"][0]["event_id"] = "../../unsafe"
        invalid_documents.append(unsafe_id)
        for invalid in invalid_documents:
            with self.subTest(tables=invalid["tables"]):
                self.render(self.document)
                self.imported(invalid)
                self.assertEqual(self.page.evaluate("window.Law19Review.getManifest()"), self.document)

    def test_schema_row_edit_and_new_observation_assessment_require_reviewed_context(self):
        expected = copy.deepcopy(self.document)
        self.page.locator("#field-competition").fill("Fixture tournament")
        self.page.locator("#field-crouch_s").fill("21.5")
        self.page.locator("#apply-row").click()
        expected["tables"]["events"][0].update(
            competition="Fixture tournament", crouch_s=21.5, clip_start_s=6.5)
        self.assertEqual(self.page.evaluate("window.Law19Review.getManifest()"), expected)

        self.page.locator("#new-observation").click()
        observation_id = self.page.locator("#field-observation_id").input_value()
        self.page.locator("#field-observation_type").select_option("actor_player_id")
        self.page.locator("#field-observed_value_json").fill('{"visible": true, "frames": [1, 2]}')
        self.page.locator("#field-start_s").fill("25.5")
        self.page.locator("#field-end_s").fill("26.8")
        self.page.locator("#field-evidence_type").select_option("video")
        self.page.locator("#field-evidence_path").fill("synthetic_match.mp4")
        self.page.locator("#field-evidence_start_s").fill("25.5")
        self.page.locator("#field-evidence_end_s").fill("26.8")
        self.page.locator("#field-observability").select_option("observable")
        self.page.locator("#field-review_status").select_option("reviewed")
        self.page.locator("#apply-row").click()
        observed = self.page.evaluate("window.Law19Review.getManifest()")
        self.assertEqual(len(observed["tables"]["observations"]), 2)
        observation = observed["tables"]["observations"][-1]
        self.assertEqual(observation["observation_id"], observation_id)
        self.assertEqual(observation["observed_value_json"], {"visible": True, "frames": [1, 2]})
        self.assertEqual(set(observation), set(load_assets()["schema"]["tables"]["observations"]["columns"]))
        expected["tables"]["observations"].append(observation)
        self.assertEqual(observed, expected)

        self.page.locator("#law-select").select_option("19.2")
        self.page.locator("#new-assessment").click()
        assessment_id = self.page.locator("#field-assessment_id").input_value()
        self.assertEqual(self.page.locator("#field-law_clause").input_value(), "19.2")
        self.page.locator("#field-applicability_status").select_option("applicable")
        self.page.locator("#field-assessment_status").select_option("satisfied")
        self.page.locator("#field-review_status").select_option("reviewed")
        self.page.locator("#field-supporting_observation_ids").fill(json.dumps([observation_id]))
        self.page.locator("#field-rule_context").fill('{"location_reviewed": true}')
        self.page.locator("#apply-row").click()
        self.assertIn("verified event ruleset context", self.page.locator("#message").inner_text())
        self.assertEqual(self.page.evaluate("window.Law19Review.getManifest()"), expected)

        self.page.locator("#field-review_status").select_option("draft")
        self.page.locator("#apply-row").click()
        drafted = self.page.evaluate("window.Law19Review.getManifest()")
        assessment = drafted["tables"]["rule_assessments"][-1]
        self.assertEqual(assessment["assessment_id"], assessment_id)
        self.assertEqual(assessment["review_status"], "draft")
        self.assertEqual(assessment["supporting_observation_ids"], [observation_id])
        expected["tables"]["rule_assessments"].append(assessment)
        self.assertEqual(drafted, expected)

        self.page.locator("#table-select").select_option("events")
        self.page.locator("#field-ruleset_id").fill("fixture-ruleset-2026")
        self.page.locator("#field-law_edition").fill("Fixture edition 2026")
        self.page.locator("#field-context_status").select_option("verified")
        self.page.locator("#apply-row").click()
        expected["tables"]["events"][0].update(
            ruleset_id="fixture-ruleset-2026", law_edition="Fixture edition 2026",
            context_status="verified")
        self.page.locator("#table-select").select_option("rule_assessments")
        self.page.locator("#row-select").select_option(assessment_id)
        self.page.locator("#field-review_status").select_option("reviewed")
        self.page.locator("#apply-row").click()
        expected["tables"]["rule_assessments"][-1]["review_status"] = "reviewed"
        reviewed = self.page.evaluate("window.Law19Review.getManifest()")
        self.assertEqual(reviewed, expected)
        self.assertEqual(validate_document(reviewed), expected)
        self.assertEqual(reviewed["tables"]["decisions"], self.document["tables"]["decisions"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for synthetic video")
    def test_local_mp4_is_opened_as_a_blob_with_original_source_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "synthetic_match.mp4"
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=64x48:rate=2", "-t", "40", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video),
            ], check=True, capture_output=True, timeout=30)
            document = copy.deepcopy(self.document)
            sha = hashlib.sha256(video.read_bytes()).hexdigest()
            document["source"]["sha256"] = sha
            document["tables"]["events"][0]["source_video_sha256"] = sha
            self.render(document)
            self.page.locator("#video-file").set_input_files(video)
            self.page.wait_for_function("document.querySelector('video').readyState >= 1")
            self.assertTrue(self.page.locator("video").get_attribute("src").startswith("blob:"))
            self.assertAlmostEqual(self.page.locator("video").evaluate("video => video.duration"), 40., delta=.1)
            self.page.locator("video").evaluate("video => { video.currentTime = 27.5; }")
            self.page.wait_for_function("Math.abs(document.querySelector('video').currentTime - 27.5) < .1")
            self.assertEqual(self.page.evaluate("window.Law19Review.getManifest()"), document)


if __name__ == "__main__":
    unittest.main()
