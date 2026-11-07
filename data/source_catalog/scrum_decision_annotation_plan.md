# Scrum decision annotations — mapped to the supplied Law 19 HTML

This document defines the decision layer of the
[full Law 19 annotation specification](scrum_full_annotation_plan.md).
Normal play, procedures, permissions, possession, formation and all other
chapter content are covered in that broader specification.

Requested authority: [World Rugby Law 19 — Scrum](https://passport.world.rugby/laws-of-the-game/laws-by-number/19-scrum/).

The user supplied both text and the complete HTML titled “World Rugby Passport
– 19 Scrum”. Clause numbers, printed sanctions and embedded example associations
can now be checked against that supplied source. The live page has not been
independently retrieved. The HTML's copyright year does not establish its law
edition or effective date, which remain unknown. No match labels are added by
this specification.

The imported `law19/` catalogue preserves source text and video associations.
Its player links are reconstructed from the HTML's Brightcove account, player
and video IDs. No video has been downloaded, visually assessed, or assigned a
confirmed camera angle.

## Annotation unit

Keep phase labels on their existing sampled frames. Add a separate event-level
decision table, joined by `event_id` and `clip_id`. Each row represents one
observed referee decision, with `decision_index` ordering several decisions in
one event. An advantage, a later award, and a reset must not overwrite each
other. Record the original video timestamp, not only the scoreboard clock.

The accompanying `scrum_decision_template.csv` contains headers only. It does
not add any penalty labels to the current pilot.

## Independent evidence

1. **Observed referee decision:** what the referee actually signals or says,
   its time, and the team receiving the award. Candidate data categories are
   penalty, free kick, reset, advantage, play continues, and unknown. These are
   dataset categories, not a claimed list of Law 19 sanctions.
2. **Stated reason:** preserve the words and identify the speaker. Commentary
   about a possible offence is not a referee-stated explanation. Normalize a
   reason using the checked clause catalogue, preserving qualifications such
   as “intentionally”, “when there is no infringement”, and the marked trial.
3. **Observed behaviour:** neutral visual evidence, such as a pack going down,
   a visible loss of binding, or rotation. This does not establish an offence,
   intent, or physical causation on its own.
4. **Attributed offender:** team, visible/identified jersey number, and role
   are separate fields. A referee's attribution and an observer's hypothesis
   have different evidence bases. Leave identity unknown when unsupported;
   do not turn an expected front-row jersey number into a player identity.
5. **Law reference:** store the verified clause and its prescribed sanction
   independently of the decision that was actually awarded. A mismatch needs
   review rather than an automatic correction to either field.

`unknown` means the evidence does not establish a value. `not_observable` means
the relevant sound or view is absent. Empty fields remain unannotated. An
observed continuation of play does not prove that no offence occurred.

## Law context and verification

For a confirmed mapping, record the law source URL, edition/effective period,
competition, match date, applicable variation/trial, and verification status.
Current online wording must not silently be applied to older matches, U19 or
uncontested scrums, or competitions with different trials. Store additional
law references separately if a decision depends on provisions outside Law 19.

The catalogue's provenance is `user_supplied_html`, not a live-page retrieval.
For each match event, `law_mapping_status` is independently `unmapped`,
`candidate` or `reviewed`. A checked source paragraph does not mean an unseen
match event has been checked. Leave an event's clause unassigned if the available
evidence supports several rules. Do not fill a law's sanction by copying the
referee decision.

## Core mappings from the supplied text

These labels summarize requirements; they are not automatic verdicts about a
particular player or clip. Full clause wording and conditions take precedence.

| Clauses | Requirement or condition | Printed sanction / action |
| --- | --- | --- |
| 19.4 | Be ready to form within 30 seconds of the referee's mark | Free-kick |
| 19.7(a–d) | Binding within a team's pack | Penalty |
| 19.10(a–c) | Crouch posture, head position and hooker brake foot | Free-kick |
| 19.11(a–d) | Opposing prop arm position, jersey grip, maintaining binds | Penalty |
| 19.11(e) | Brake foot must remain effective when adjusted at Bind | Free-kick |
| 19.12(a–d) | Set/engagement, readiness and front-row foot requirements | Free-kick |
| 19.16 | Legal scrum start: ball leaves scrum-half's hands | No explicit sanction listed |
| 19.17 | Teams may push only once the scrum legally begins | Free-kick |
| 19.19 | Push straight and parallel to the ground | Penalty |
| 19.25 | Collapse, lifting or forcing upward requires immediate whistle | Safety stoppage; no explicit sanction listed |
| 19.26 | After “use it”, play the ball out immediately | Scrum |
| 19.30(a) | Non-possessing scrum-half near the centre line of the tunnel | Penalty; explicitly marked GLOBAL LAW TRIAL |
| 19.34(a–d) | Specified failures, including collapse or >90° rotation, **when no infringement occurred** | Reset scrum |
| 19.34(e) | Unintentional kick out of tunnel | Reset; printed penalty applies to the repeated-kick exception |
| 19.36(a–e) | Enumerated endings: ball exit except tunnel, specified ball pickup/play, infringement whistle, ball on/over try line | Ending criteria |
| 19.37(a–e) | Charging, pulling, intentional lifting, intentional collapse, intentional falling/kneeling | Penalty |
| 19.38(a–c) | Specified restricted practices | Penalty |
| 19.38(d–f) | Other specified restricted practices | Free-kick |

19.23 separately prints a free-kick for a front-row player intentionally kicking
the ball out in the direction from which it was thrown. Do not collapse it and
19.34(e)'s repeated-kick exception into one unconditional label. Likewise, a
generic report of “binding” cannot select a specific subclause by itself.

## Hypothetical example

If the referee clearly identifies Blue No. 3 and gives collapsing as the
reason, the event can record: decision=penalty, offending team=Blue, player=3,
reason speaker=referee, and attribution basis=explicit referee identification.
Record the exact reason wording in the evidence, and separately describe the
visible collapse. 19.37(d) is the catalogue rule for **intentional** collapse,
with penalty as the printed sanction; assigning that rule to this event needs
evidence and review, including applicability of that edition. A collapse with
no infringement can instead fall under 19.34(b), with a safety whistle under
19.25. This example is not a label for a supplied clip and does not prove who
physically initiated the collapse.

## Use of official example videos

The HTML contains 31 embedded video references. Store them as an
`official_rule_reference` collection linked to the paragraph they illustrate.
For example, 19.37(d) has two videos and 19.34(b) has two different videos.
An attachment to a law paragraph is verified metadata, not a verified claim
that every frame shows an infringement. Clips under formation/binding rules
may illustrate correct technique. Mark legal/illegal/mixed content, player
identity, intent, view and audio availability only after reviewing the video.

Keep this reference collection separate from newly collected match events.
It is useful as a codebook for annotators, but edited teaching clips may omit
Crouch, the 15-second lead-in, the scrum finish, or the referee's explanation.
Do not invent missing context or assume No. 3 was responsible. Shared original
matches or duplicate footage must also be identified before any dataset split.

## Clip coverage and pilot limits

For decision annotation, retain the event through any relevant referee
explanation following the scrum end. Keep physical scrum end, whistle/decision
time, and explanation end as separate timestamps. A silent or early-ending
clip may support a phase label while leaving the decision/reason unknown.

Crouch and Set are preparation/engagement cues. Under 19.16 the legal scrum
start is the ball feed, so keep `ball_feed_s` separately. “Use it” under 19.26
does not itself end the scrum. For an ending, record the applicable 19.36
condition, or distinguish a safety/reset stoppage without an established
infringement. Not every whistle establishes an infringement under 19.36(d).

The supplied pilot previews are cropped, have pose overlays, and have no audio;
the original videos are absent. Referee speech and off-crop signals therefore
cannot be verified from those previews. No model pose confidence should be used
to infer guilt, a penalty, or the identity of a penalized player.

Review decisions, attribution, and law mappings before treating them as
supervised labels. Keep all events from one match in a single dataset split.
