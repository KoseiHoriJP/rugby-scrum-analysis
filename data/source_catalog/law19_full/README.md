# Full Law 19 source and annotation design

Start with the [full annotation specification](../scrum_full_annotation_plan.md),
the [clause-by-clause coverage](../law19_rule_coverage.md), and the
[blank annotation tables](../annotation_templates_full/).

The catalogue was parsed from user-supplied World Rugby Passport HTML. It
contains 88 numbered paragraphs, the principle, all 17 restart-table cases,
three diagram references, and 31 video references. The source edition and its
applicability to individual historical matches remain unverified.

| File | Contents |
| --- | --- |
| `law19_document.json` | Full law-content text, restart table, headings, captions, references, clauses and video metadata |
| `law19_clauses.json` | Numbered paragraphs, parent conditions, printed sanctions and trial qualifications |
| `law19_reference_videos.csv` | Video IDs and player links associated with source paragraphs |
| `source_provenance.json` | Source checksum, acquisition method and verification limits |

[Open the video-reference index](../law19/reference_videos.md) for the 31 player
links extracted from the same HTML. These are reference associations; image
pixels, video contents, angles and player identities have not been reviewed.
They are not automatically labelled offences or downloaded media files.

The [coverage audit](../full_coverage_audit.json) records comparisons against
the supplied text and all 51 restart-table cells. The [importer](../import_law19_html.py)
can reproduce the catalogue from a saved copy of the HTML:

```sh
python data/source_catalog/import_law19_html.py /path/to/law19.html --output /path/to/new-catalogue
```

The importer parses local HTML without executing scripts or fetching linked
assets. An existing output directory is preserved rather than overwritten.
The older `../law19/` directory retains the initial paragraph/video catalogue;
use this full document and the complete coverage specification for new work.
