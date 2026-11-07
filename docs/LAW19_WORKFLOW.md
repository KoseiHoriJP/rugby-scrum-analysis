# Annotating scrums against Law 19

[English](LAW19_WORKFLOW.md) | [日本語](LAW19_WORKFLOW.ja.md)

The full-law workflow records observations and compares them with the supplied
World Rugby Law 19 reference, alongside the actual referee decision. Player
tracks can support an observation; they do not establish an offence, identity,
intent or cause. The original phase pilot remains available separately.

## 1. Open a full review

A new `scan` creates a full-law `review.html`, v2 `events-law19.json`, original
v1 `events.json`, transcript, and `legacy_clip_review.html`. For an existing
collection manifest or a saved v2 annotation document:

```sh
python autoclip.py review-laws --video media/match01/match.mp4 --events runs/match01/events.json --ruleset-preset rwc2023 --output runs/match01-law19
open runs/match01-law19/review.html
```

The output directory must be new. Select the same local MP4 in the page.
Everything runs offline after source acquisition/model installation. Save the
JSON before closing the tab; loading that JSON resumes the seven tables.
The exporter verifies the original video's SHA-256, not just its filename.

The selected first target is **Men's Rugby World Cup 2023**. Use
`--ruleset-preset rwc2023` with `scan` or `review-laws` to prefill that target.
The [preset](../data/rulesets/rwc2023.json) leaves the law edition blank,
trial applicability unknown, and rules context unverified until supported by
historical sources. It does not assume that the supplied 19.30(a) trial
applied in 2023. Omit the preset for other competitions.

## 2. Review the event and its rules

Reject false speech candidates or confirm Crouch/Bind/Set. Set the physical
`attempt_end_s` from the actual event, `explanation_end_s` if the referee speaks
afterwards, and `clip_end_s` to retain both. Clip start stays Crouch minus 15
seconds, clamped at zero. Mark the ending and camera view reviewed explicitly;
clip review is separate from the law assessment's review status.

Record competition, match grouping, date, `ruleset_id`, `law_edition` and
`trial_context`. Only mark `context_status=verified` after identifying the
rules that applied to that match. The supplied HTML's edition is unknown; it
is not independently verified World Cup competition regulations. Other law
pages, historical editions, U19 variations and adopted trials may be needed.
Never fill an edition from the page's copyright year.

Use the seven tables for:

| Table | Record |
| --- | --- |
| events | Timeline, match/rules context and collection review |
| teams | Actual on-field/scrum numbers and formation |
| participants | Supported identity, team, role and optional track link |
| restarts | Restart reason, location, entitlement and reset links |
| observations | Timecoded facts, visibility, values and evidence |
| rule_assessments | Independent comparison with a specific law clause |
| decisions | Actual referee decision, exact words and attributed offender |

All 88 numbered source records are available, including permitted choices,
normal play, safety, resets and endings. The reference material also includes
the principle, all 17 restart-table cases, diagram references and 31 video
references. Linked images/videos have not been downloaded or visually verified.
The 179 observation types are a vocabulary, not 179 mandatory findings.

Each row has the exact columns in the schema manifest. Blank/null means
unannotated. `not_observable` means inadequate evidence, `not_applicable` means
the rule's condition does not apply, and neither means failure. Structured
observation values are JSON; evidence fields contain JSON arrays of observation
IDs from the same event. Keep referee words separate from your interpretation.
A collapse or a visible number 3 alone cannot identify an intentional offender.

## 3. Run conservative checks on recorded facts

```sh
python autoclip.py check-laws --events ~/Downloads/law19_reviewed_events.json --output runs/match01-checked.json
python autoclip.py review-laws --events runs/match01-checked.json --output runs/match01-check-review
```

Checks propose draft results for supported facts: the 30-second preparation
window, formation counts, permitted player reductions, pushing relative to
ball feed, and throwing-team continuity on a confirmed reset. They require
verified rules context and reviewed, observable supporting evidence. Incomplete
or conflicting evidence produces `not_observable`. Trial applicability is
explicit; it is never inferred from the match name.

These checks use entered facts; they do not detect new visual/audio actions.
A timing or count check addresses that component of a clause, not every
binding/posture condition. Unsupported clauses stay for manual review. The
checker never changes human assessments or referee decisions, and never assigns
intent or an offending player. Its snapshot becomes stale after edits; rerun
the commands. Legal scrum start is ball feed (19.16), not Set. A safety whistle
is not automatically a penalty; a reset may involve no infringement.

For timing checks, set the event's `review_status=reviewed` and link the matching
reviewed observations through `events.evidence_ids`. Each observation needs a
source `evidence_type`, `evidence_path` and explicit observability. The scalar
`observed_value_json` must equal the corresponding source timestamp:

| Event field | Observation type |
| --- | --- |
| mark_s | referee_mark_time_s |
| ready_s | teams_ready_time_s |
| ball_feed_s | ball_leave_hands_time_s |
| first_push_s | push_start_time_s |

For example, a recorded feed at 50 seconds uses observation type
`ball_leave_hands_time_s` and JSON value `50`. Count evidence uses each team's
`evidence_ids`, `subject_type=team` and `subject_id=team_id`. Correct counts alone
do not prove binding: the formation check additionally requires a reviewed
`scrum_formation` value `{"bound_together":true,"formation_compliant":true}`
for each team. Conflicting reviewed values require resolution. Use
`19.30(a)=applicable` or `19.30(a)=not_applicable` in `trial_context` only after
confirming that historical provision for the actual match.

## 4. Validate and export

```sh
# All seven tables, even if no clips are ready. Draft statuses are preserved.
python autoclip.py export-annotations --events ~/Downloads/law19_reviewed_events.json --output datasets/match01-annotations

# Reviewed aerial/side clips, retained audio, and the full annotation document/tables.
python autoclip.py export --video media/match01/match.mp4 --events ~/Downloads/law19_reviewed_events.json --output datasets/match01
```

The exporter rejects invalid IDs, references, enum values and time bounds.
It rejects cuts that would truncate a recorded scrum ending or explanation.
It preserves full JSON, including legacy metadata and extensions. Seven CSVs
use original source-video seconds; `clips.csv` supplies the offset to each
exported clip. Clip readiness does not imply a completed legal assessment.
Keep all recordings and examples from one match in the same dataset split.
Existing outputs are never overwritten.
