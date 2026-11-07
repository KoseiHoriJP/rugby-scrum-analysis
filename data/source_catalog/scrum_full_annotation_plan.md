# Full Law 19 annotation plan

This is the full specification for the new dataset. It supersedes the earlier
decision-only scope. The decision plan remains one component, alongside normal
play, permitted actions, formation, possession, restarts, and endings.

Authority: the user-supplied HTML titled **World Rugby Passport — 19 Scrum**,
attributed to https://passport.world.rugby/laws-of-the-game/laws-by-number/19-scrum/.
The saved source has SHA-256
`fbf3f5c31cd2ea7513c390d3fb4c8533cf008d92cc798224873af0037833a07b`.
It was supplied as a file, not independently fetched. Its edition/effective
date and applicability to historical competitions remain unconfirmed.

## Complete source scope

The source coverage includes the principle; all 39 main clauses and 49
subclauses; all 17 restart-table rows and three column headings; all ten
section headings; all three diagram references and captions; the marked law
trial; the inline cross-reference to Law 3.15 and textual references to 19.7;
and all 31 videos associated with 18 clause groups. Image pixels, video contents,
and provisions on other pages are not supplied by the HTML and remain unreviewed.

`law19_rule_coverage.json` assigns observation fields, evidence, context and
assessment types to every numbered clause and to the principle, restart rows
and diagrams. The `law19_full/` import preserves the table, surrounding text,
assets and source context; the earlier `law19/` paragraph import is retained
as the initial version.

## What each part of the law contributes

| Source | Annotation scope, including normal play |
| --- | --- |
| Principle | A restart and contest for possession; event/possession context, not an infringement label |
| 19.1 and its full table | Why the scrum was awarded, where it should be, and the team entitled to throw in; preserve each condition/option |
| 19.2–9 | Referee's mark and middle line, readiness timer, players on field/in scrum, roles, pack formation/binding, alignment and front-row distance |
| 19.10–12 | Square/stable/stationary at each command, crouch/head posture, brake foot, opposing prop bindings, Set/engagement, readiness and foot placement |
| 19.13–15 | Scrum-half's chosen side, ball-holding diagram, tunnel/outside position, delay, single movement, speed, straight feed and first ground contact |
| 19.16–26 | Ball feed as legal start, first push, possession gain, push direction, striking/feet and ball handling, safety stops, availability at the rear and “use it” |
| 19.27–33 | Scrum-half and other players' offside positions over time, hindmost foot/try-line context, marked trial and end of scrum-specific offside lines |
| 19.34–35 | Every no-infringement reset reason, the repeated-kick exception, attempt linkage and retention of the previous throw-in team |
| 19.36(a–e) | Each distinct legal ending condition, with time and supporting evidence |
| 19.37–38 | Every dangerous/restricted practice and its specific printed sanction, preserving intent and actor qualifications |
| 19.39 | Authority to apply U19 variations at defined levels; actual external variation text/applicability needs separate evidence |
| Diagrams | Formation, throw-in and offside reference material; preserve captions and source paths without inventing unseen geometry |
| Videos | Rule illustrations for correct technique, procedure, resets or infringements as appropriate after review; no automatic offence/player label |

## Annotation tables

Blank tables are in `annotation_templates_full/`. No match labels are seeded.

| Table | Unit and purpose |
| --- | --- |
| `events.csv` | One scrum attempt, linked to its episode, source match, applicable rules and timeline |
| `teams.csv` | Team participation counts, scrum formation counts, entitlement and possession context |
| `participants.csv` | Player/role identity observations over a time interval; jersey number and role are independent |
| `restarts.csv` | Each award/reset, linked to the appropriate 19.1 row or 19.34 condition, its location and throw-in entitlement |
| `observations.csv` | Timed observations using the coverage registry's field names and structured values, evidence and units |
| `rule_assessments.csv` | Assessment of an applicable requirement, supported by observations; normal compliance is retained |
| `decisions.csv` | Actual referee decisions, stated reasons, attribution and law mappings, kept independent of the requirement assessment |

The same event can contain multiple timed observations and decisions. Every
row has an identifier and an `event_id` where applicable; evidence links back
to the original video's time. Keep individual reset attempts linked through
`episode_id` and `previous_attempt_id`, rather than replacing an earlier attempt.
All related material from the same match stays in one dataset split.

## Assessment and unknown values

For an assessable legal requirement, use:

- `satisfied`: the relevant condition is supported by adequate evidence.
- `not_satisfied`: evidence supports failure of the requirement; this is
  separate from a referee award, intent or physical causation.
