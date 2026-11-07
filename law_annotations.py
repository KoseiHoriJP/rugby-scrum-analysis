"""Validate, migrate and export full Law 19 annotations without inferring labels.

The source catalogue supplies reference text and annotation vocabularies. It
does not establish a match's applicable edition, an offender, or a verdict.
All timestamps refer to the original source video, including context outside
the retained clip. CSV exports include drafts; review is not training approval.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile


SCHEMA_VERSION = 2
SCHEMA_ID = "law19_full_annotation_v2"
CATALOG = Path(__file__).resolve().parent / "data" / "source_catalog"
PRIMARY_KEYS = {
    "events": "event_id",
    "teams": "team_observation_id",
    "participants": "participant_observation_id",
    "restarts": "restart_id",
    "observations": "observation_id",
    "rule_assessments": "assessment_id",
    "decisions": "decision_id",
}
STATUS_DEFAULTS = {
    "review_status": "unreviewed", "track_review_status": "unreviewed",
    "context_status": "unknown", "identity_status": "unknown",
    "applicability_status": "unknown", "assessment_status": "unreviewed",
    "mapping_status": "unmapped", "law_mapping_status": "unmapped",
    "end_status": "needs_review", "view_status": "unverified",
    "cue_status": "unverified", "camera_view": "unknown",
    "audio_status": "unknown", "observability": "unreviewed",
    "referee_decision": "unknown",
}
ENUM_ALIASES = {"track_review_status": "review_status", "law_mapping_status": "mapping_status"}
ENUM_FALLBACKS = {
    "context_status": {"unknown", "unverified", "verified"},
    "end_status": {"needs_review", "reviewed"},
    "view_status": {"unverified", "reviewed"},
    "cue_status": {"unverified", "reviewed"},
}
INTEGER_FIELDS = {
    "attempt_index", "decision_index", "players_on_field", "players_in_scrum",
    "prop_count", "hooker_count", "lock_count", "back_row_count",
    "jersey_number", "offending_player_number",
}
REFERENCE_ARRAYS = {"evidence_ids", "supporting_observation_ids"}
JSON_FIELDS = {"observed_value_json", "rule_context"}
SOURCE_KEYS = {"filename", "sha256", "duration_s"}


class AnnotationError(ValueError):
    """An annotation document violates the explicit schema or references."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AnnotationError(message)


def _load_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AnnotationError(f"Cannot read annotation asset {path.name}: {error}") from error
    _check(isinstance(result, dict), f"Annotation asset {path.name} must be an object")
    return result


def load_assets() -> dict:
    """Load the committed schema and supplied-source references, without I/O outside the repo."""
    schema = _load_json(CATALOG / "annotation_templates_full" / "schema_manifest.json")
    document = _load_json(CATALOG / "law19_full" / "law19_document.json")
    coverage = _load_json(CATALOG / "law19_rule_coverage.json")
    _check(set(schema.get("tables", {})) == set(PRIMARY_KEYS), "Annotation schema must define the seven supported tables")
    for name, primary in PRIMARY_KEYS.items():
        columns = schema["tables"][name].get("columns")
        _check(isinstance(columns, list) and all(isinstance(key, str) for key in columns)
               and len(columns) == len(set(columns)) and primary in columns,
               f"Invalid column definition for {name}")
    clauses = document.get("clauses")
    videos = document.get("reference_videos")
    _check(isinstance(clauses, list) and isinstance(videos, list), "Law document has no clause/video catalogue")
    restart_cases = [row for table in document.get("tables", []) for row in table.get("body_rows", [])
                     if isinstance(row.get("item_id"), str) and row["item_id"].startswith("restart_")]
    return {"schema": schema, "clauses": clauses, "coverage": coverage,
            "restart_cases": restart_cases, "videos": videos, "document": document,
            "observation_fields": _load_json(CATALOG / "annotation_templates_full" / "observation_field_registry.json")}


