"""Conservative, reviewable Law 19 fact suggestions for annotation documents.

This module compares a small set of explicit, reviewed facts. It never edits a
rule assessment or referee decision, identifies an offender, or infers intent.
The source catalogue contains 88 numbered records; coverage is not a claim that
all 88 can be assessed automatically. Unimplemented requirements stay manual.

Evidence values use the registry's observation type and a scalar matching the
field being checked. Team evidence additionally identifies subject_type=team
and subject_id=team_id. Formation evidence is the explicit object
{"bound_together": true, "formation_compliant": true}; it is a reviewed human
observation, not something derived from player counts or tracking.
"""

from __future__ import annotations

import math
import re

from law_annotations import load_assets, validate_document


_UNKNOWN = {"", "unknown", "n/a", "na", "unverified", "none", "null", "not applicable",
            "not specified", "not_specified", "unspecified", "unobservable"}
_VISIBILITY = {"observable", "partly_observable"}
_COUNT_FIELDS = {
    "players_on_field": "players_on_field_count",
    "players_in_scrum": "scrum_player_count",
    "prop_count": "front_row_prop_count",
    "hooker_count": "front_row_hooker_count",
    "lock_count": "second_row_lock_count",
    "back_row_count": "back_row_player_count",
}
_CONTEXT_ROLES = {"informational_parent", "permitted_action", "event_definition", "administrative_authority"}
_RESET_REASONS = {f"19.34({letter})" for letter in "abcde"}
_VIDEO = {"video", "multi_angle_video"}
_FACT_SOURCES = {
    "referee_mark_time_s": _VIDEO | {"referee_audio", "referee_signal"},
    "teams_ready_time_s": _VIDEO,
    "ball_leave_hands_time_s": _VIDEO,
    "push_start_time_s": _VIDEO,
    "players_on_field_count": _VIDEO | {"match_metadata", "roster"},
    "scrum_player_count": _VIDEO,
    "front_row_prop_count": _VIDEO | {"roster"},
    "front_row_hooker_count": _VIDEO | {"roster"},
    "second_row_lock_count": _VIDEO | {"roster"},
    "back_row_player_count": _VIDEO | {"roster"},
    "scrum_formation": _VIDEO,
    "reset_reason": _VIDEO | {"referee_audio", "referee_signal", "referee_explanation"},
    "reset_throwing_team_id": _VIDEO | {"referee_audio", "referee_signal"},
    "previous_throwing_team_id": _VIDEO | {"preceding_play_video", "referee_audio", "referee_signal"},
}


def _known(value) -> bool:
    return isinstance(value, str) and value.strip().lower() not in _UNKNOWN


def _number(value) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _equal(actual, expected) -> bool:
    # bool is not a count/timestamp despite Python's bool/int equality.
    if _number(expected):
        return _number(actual) and actual == expected
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and actual.keys() == expected.keys()
                and all(_equal(actual[key], value) for key, value in expected.items()))
    return type(actual) is type(expected) and actual == expected


def _reviewed(row) -> bool:
    return row.get("review_status") == "reviewed"


def _evidence(row, observations, observation_type, value, team_id=None):
    """Return only referenced, visible, reviewed evidence matching this fact."""
    matching = None
    for identifier in row.get("evidence_ids") or []:
        observation = observations[identifier]
        if (not _reviewed(observation)
                or observation.get("observability") not in _VISIBILITY
                or not _known(observation.get("evidence_type"))
                or not _known(observation.get("evidence_path"))
                or observation.get("evidence_type") not in _FACT_SOURCES.get(observation_type, set())
                or observation.get("observation_type") != observation_type):
            continue
        if team_id is not None and (observation.get("subject_type") != "team"
                                    or observation.get("subject_id") != team_id):
            continue
        if not _equal(observation.get('observed_value_json'), value):
            return None  # Conflicting reviewed facts need a reviewer to resolve them.
        matching = f"observation {identifier}: {observation_type}={value!r} ({observation['evidence_type']}: {observation['evidence_path']})"
    return matching


def _fact(row, field, observation_type, observations, team_id=None):
    value = row.get(field)
    if value is None:
        return None
    return _evidence(row, observations, observation_type, value, team_id)


def _suggest(event_id, clause, status, explanation, basis=()):
    return {"event_id": event_id, "law_clause": clause, "suggested_status": status,
            "explanation": explanation, "basis": list(basis), "review_required": True}