- `not_observable`: the necessary view/audio/context is missing or occluded.
- `not_applicable`: a verified context makes the requirement inapplicable.
- `unreviewed`: nobody has completed the assessment.

Permissions, definitions, context, table choices and informational parent
clauses need their corresponding observation/context records rather than a
forced infringement assessment. Unknown applicability is not the same as
verified non-applicability. Blank means not yet annotated. A referee's failure
to award a penalty does not establish that every requirement was satisfied.

Store normal executions as positive examples of satisfied requirements. For
example, if ball feed and pushing are visible, a first push after ball release
can support 19.17 compliance; an ordinary ball exit outside the tunnel can
support 19.36(a). This does not certify other unobservable rules in that event.

## Temporal and contextual details

- Record mark, readiness, Crouch, Bind, Set, engagement, ball release/feed,
  first push, ball availability, Use It, ball exit, whistle, attempt end and
  explanation end separately where observable.
- Under 19.16, **the legal scrum starts when the ball leaves the scrum-half's
  hands**. Crouch and Set are different events.
- The 30-second readiness requirement in 19.4 starts at the referee's mark.
  The collector's 20-second speech-sequence filter is an implementation
  setting, not a law. The 15-second clip lead-in is also a dataset setting.
- Evaluate square/stable/stationary and the brake foot at the relevant
  command, not as a single assumption covering the entire event.
- “Use it” is not itself a scrum-ending condition. Distinguish 19.36 endings,
  immediate safety whistles and resets; a whistle alone does not identify
  an infringement.
- Original restart reasons, last possession/movement, player reductions,
  timing from the mark and offside distances may require context outside a
  short clip. Preserve links to that context or mark it unavailable.
- Physical distance, angle, body height and force are not established merely
  by a confident 2D pose. Record coordinate frames and units; use calibrated
  measurements or leave physical quantities unknown.

## Qualifications that must survive normalization

- 19.5 applies when both teams have 15 players and references 19.7(d).
  Under 19.6 the permitted reduction and minimum of five need context;
  the opponent is not required to mirror a reduction.
- 19.7(b) permits the hooker's arms over or under the props' arms. 19.13
  permits the scrum-half to choose a side. These choices are normal-play
  observations, not automatically faults.
- 19.15(f) permits the stated shoulder-width alignment while still requiring
  a straight throw. Annotate body alignment and ball trajectory independently.
- In 19.21 a front-row player may use either striking foot, but not both at
  the same time. Using different feet at different moments is not the same
  observation as simultaneous two-foot striking.
- 19.11(a–d) print penalties, while 19.11(e) prints a free-kick. Avoid one
  unconditional “binding fault = penalty” category.
- The positioning choices in 19.28 and 19.30 are alternatives joined by “or”.
  Record the applicable choice instead of requiring every option simultaneously.
- 19.30(a) alone is wrapped in **GLOBAL LAW TRIAL** in this supplied HTML.
  Its applicability/effective period cannot be inferred from the copyright year.
- 19.34 is explicitly about **no infringement**. A collapse or a wheel beyond
  90 degrees can therefore be a reset without attributing a foul.
- In 19.34(e), the printed penalty applies to the repeated-kick exception;
  ordinary unintentional kicking-out is reset context. Keep 19.23's separate
  front-row provision and printed free-kick distinct.
- 19.37 requires the relevant actor/action/intent conditions. A fall or
  collapse alone does not identify an intentional offence or its initiator.
- Under 19.36(a), an exit through the tunnel is excluded from that ending
  condition. Under 19.36(b), reaching the hindmost feet is not enough by
  itself: the specified pickup/play must occur. 19.36(e) identifies a scrum
  ending at the try line; it is not by itself an annotation that a try was scored.
- Law 3.15, full U19/uncontested variations, competition trials and relevant
  laws on other pages remain external dependencies, not verified by this HTML.

## Media and evidence boundaries

The HTML references three diagrams but supplies neither their image pixels nor
the 31 video files. Captions/context can be catalogued now; legal/illegal
content, camera angles, player identity, audio and complete clip windows need
media review. Empty image alt text must not be replaced with an invented
description. Formation/throw-in/offside diagrams must not be assigned to a
single preceding paragraph merely by proximity.

Keep the official reference library distinct from collected match clips. A
reference clip's association with a clause is not an automatic ground-truth
verdict. Edited examples may not contain the 15-second lead-in, referee calls,
full scrum ending or post-decision explanation. Reference and match footage
from the same original game must be checked for duplicate/split leakage.

This specification and its blank templates do not alter the existing pilot's
labels or implement these fields in the current annotation application.
