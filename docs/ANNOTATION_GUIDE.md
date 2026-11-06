# Scrum phase annotation: scrum_phase_v1

## Unit and purpose

Assign **one event-level label per sampled frame**, about every 0.2 seconds.
The aim is to segment scrum phases from visible video context. Do not label
players, track identities, forces, technical legality, or referee decisions.
The preview is an annotated crop; watch surrounding frames when needed.

| Label | Visible working definition |
| --- | --- |
| `formation` | Packs assemble, crouch, align or bind in preparation, before front-row engagement. |
| `engagement` | Initial front-row contact and immediate settling into a bound scrum. This is a transition, not the entire time packs are bound. |
| `drive` | The established bound scrum contest after initial settling, including visibly stationary contest and sustained pushing. |
| `release` | Packs visibly disengage, stand up or separate as the scrum ends. |
| `not_scrum` | Clearly outside the scrum event, such as subsequent open play. |
| `uncertain` | Occlusion, a cut, insufficient context or a phase boundary prevents a defensible choice. Add a note. |

These are project working definitions. In particular, `drive` is a visual phase,
not a measurement of force or evidence of ball insertion. Engagement need not
appear in every clip: one starts with packs already engaged. Do not assume
the full formation → engagement → drive → release sequence must occur.
Resets can revisit phases. Collapse, partial disengagement and blocked views
may require `uncertain`; do not infer a foul or outcome.

## Review procedure

1. Read the clip's context and watch the whole preview once. Previews run at
   5 fps; their time starts at the sampled section, not necessarily the source
   video's start. The tool displays source and preview time separately.
2. Inspect each selected frame, using adjacent frames for context. Assign one
   label only when supported visually. At a transition, label the first
   sampled frame clearly showing the new phase; otherwise use `uncertain`.
3. Record a reviewer name and notes for ambiguous frames. An empty label means
   **not yet annotated**, which differs from `uncertain`.
4. Export JSON to resume work and CSV for analysis. Labels produced by the tool
   have `review_status=draft`. Keep the original exported file unchanged.
5. Have a second reviewer check transitions and uncertain frames. Resolve
   disagreements, record the resolution in notes and mark reviewed rows in a
   separately versioned CSV. Do not train/evaluate against unreviewed drafts
   while calling them verified ground truth.

Use `(clip_id, source_frame_index)` as the stable annotation key. `sample_index`
is local to the clip and maps to preview frame order. A person detection index
is not a frame label key or a cross-frame player identity.

## Quality rules

- Label all frames, including frames with zero person detections.
- Inspect video pixels; skeleton overlays can be wrong or cover useful cues.
- Model confidence is not evidence of a phase, anatomical correctness, player
  visibility or an actual scrum participant.
- Keep all clips from one `match_group` in one split. Adjacent frames in a
  match must never be scattered between train and test.
- Record target label counts and reviewer agreement before training. With
  five clips, classes may be missing from an entire split. Collect additional
  independent matches before treating performance as representative.
- Original clean videos are absent in this upload. If overlays obscure a
  transition, use `uncertain` and revisit it after receiving the original.