def _readiness(event, observations):
    mark, ready = event.get("mark_s"), event.get("ready_s")
    if not (_number(mark) and _number(ready) and ready >= mark):
        return "not_observable", "Reviewed mark and readiness times on a continuous source timeline are required.", []
    basis = [_fact(event, "mark_s", "referee_mark_time_s", observations),
             _fact(event, "ready_s", "teams_ready_time_s", observations)]
    if not all(basis):
        return "not_observable", "Mark and readiness need their own matching reviewed, visible evidence; command or clip timestamps are insufficient.", []
    elapsed = ready - mark
    return ("satisfied" if elapsed <= 30 else "not_satisfied",
            f"Reviewed readiness is {elapsed:g} seconds after the mark; the 19.4 limit is 30 seconds, inclusive.", basis)


def _team_rows(event_id, tables):
    teams = [row for row in tables["teams"] if row["event_id"] == event_id]
    # Multiple intervals or competing observations need a reviewer to choose.
    if len(teams) != 2 or len({row.get("team_id") for row in teams}) != 2:
        return None
    if any(not _known(row.get("team_id")) or not _reviewed(row) for row in teams):
        return None
    return teams


def _counts(teams, observations, fields):
    basis = []
    for team in teams:
        for field in fields:
            value = team.get(field)
            if type(value) is not int or value < 0:
                return None
            evidence = _fact(team, field, _COUNT_FIELDS[field], observations, team["team_id"])
            if evidence is None:
                return None
            basis.append(evidence)
    return basis


def _full_formation(event, tables, observations):
    teams = _team_rows(event["event_id"], tables)
    if teams is None:
        return "not_observable", "Two distinct reviewed team observations are required; ambiguous intervals need manual review.", []
    on_field = _counts(teams, observations, ["players_on_field"])
    if on_field is None:
        return "not_observable", "Both teams' on-field counts require matching reviewed team evidence before 19.5 applicability is known.", []
    if any(team["players_on_field"] < 15 for team in teams):
        return "not_applicable", "The both-teams-have-15 condition of 19.5 does not apply; assess the reduction context under 19.6 separately.", on_field
    if any(team["players_on_field"] != 15 for team in teams):
        return "not_observable", "The recorded team sizes do not establish the both-teams-have-15 condition.", on_field
    fields = ["players_in_scrum", "prop_count", "hooker_count", "lock_count", "back_row_count"]
    counts = _counts(teams, observations, fields)
    if counts is None:
        return "not_observable", "Scrum and role counts are incomplete or lack matching reviewed team evidence; missing counts are unknown.", on_field
    basis = on_field + counts
    required = dict(zip(fields, (8, 2, 1, 2, 3)))
    if any(team[field] != count for team in teams for field, count in required.items()):
        return "not_satisfied", "With both teams at 15, reviewed scrum or role counts differ from the 8 / 2 props / 1 hooker / 2 locks / 3 back-row requirement.", basis
    formation = {"bound_together": True, "formation_compliant": True}
    bindings = [_evidence(team, observations, "scrum_formation", formation, team["team_id"]) for team in teams]
    if not all(bindings):
        return "not_observable", "The reviewed counts match 19.5, but counts alone do not establish binding and formation, including the 19.7(d) qualification.", basis
    return "satisfied", "Reviewed counts and explicit binding/formation observations support 19.5, including its formation qualification; these remain review suggestions.", basis + bindings


def _reduction(event, tables, observations):
    teams = _team_rows(event["event_id"], tables)
    if teams is None:
        return "not_observable", "Two distinct reviewed team observations are required to assess reduction context.", []
    basis = _counts(teams, observations, ["players_on_field", "players_in_scrum"])
    if basis is None:
        return "not_observable", "On-field and scrum counts require matching reviewed evidence for both teams.", []
    if all(team["players_on_field"] == 15 for team in teams):
        return "not_applicable", "Neither team is reduced below 15; the reduced-team condition in 19.6 does not apply.", basis
    if not any(team["players_on_field"] < 15 for team in teams):
        return "not_observable", "A team reduced below 15 has not been established.", basis
    if any(team["players_in_scrum"] < 5 for team in teams):
        return "not_satisfied", "In a reduced-team context, a reviewed count is below the five-player scrum minimum in 19.6.", basis
    reduced = [team for team in teams if team["players_in_scrum"] < 8]
    if any(team.get("reduction_context") != "permitted" for team in reduced):
        return "not_observable", "Counts meet the five-player minimum, but each reduced scrum needs an explicit permitted reduction context; Law 3.15 is also external.", basis
    return "not_observable", "Reviewed counts meet the five-player minimum. Permitted asymmetric scrum numbers are allowed: the other team need not mirror a reduction. This checks only counts; external Law 3.15 conditions prevent a whole-clause compliance conclusion.", basis