def _json_value(value, path: str, ancestors: set[int] | None = None) -> None:
    """Reject non-JSON values, nonfinite numbers and cycles, including extensions."""
    if value is None or isinstance(value, (str, bool)):
        return
    if type(value) in {int, float}:
        _check(math.isfinite(value), f"{path} must contain only finite JSON numbers")
        return
    _check(isinstance(value, (dict, list)), f"{path} contains a non-JSON value")
    ancestors = set() if ancestors is None else ancestors
    identity = id(value)
    _check(identity not in ancestors, f"{path} contains a cycle")
    ancestors.add(identity)
    try:
        if isinstance(value, dict):
            _check(all(isinstance(key, str) for key in value), f"{path} requires string object keys")
            items = value.items()
        else:
            items = enumerate(value)
        for key, child in items:
            _json_value(child, f"{path}.{key}", ancestors)
    finally:
        ancestors.remove(identity)


def _number(value, path: str) -> float:
    _check(type(value) in {int, float} and math.isfinite(value), f"{path} must be a finite number")
    return float(value)


def _identifier(value, path: str) -> str:
    _check(isinstance(value, str) and bool(value.strip()) and len(value) <= 200
           and not any(ord(char) < 32 for char in value), f"{path} must be a nonempty identifier")
    return value


def _source(value: dict, path: str = "source") -> None:
    _check(isinstance(value, dict) and set(value) == SOURCE_KEYS, f"{path} must contain exactly filename, sha256 and duration_s")
    _check(isinstance(value["filename"], str) and bool(value["filename"].strip()), f"{path}.filename must be text")
    _check(isinstance(value["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None,
           f"{path}.sha256 must be a lowercase SHA-256")
    _check(_number(value["duration_s"], f"{path}.duration_s") > 0, f"{path}.duration_s must be positive")


def _empty_row(schema: dict, table: str) -> dict:
    row = {column: None for column in schema["tables"][table]["columns"]}
    for column, value in STATUS_DEFAULTS.items():
        if column in row:
            row[column] = value
    return row


def upgrade_manifest(legacy_v1: dict) -> dict:
    """Migrate collection candidates; law review starts unreviewed, never inferred."""
    _json_value(legacy_v1, "legacy_manifest")
    _check(isinstance(legacy_v1, dict) and type(legacy_v1.get("schema_version")) is int
           and legacy_v1["schema_version"] == 1, "Expected legacy collection schema_version 1")
    _check(isinstance(legacy_v1.get("source"), dict), "Legacy manifest requires source metadata")
    source = {key: copy.deepcopy(legacy_v1["source"].get(key)) for key in SOURCE_KEYS}
    _source(source)
    events = legacy_v1.get("events")
    _check(isinstance(events, list), "Legacy manifest requires an events list")
    schema = load_assets()["schema"]
    tables = {name: [] for name in PRIMARY_KEYS}
    for index, old in enumerate(events):
        _check(isinstance(old, dict), f"Legacy event {index} must be an object")
        row = _empty_row(schema, "events")
        for name in ("event_id", "crouch_s", "bind_s", "set_s", "camera_view", "end_status", "view_status", "cue_status", "cue_confidence", "notes"):
            if name in old:
                _check(name in row, f"Runtime schema is missing collection column {name}")
                row[name] = copy.deepcopy(old[name]) if old[name] != "" else None
        row['cue_status'] = 'reviewed' if old.get('cue_status') == 'reviewed' else 'unverified'
        row.update({"source_video_sha256": source["sha256"], "clip_start_s": old.get("start_s"),
                    "attempt_end_s": old.get("end_s"), "clip_end_s": old.get("end_s"),
                    "explanation_end_s": None, "include": old.get("include", True),
                    "review_status": "unreviewed", "context_status": "unknown"})
        tables["events"].append(row)
    document = {"schema_version": SCHEMA_VERSION, "schema_id": SCHEMA_ID, "source": source,
                "tables": tables, "extensions": {"legacy_collection_manifest": copy.deepcopy(legacy_v1)}}
    return validate_document(document)


def _row_types(row: dict, table: str, schema: dict, duration: float) -> None:
    vocabularies = schema.get("vocabularies", {})
    for column, value in row.items():
        path = f"{table}.{row[PRIMARY_KEYS[table]]}.{column}"
        vocabulary = vocabularies.get(column, vocabularies.get(ENUM_ALIASES.get(column, "")))
        if vocabulary is None:
            vocabulary = ENUM_FALLBACKS.get(column)
        if column in STATUS_DEFAULTS:
            _check(value is not None, f"{path} requires an explicit status")
        if vocabulary is not None and value is not None:
            _check(isinstance(value, str) and value in vocabulary, f"{path} has an unsupported vocabulary value")
        if value is None:
            continue
        _check(value != "", f"{path}: use null for an unannotated field, not an empty string")
        if column.endswith("_s"):
            numeric = _number(value, path)
            _check(0 <= numeric <= duration, f"{path} lies outside the source video")
        elif column in INTEGER_FIELDS:
            _check(type(value) is int and value >= 0, f"{path} must be a nonnegative integer or null")
        elif column == "include":
            _check(type(value) is bool, f"{path} must be a boolean")
        elif column == "cue_confidence":
            _check(0 <= _number(value, path) <= 1, f"{path} must lie in [0, 1]")
        elif column == "distance_from_touch_m":
            _check(_number(value, path) >= 0, f"{path} must be nonnegative")
        elif column in REFERENCE_ARRAYS:
            _check(isinstance(value, list), f"{path} must be a JSON array or null")
            for identifier in value:
                _identifier(identifier, path)
            _check(len(value) == len(set(value)), f"{path} contains duplicate references")
        elif column in JSON_FIELDS:
            pass  # The complete document already passed finite JSON validation.
        elif column == "certainty":
            _check((type(value) in {int, float} and 0 <= _number(value, path) <= 1)
                   or isinstance(value, str), f"{path} must be a certainty value or null")
        else:
            _check(isinstance(value, str), f"{path} must be text or null")
    for start, end in (("start_s", "end_s"), ("evidence_start_s", "evidence_end_s")):
        if row.get(start) is not None and row.get(end) is not None:
            _check(row[start] <= row[end], f"{table} has reversed {start}/{end}")


def validate_document(doc: dict, source: dict | None = None) -> dict:
    """Check all tables and references without changing the caller's document."""
    _json_value(doc, "document")
    _check(isinstance(doc, dict) and set(doc) == {"schema_version", "schema_id", "source", "tables", "extensions"},
           "Document requires exactly schema_version, schema_id, source, tables and extensions; put extra metadata in extensions")
    _check(type(doc["schema_version"]) is int and doc["schema_version"] == SCHEMA_VERSION
           and doc["schema_id"] == SCHEMA_ID, "Expected law19_full_annotation_v2 schema_version 2")
    _source(doc["source"])
    if source is not None:
        _source(source, "selected source")
        _check(doc["source"]["sha256"] == source["sha256"], "Selected source SHA-256 does not match the annotation document")
        _check(abs(doc["source"]["duration_s"] - source["duration_s"]) <= 0.05, "Selected source duration does not match the annotation document")
    _check(isinstance(doc["extensions"], dict), "extensions must be a JSON object")
    tables = doc["tables"]
    _check(isinstance(tables, dict) and set(tables) == set(PRIMARY_KEYS), "Document must contain exactly all seven annotation tables")
    assets = load_assets()
    schema = assets["schema"]
    clause_ids = {row["clause_id"] for row in assets["clauses"]}
    restart_ids = {row["item_id"] for row in assets["restart_cases"]}
    observation_types = {field for row in assets["coverage"]["numbered_clause_coverage"] + assets["coverage"]["supplementary_coverage"] for field in row["observation_fields"]}
    law_hash = schema["source"]["sha256"]
    duration = doc["source"]["duration_s"]
    indexes = {}
    for table, primary in PRIMARY_KEYS.items():
        rows = tables[table]
        _check(isinstance(rows, list), f"tables.{table} must be an array")
        allowed = set(schema["tables"][table]["columns"])
        indexes[table] = {}
        for row in rows:
            _check(isinstance(row, dict) and set(row) == allowed, f"{table} rows must contain exactly the schema columns; store extras in extensions")
            identifier = _identifier(row[primary], f"{table}.{primary}")
            _check(identifier not in indexes[table], f"Duplicate {table} {primary}: {identifier}")
            indexes[table][identifier] = row
            _row_types(row, table, schema, duration)
    events = indexes["events"]
    for table, rows in tables.items():
        for row in rows:
            event_id = _identifier(row["event_id"], f"{table}.event_id")
            _check(event_id in events, f"{table} refers to an unknown event_id: {event_id}")
            event = events[event_id]
            if table == "events":
                _check(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", event_id) is not None,
                       "Event event_id must use 1–80 letters, digits, underscores or hyphens")
                cue = [row.get(name) for name in ("crouch_s", "bind_s", "set_s")]
                _check(all(type(value) in {int, float} for value in cue)
                       and 0 <= cue[0] < cue[1] < cue[2] < duration, f"Event {event_id} requires ordered Crouch, Bind, Set times")
                _check(row["clip_start_s"] is not None and abs(row["clip_start_s"] - max(0, cue[0] - 15)) <= 1e-6,
                       f"Event {event_id} clip_start_s must equal Crouch minus 15 seconds, clamped at zero")
                ending = row["attempt_end_s"]
                _check(ending is None or ending > cue[2], f"Event {event_id} attempt_end_s must follow Set")
                _check(row["end_status"] != "reviewed" or ending is not None, f"Event {event_id} reviewed end requires attempt_end_s")
                for name in ("attempt_end_s", "explanation_end_s"):
                    _check(row[name] is None or (row["clip_end_s"] is not None and row["clip_end_s"] >= row[name]),
                           f"Event {event_id} clip_end_s must retain {name}")
                _check(ending is None or row['explanation_end_s'] is None or row['explanation_end_s'] >= ending,
                       f"Event {event_id} explanation_end_s must not precede attempt_end_s")
                _check(row["clip_end_s"] is None or row["clip_end_s"] > row["set_s"], f"Event {event_id} clip_end_s must follow Set")
                _check(row["source_video_sha256"] == doc["source"]["sha256"], f"Event {event_id} source_video_sha256 does not match source")
                if row["context_status"] == "verified":
                    _check(row["ruleset_id"] is not None and row["law_edition"] is not None,
                           f"Event {event_id} verified context requires ruleset_id and law_edition")
                    _check(all(row[name].strip().casefold() not in {'unknown', 'unverified', 'n/a', 'not specified'}
                               for name in ('ruleset_id', 'law_edition')),
                           f"Event {event_id} verified context cannot use unknown ruleset/edition placeholders")
            for name in ("law_clause", "end_reason_clause", "reset_reason_clause"):
                if name in row and row[name] is not None:
                    _check(row[name] in clause_ids, f"{table}.{name} references unsupported law clause {row[name]!r}")
            if table == "restarts" and row["restart_table_row_id"] is not None:
                _check(row["restart_table_row_id"] in restart_ids, "Unknown restart_table_row_id")
            if row.get("previous_attempt_id") is not None:
                previous_id = row["previous_attempt_id"]
                _check(previous_id in events and previous_id != event_id, f"{table} previous_attempt_id must reference another event")
                _check(events[previous_id]["crouch_s"] < event["crouch_s"], "previous_attempt_id must precede the current attempt")
            for name in REFERENCE_ARRAYS:
                for observation_id in row.get(name) or []:
                    observation = indexes["observations"].get(observation_id)
                    _check(observation is not None and observation["event_id"] == event_id,
                           f"{table}.{name} must reference observations from the same event")
            if table == "observations":
                _check(row["observation_type"] in observation_types, "Unknown observation_type")
            if table == "rule_assessments":
                _check(row["law_clause"] in clause_ids, "A rule assessment requires a supported law_clause")
                status, applicable = row["assessment_status"], row["applicability_status"]
                _check(status != "not_applicable" or applicable == "not_applicable", "not_applicable assessment requires not_applicable applicability")
                _check(status not in {"satisfied", "not_satisfied"} or applicable == "applicable", "A compliance assessment requires applicable status")
                _check(applicable != "not_applicable" or status in {"unreviewed", "not_applicable"}, "A non-applicable rule cannot receive a compliance assessment")
                _check(row["source_law_sha256"] is None or row["source_law_sha256"] == law_hash, "Rule assessment law-source SHA-256 does not match the catalogue")
                if row['review_status'] == 'reviewed' and status in {'satisfied', 'not_satisfied'}:
                    _check(event['context_status'] == 'verified', 'Reviewed compliance assessment requires verified event rules context')
                    _check(row['source_law_sha256'] == law_hash, 'Reviewed compliance assessment requires the law-source SHA-256')
                    evidence = row['supporting_observation_ids'] or []
                    _check(bool(evidence), 'Reviewed compliance assessment requires supporting observations')
                    for observation_id in evidence:
                        observation = indexes['observations'][observation_id]
                        _check(observation['review_status'] == 'reviewed'
                               and observation['observability'] in {'observable', 'partly_observable'}
                               and observation['evidence_type'] is not None and observation['evidence_path'] is not None,
                               'Reviewed compliance assessment requires reviewed observable source evidence')
            if table == "decisions" and row["offending_player_number"] is not None:
                _check(row["attribution_basis"] is not None, "An attributed offending player number requires an explicit attribution_basis")
            if table == 'decisions' and row['explanation_end_s'] is not None:
                _check(event['clip_end_s'] is not None and event['clip_end_s'] >= row['explanation_end_s'],
                       'Event clip_end_s must retain every recorded referee explanation')
    return doc


def review_payload(doc: dict) -> dict:
    """Return validated annotation data and the complete law reference catalogue."""
    validate_document(doc)
    return {"manifest": doc, **load_assets()}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def export_tables(doc: dict, output: Path) -> dict:
    """Atomically export all seven tables and lossless JSON, without overwrites."""
    validate_document(doc)
    output = Path(output)
    _check(not output.exists() and not output.is_symlink(), f"Annotation output already exists: {output}")
    assets = load_assets()
    schema = assets["schema"]
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = {name: len(rows) for name, rows in doc["tables"].items()}
    with tempfile.TemporaryDirectory(prefix=".law19-tables-", dir=output.parent) as temporary:
        staging = Path(temporary) / "annotations"
        staging.mkdir()
        for name, rows in doc["tables"].items():
            columns = schema["tables"][name]["columns"]
            with (staging / f"{name}.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                                     if isinstance(value, (dict, list, bool)) or key in JSON_FIELDS and value is not None
                                     else value for key, value in row.items()})
        _write_json(staging / "manifest.json", doc)
        _write_json(staging / "schema_manifest.json", schema)
        _write_json(staging / "source_provenance.json", {
            "annotation_schema_id": SCHEMA_ID, "source_video": doc["source"],
            "law_source": assets["coverage"]["source_provenance"],
            "schema_manifest_sha256": hashlib.sha256((CATALOG / "annotation_templates_full" / "schema_manifest.json").read_bytes()).hexdigest(),
            "table_counts": counts,
            "review_policy": "Draft and unreviewed rows are retained; this export does not approve training labels or infer legal verdicts.",
            "split_guidance": "Use a reviewed common match_group across all recordings of one match; source SHA-256 identifies a file, not every recording of that match.",
        })
        _check(not output.exists() and not output.is_symlink(), f"Annotation output appeared during export: {output}")
        staging.rename(output)
    return {"output_dir": str(output), "schema_id": SCHEMA_ID, "counts": counts,
            "training_approved": False}
