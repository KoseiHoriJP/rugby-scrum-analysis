"""Synthetic evidence tests for conservative suggestions, not referee accuracy."""

import copy
import unittest

from automation.law_checks import check_document
from law_annotations import AnnotationError, STATUS_DEFAULTS, load_assets, upgrade_manifest


class LawChecksTests(unittest.TestCase):
    def setUp(self):
        self.assets = load_assets()
        self.doc = upgrade_manifest({
            "schema_version": 1,
            "source": {"filename": "synthetic.mp4", "sha256": "a" * 64, "duration_s": 200.},
            "events": [{"event_id": "e1", "crouch_s": 40., "bind_s": 42., "set_s": 44.,
                        "start_s": 25., "end_s": 80.}],
        })
        self.event = self.doc["tables"]["events"][0]
        self.event.update(review_status="reviewed", context_status="verified",
                          ruleset_id="synthetic_standard_15", law_edition="2026 test context")
        self.next_observation = 1

    def row(self, table, **fields):
        row = {name: None for name in self.assets["schema"]["tables"][table]["columns"]}
        row.update({name: value for name, value in STATUS_DEFAULTS.items() if name in row})
        row.update(event_id="e1", **fields)
        return row

    def evidence(self, target, observation_type, value, *, evidence_type="video",
                 review_status="reviewed", observability="observable", evidence_path="synthetic.mp4#t=30"):
        identifier = f"o{self.next_observation}"
        self.next_observation += 1
        team = target.get("team_id")
        observation = self.row(
            "observations", observation_id=identifier, observation_type=observation_type,
            observed_value_json=value, subject_type="team" if team else "event",
            subject_id=team or target["event_id"], review_status=review_status,
            observability=observability, evidence_type=evidence_type, evidence_path=evidence_path,
        )
        self.doc["tables"]["observations"].append(observation)
        target["evidence_ids"] = (target.get("evidence_ids") or []) + [identifier]
        return observation

    def time_fact(self, field, observation_type, value, **evidence_options):
        self.event[field] = value
        return self.evidence(self.event, observation_type, value, **evidence_options)

    def teams(self, first=None, second=None):
        defaults = {"players_on_field": 15, "players_in_scrum": 8, "prop_count": 2,
                    "hooker_count": 1, "lock_count": 2, "back_row_count": 3}
        fields = {"players_on_field": "players_on_field_count", "players_in_scrum": "scrum_player_count",
                  "prop_count": "front_row_prop_count", "hooker_count": "front_row_hooker_count",
                  "lock_count": "second_row_lock_count", "back_row_count": "back_row_player_count"}
        rows = []
        for index, changes in enumerate((first, second), 1):
            values = dict(defaults, **(changes or {}))
            team = self.row("teams", team_observation_id=f"t{index}", team_id=f"team{index}",
                            review_status="reviewed", **values)
            self.doc["tables"]["teams"].append(team)
            for field, observation_type in fields.items():
                if team[field] is not None:
                    self.evidence(team, observation_type, team[field])
            rows.append(team)
        return rows

    def suggestion(self, clause):
        return next(row for row in check_document(self.doc) if row["law_clause"] == clause)

    def test_every_event_gets_exactly_all_88_source_clause_ids(self):
        second = copy.deepcopy(self.event)
        second.update(event_id="e2", crouch_s=90., bind_s=92., set_s=94.,
                      clip_start_s=75., attempt_end_s=120., clip_end_s=120.)
        self.doc["tables"]["events"].append(second)
        results = check_document(self.doc)
        source_ids = [row["clause_id"] for row in self.assets["clauses"]]
        self.assertEqual(len(source_ids), 88)
        self.assertEqual(len(results), 176)
        for event_id in ("e1", "e2"):
            self.assertEqual([row["law_clause"] for row in results if row["event_id"] == event_id], source_ids)
        self.assertTrue(all(row["review_required"] is True for row in results))
        self.assertTrue(all(set(row) == {"event_id", "law_clause", "suggested_status", "explanation", "basis", "review_required"}
                            for row in results))

    def test_readiness_30_second_boundary_and_late_readiness(self):
        self.time_fact("mark_s", "referee_mark_time_s", 10.)
        ready = self.time_fact("ready_s", "teams_ready_time_s", 40.)
        self.assertEqual(self.suggestion("19.4")["suggested_status"], "satisfied")
        self.event["ready_s"] = ready["observed_value_json"] = 40.001
        self.assertEqual(self.suggestion("19.4")["suggested_status"], "not_satisfied")

    def test_conflicting_reviewed_fact_values_need_resolution(self):
        self.time_fact('mark_s', 'referee_mark_time_s', 10.)
        self.time_fact('ready_s', 'teams_ready_time_s', 40.)
        self.evidence(self.event, 'teams_ready_time_s', 45.)
        self.assertEqual(self.suggestion('19.4')['suggested_status'], 'not_observable')

    def test_timestamp_field_is_not_proof_without_matching_reviewed_evidence(self):
        self.time_fact("mark_s", "referee_mark_time_s", 10.)
        ready = self.time_fact("ready_s", "teams_ready_time_s", 40.)
        for change in ({"observed_value_json": 39.}, {"review_status": "draft"},
                       {"observability": "not_observable"}, {"evidence_path": None},
                       {"evidence_type": "source_diagram"}, {"observation_type": "whistle_time_s"}):
            original = copy.deepcopy(ready)
            ready.update(change)
            with self.subTest(change=change):
                self.assertEqual(self.suggestion("19.4")["suggested_status"], "not_observable")
            ready.clear()
            ready.update(original)

    def test_push_compares_with_feed_not_set_and_includes_equal_boundary(self):
        self.time_fact("ball_feed_s", "ball_leave_hands_time_s", 50.)
        push = self.time_fact("first_push_s", "push_start_time_s", 49.)
        self.assertGreater(self.event["first_push_s"], self.event["set_s"])
        self.assertEqual(self.suggestion("19.17")["suggested_status"], "not_satisfied")
        self.event["first_push_s"] = push["observed_value_json"] = 50.
        self.assertEqual(self.suggestion("19.17")["suggested_status"], "satisfied")
        self.event["ball_feed_s"] = None
        self.assertEqual(self.suggestion("19.17")["suggested_status"], "not_observable")

    def test_missing_count_is_unknown_not_a_failure(self):
        self.teams(first={"hooker_count": None})
        result = self.suggestion("19.5")
        self.assertEqual(result["suggested_status"], "not_observable")
        self.assertIn("incomplete", result["explanation"])

    def test_correct_counts_alone_do_not_establish_binding_and_formation(self):
        teams = self.teams()
        result = self.suggestion("19.5")
        self.assertEqual(result["suggested_status"], "not_observable")
        self.assertIn("binding and formation", result["explanation"])
        for team in teams:
            self.evidence(team, "scrum_formation", {"bound_together": True, "formation_compliant": True})
        self.assertEqual(self.suggestion("19.5")["suggested_status"], "satisfied")

    def test_wrong_observed_counts_support_limited_failure_but_other_team_identity_cannot(self):
        teams = self.teams(first={"players_in_scrum": 7})
        self.assertEqual(self.suggestion("19.5")["suggested_status"], "not_satisfied")
        observation = next(row for row in self.doc["tables"]["observations"]
                           if row["subject_id"] == "team1" and row["observation_type"] == "scrum_player_count")
        observation["subject_id"] = teams[1]["team_id"]
        self.assertEqual(self.suggestion("19.5")["suggested_status"], "not_observable")

    def test_reduction_asymmetry_is_permitted_without_whole_clause_compliance(self):
        self.teams(first={"players_on_field": 14, "players_in_scrum": 7, "reduction_context": "permitted"})
        self.assertEqual(self.suggestion("19.5")["suggested_status"], "not_applicable")
        result = self.suggestion("19.6")
        self.assertEqual(result["suggested_status"], "not_observable")
        self.assertIn("need not mirror", result["explanation"])
        self.assertIn("Law 3.15", result["explanation"])

    def test_reduction_minimum_and_unknown_authorization(self):
        teams = self.teams(first={"players_on_field": 14, "players_in_scrum": 4})
        self.assertEqual(self.suggestion("19.6")["suggested_status"], "not_satisfied")
        teams[0]["players_in_scrum"] = 7
        for observation in self.doc["tables"]["observations"]:
            if observation["subject_id"] == "team1" and observation["observation_type"] == "scrum_player_count":
                observation["observed_value_json"] = 7
        result = self.suggestion("19.6")
        self.assertEqual(result["suggested_status"], "not_observable")
        self.assertIn("permitted reduction context", result["explanation"])

    def test_unknown_or_unreviewed_match_context_holds_measured_facts(self):
        self.time_fact("mark_s", "referee_mark_time_s", 10.)
        self.time_fact("ready_s", "teams_ready_time_s", 40.)
        for change in ({"context_status": "unknown"}, {"review_status": "draft"},
                       {"context_status": "unknown", "ruleset_id": "unknown"},
                       {"context_status": "unknown", "law_edition": "n/a"},
                       {"context_status": "unknown", "law_edition": "unverified"}):
            original = copy.deepcopy(self.event)
            self.event.update(change)
            with self.subTest(change=change):
                self.assertEqual(self.suggestion("19.4")["suggested_status"], "not_observable")
            self.event.clear()
            self.event.update(original)

    def test_invalid_verified_context_placeholders_are_rejected(self):
        self.event["ruleset_id"] = "unknown"
        with self.assertRaises(AnnotationError):
            check_document(self.doc)

    def test_trial_applicability_is_explicit_and_does_not_activate_all_alternatives(self):
        self.assertEqual(self.suggestion("19.30(a)")["suggested_status"], "not_observable")
        self.event["trial_context"] = "19.30(a)=not_applicable"
        self.assertEqual(self.suggestion("19.30(a)")["suggested_status"], "not_applicable")
        self.assertEqual(self.suggestion("19.30(b)")["suggested_status"], "not_observable")
        self.event["trial_context"] = "19.30(a)=applicable"
        self.assertEqual(self.suggestion("19.30(a)")["suggested_status"], "not_observable")
        self.event["trial_context"] = "19.30(a)=applicable; 19.30(a)=not_applicable"
        self.assertEqual(self.suggestion("19.30(a)")["suggested_status"], "not_observable")

    def test_reset_needs_confirmed_context_and_matching_throwing_team_evidence(self):
        restart = self.row("restarts", restart_id="r1", context_status="verified",
                           review_status="reviewed", reset_reason_clause="19.34(b)",
                           actual_throwing_team="team1", previous_throwing_team="team1")
        self.doc["tables"]["restarts"].append(restart)
        self.assertEqual(self.suggestion("19.35")["suggested_status"], "not_observable")
        self.evidence(restart, "reset_reason", "19.34(b)")
        actual = self.evidence(restart, "reset_throwing_team_id", "team1")
        self.evidence(restart, "previous_throwing_team_id", "team1")
        self.assertEqual(self.suggestion("19.35")["suggested_status"], "satisfied")
        restart["actual_throwing_team"] = actual["observed_value_json"] = "team2"
        self.assertEqual(self.suggestion("19.35")["suggested_status"], "not_satisfied")
        restart["context_status"] = "unknown"
        self.assertEqual(self.suggestion("19.35")["suggested_status"], "not_observable")

    def test_collapse_and_whistle_never_imply_intent_or_a_penalty(self):
        self.time_fact("whistle_s", "whistle_time_s", 60.)
        self.evidence(self.event, "scrum_collapse_time_s", 59.)
        self.doc["tables"]["decisions"].append(self.row(
            "decisions", decision_id="d1", referee_decision="reset", review_status="reviewed"))
        result = self.suggestion("19.37(d)")
        self.assertEqual(result["suggested_status"], "not_observable")
        self.assertIn("alone does not establish intentional", result["explanation"])
        self.assertNotIn("offending_team", result)
        self.assertNotIn("law_prescribed_sanction", result)
        self.assertEqual(self.suggestion("19.25")["suggested_status"], "not_observable")
        self.assertEqual(self.suggestion("19.35")["suggested_status"], "not_observable")

    def test_unsupported_use_it_and_permission_parent_records_remain_conservative(self):
        self.time_fact("use_it_s", "use_it_command_time_s", 60.)
        self.time_fact("ball_exit_s", "ball_played_out_time_s", 60.01)
        self.assertEqual(self.suggestion("19.26")["suggested_status"], "not_observable")
        for clause in ("19.7", "19.13", "19.18", "19.30", "19.39"):
            self.assertEqual(self.suggestion(clause)["suggested_status"], "not_applicable")

    def test_document_human_assessments_decisions_and_extensions_are_unchanged(self):
        self.doc["tables"]["rule_assessments"].append(self.row(
            "rule_assessments", assessment_id="a1", law_clause="19.37(d)",
            assessment_status="not_observable", review_status="reviewed"))
        self.doc["tables"]["decisions"].append(self.row(
            "decisions", decision_id="d1", referee_decision="penalty", awarded_to_team="team2",
            offending_team="team1", referee_reason_verbatim="Referee's words", review_status="reviewed"))
        self.doc["extensions"]["custom"] = {"keep": [None, False, 1]}
        before = copy.deepcopy(self.doc)
        results = check_document(self.doc)
        self.assertEqual(self.doc, before)
        results[0]["basis"].append("separate output")
        self.assertEqual(self.doc, before)


if __name__ == "__main__":
    unittest.main()