def _push(event, observations):
    feed, push = event.get("ball_feed_s"), event.get("first_push_s")
    if not (_number(feed) and _number(push)):
        return "not_observable", "Ball-leaves-hands and first active push times are required; Set does not start the scrum.", []
    basis = [_fact(event, "ball_feed_s", "ball_leave_hands_time_s", observations),
             _fact(event, "first_push_s", "push_start_time_s", observations)]
    if not all(basis):
        return "not_observable", "Feed and first active push need their own matching reviewed visible evidence; displacement alone is insufficient.", []
    return ("satisfied" if push >= feed else "not_satisfied",
            f"First reviewed active push ({push:g}s) is {'at or after' if push >= feed else 'before'} the ball leaving the hands ({feed:g}s), the legal start under 19.16; Set is not the comparison point.", basis)


def _reset(event, tables, observations):
    restarts = [row for row in tables["restarts"] if row["event_id"] == event["event_id"]]
    if len(restarts) != 1:
        return "not_observable", "A single confirmed reset record with adequate 19.34 context is required; a whistle alone does not establish a reset.", []
    row = restarts[0]
    if (not _reviewed(row) or row.get("context_status") != "verified"
            or row.get("reset_reason_clause") not in _RESET_REASONS
            or not _known(row.get("actual_throwing_team"))
            or not _known(row.get("previous_throwing_team"))):
        return "not_observable", "Reset context must be reviewed and verified with a 19.34(a–e) reason and known actual and previous throwing teams.", []
    basis = [_fact(row, "reset_reason_clause", "reset_reason", observations),
             _fact(row, "actual_throwing_team", "reset_throwing_team_id", observations),
             _fact(row, "previous_throwing_team", "previous_throwing_team_id", observations)]
    if not all(basis):
        return "not_observable", "The reset reason and both throwing-team identities need their own matching reviewed evidence; a decision label is insufficient.", []
    same = row["actual_throwing_team"] == row["previous_throwing_team"]
    return ("satisfied" if same else "not_satisfied",
            "The confirmed reset's reviewed throwing team " + ("matches" if same else "differs from") + " the previous throwing team under 19.35. This does not assess the legality of the reset reason itself.", basis)


def _trial(event):
    text = event.get("trial_context") or ""
    values = set(re.findall(r"(?<![\w.])19\.30\(a\)\s*=\s*(applicable|not_applicable)\b", text))
    if values == {"not_applicable"}:
        return "not_applicable", "The reviewed event context explicitly records 19.30(a)=not_applicable for this global law trial; this says nothing about the other position alternatives.", ["event trial_context: 19.30(a)=not_applicable"]
    if values == {"applicable"}:
        return "not_observable", "The trial is explicitly applicable, but the chosen alternative and reviewed foot/tunnel geometry still require manual assessment; the alternatives do not all apply together.", ["event trial_context: 19.30(a)=applicable"]
    return "not_observable", "Global trial applicability is unknown or conflicting. Record 19.30(a)=applicable or 19.30(a)=not_applicable for the actual match before assessing the chosen alternative.", []


def check_document(doc: dict) -> list[dict]:
    """Return one immutable-input draft suggestion per event × source clause.

    Invalid annotation documents raise AnnotationError through the shared
    validator. Every output has review_required=True. Existing assessments,
    decisions and extensions are read neither as proof nor as permission to
    infer a legal verdict.
    """
    validate_document(doc)
    assets = load_assets()
    roles = {row["clause_id"]: row["record_role"] for row in assets["coverage"]["numbered_clause_coverage"]}
    tables = doc["tables"]
    observations = {row["observation_id"]: row for row in tables["observations"]}
    suggestions = []
    for event in tables["events"]:
        context_ready = (_reviewed(event) and event.get("context_status") == "verified"
                         and _known(event.get("ruleset_id")) and _known(event.get("law_edition")))
        for clause in assets["clauses"]:
            clause_id = clause["clause_id"]
            if roles.get(clause_id) in _CONTEXT_ROLES:
                result = ("not_applicable", "This source record supplies context, a definition, a permitted choice or authority rather than a standalone offence requirement. Retain its observations for manual review.", [])
            elif not context_ready:
                result = ("not_observable", "A reviewed event with verified actual ruleset and law edition is required; unknown context cannot establish compliance or failure.", [])
            elif clause_id == "19.4":
                result = _readiness(event, observations)
            elif clause_id == "19.5":
                result = _full_formation(event, tables, observations)
            elif clause_id == "19.6":
                result = _reduction(event, tables, observations)
            elif clause_id == "19.17":
                result = _push(event, observations)
            elif clause_id == "19.35":
                result = _reset(event, tables, observations)
            elif clause_id == "19.30(a)":
                result = _trial(event)
            elif clause_id == "19.37(d)":
                result = ("not_observable", "A visible collapse alone does not establish intentional collapse, cause, or an offending player. Intent and attribution require independent manual review.", [])
            else:
                result = ("not_observable", "This requirement needs manual assessment of its applicability and supporting observations; no automatic fact check is implemented.", [])
            suggestions.append(_suggest(event["event_id"], clause_id, *result))
    return suggestions
