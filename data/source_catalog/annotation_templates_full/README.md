# Full Law 19 annotation templates

These seven header-only CSVs cover context, procedure, normal play, observations, rule assessments and referee decisions. See ../scrum_full_annotation_plan.md and ../law19_rule_coverage.md.

No real or synthetic annotation rows are included. Rule compliance, observed referee outcomes and causal/player attribution remain separate. A short or occluded clip may leave many fields not observable.

The v2 schema manifest describes the runtime table layout and vocabulary.
`law_annotations.py` validates documents, migrates collection-only v1 JSON
without discarding the original, and exports all seven tables.
`autoclip.py review-laws` creates the offline annotation page;
see ../../../docs/LAW19_WORKFLOW.md. These CSVs remain blank templates.
