"""Extract Law 19 text and illustration references from user-supplied HTML.

Only the saved HTML is parsed. This module executes no scripts, makes no
network requests, and does not label any match footage as an infringement.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
from typing import Iterator
from urllib.parse import urljoin, urlsplit


DECLARED_SOURCE_URL = "https://passport.world.rugby/laws-of-the-game/laws-by-number/19-scrum/"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
IGNORED_TAGS = {"script", "style", "template"}


class LawImportError(ValueError):
    """The HTML cannot be catalogued without an ambiguous or unsafe result."""


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)

    def has_class(self, name: str) -> bool:
        return name in self.attrs.get("class", "").split()


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "video":
            for key in ["data-video-id", "data-account", "data-player"]:
                if sum(name == key for name, _ in attrs) > 1:
                    raise LawImportError(f"Duplicate video attribute: {key}")
        node = Node(tag, {name: value or "" for name, value in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _walk(node: Node) -> Iterator[Node]:
    if node.tag in IGNORED_TAGS:
        return
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from _walk(child)


def _text(node: Node, *, omit_sanction: bool = False, paragraph: bool = False, omit_links: bool = False) -> str:
    """Return literal visible words, normalizing HTML layout whitespace only."""
    fragments: list[str] = []

    def collect(current: Node) -> None:
        if current.tag in IGNORED_TAGS or current.tag == "video":
            return
        if current is not node and (current.has_class("modal") or current.has_class("brightcode-multi-video-modal-container")):
            return
        if omit_sanction and current.has_class("law-sanction"):
            return
        if omit_links and current.tag == "a":
            return
        if paragraph and current is not node and current.tag == "p":
            return
        block_boundary = current is not node and current.tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "figcaption"}
        if block_boundary:
            fragments.append(" ")
        if current.tag == "br":
            fragments.append(" ")
        for child in current.children:
            if isinstance(child, str):
                fragments.append(child)
            else:
                collect(child)
        if block_boundary:
            fragments.append(" ")

    collect(node)
    return re.sub(r"\s+", " ", "".join(fragments)).strip()


def _paragraph_nodes(node: Node) -> Iterator[Node]:
    yield node
    for child in node.children:
        if isinstance(child, Node) and child.tag not in IGNORED_TAGS and child.tag != "p":
            yield from _paragraph_nodes(child)


def _ancestor(node: Node, predicate) -> Node | None:
    current = node.parent
    while current is not None:
        if predicate(current):
            return current
        current = current.parent
    return None


def _qualifications(node: Node) -> list[str]:
    labels = []
    current = node.parent
    while current is not None:
        if current.has_class("alert"):
            for heading in _walk(current):
                if heading.tag in {"h5", "h6"} and _text(heading).upper() == "GLOBAL LAW TRIAL":
                    labels.append("GLOBAL LAW TRIAL")
        current = current.parent
    return list(dict.fromkeys(labels))


def _provider_id(value: str, name: str, pattern: str) -> str:
    if not re.fullmatch(pattern, value):
        raise LawImportError(f"Invalid or missing {name} on a reference video")
    return value


def _noncontent(node: Node) -> bool:
    """Exclude page furniture and video controls, not the legal paragraphs."""
    return (
        node.tag in IGNORED_TAGS | {"video", "nav", "header", "footer", "button"}
        or node.has_class("modal")
        or node.has_class("brightcode-multi-video-modal-container")
        or node.attrs.get("data-toggle") == "modal"
        or "hidden" in node.attrs
        or node.attrs.get("aria-hidden", "").lower() == "true"
    )


def _content_walk(node: Node) -> Iterator[Node]:
    if _noncontent(node):
        return
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from _content_walk(child)


def _resolved_url(value: str | None) -> str | None:
    """Resolve references only; no URL is requested or made executable."""
    if not value:
        return None
    resolved = urljoin(DECLARED_SOURCE_URL, value)
    return resolved if urlsplit(resolved).scheme.lower() in {"http", "https"} else None


def _link(node: Node) -> dict:
    return {
        "text": _text(node),
        "href": node.attrs.get("href"),
        "resolved_url": _resolved_url(node.attrs.get("href")),
        "title": node.attrs.get("title"),
    }


def _law_references(text: str) -> list[dict]:
    """Retain explicit numbered/named references without inventing their rules."""
    pattern = re.compile(
        r"(?<![\w.])(?:law\s+)?(?P<local>19\.[0-9]+)(?:\s*\((?P<letter>[a-z])\)|(?P<bare>[a-z]))?(?![\w.])"
        r"|(?<![\w.])law\s+(?P<other>[0-9]+(?:\.[0-9]+)?)(?:\s*\((?P<other_letter>[a-z])\)|(?P<other_bare>[a-z]))?(?![\w.])",
        re.IGNORECASE,
    )
    references = []
    for match in pattern.finditer(text):
        number = match.group("local") or match.group("other")
        letter = match.group("letter") or match.group("bare") or match.group("other_letter") or match.group("other_bare")
        references.append({
            "text": match.group(),
            "target": number + (f"({letter.lower()})" if letter else ""),
            "target_type": "law_clause",
            "character_start": match.start(),
            "character_end": match.end(),
        })
    for match in re.finditer(r"\bunder[-\s]19\s+scrum\s+law\s+variations\b", text, re.IGNORECASE):
        references.append({
            "text": match.group(),
            "target": "under_19_scrum_law_variations",
            "target_type": "named_external_variation",
            "character_start": match.start(),
            "character_end": match.end(),
        })
    return sorted(references, key=lambda item: item["character_start"])


def _table(node: Node, table_id: str, clause_id: str | None, section: str | None) -> tuple[dict, dict[int, str]]:
    rows = []
    row_ids = {}
    data_index = 0
    for row in _content_walk(node):
        if row.tag != "tr" or _ancestor(row, lambda item: item.tag == "table") is not node:
            continue
        cells = []
        for cell in _content_walk(row):
            if cell.tag not in {"th", "td"} or _ancestor(cell, lambda item: item.tag == "tr") is not row:
                continue
            spans = {}
            for name in ("rowspan", "colspan"):
                raw = cell.attrs.get(name, "1")
                if not re.fullmatch(r"[1-9][0-9]{0,4}", raw):
                    raise LawImportError(f"Invalid table {name}: {raw!r}")
                spans[name] = int(raw)
            cells.append({
                "tag": cell.tag,
                "text": _text(cell),
                **spans,
                "links": [_link(item) for item in _content_walk(cell) if item.tag == "a" and "href" in item.attrs],
            })
        is_header = bool(cells) and all(cell["tag"] == "th" for cell in cells)
        if not is_header:
            data_index += 1
        item_id = None if is_header else (f"restart_{data_index:02d}" if clause_id == "19.1" else f"{table_id}_row_{data_index:02d}")
        record = {"row_index": len(rows), "item_id": item_id, "is_header": is_header, "cells": cells}
        rows.append(record)
        if item_id:
            row_ids[id(row)] = item_id
    captions = [item for item in _content_walk(node) if item.tag == "caption"]
    return {
        "table_id": table_id,
        "context_clause_id": clause_id,
        "context_association": "preceding_clause_in_same_section" if clause_id else "section_only",
        "section": section,
        "caption": _text(captions[0]) if captions else None,
        "rows": rows,
        "header_rows": [row for row in rows if row["is_header"]],
        "body_rows": [row for row in rows if not row["is_header"]],
    }, row_ids


def _body_snapshot(container: Node) -> str:
    """Visible law-body words in order, with explicit table-cell boundaries."""
    fragments = []
    block_tags = {"div", "section", "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "figure", "figcaption"}

    def collect(node: Node) -> None:
        if _noncontent(node):
            return
        if node.tag == "table":
            fragments.append("\n")
            for row in _content_walk(node):
                if row.tag == "tr" and _ancestor(row, lambda item: item.tag == "table") is node:
                    cells = [cell for cell in _content_walk(row) if cell.tag in {"td", "th"} and _ancestor(cell, lambda item: item.tag == "tr") is row]
                    fragments.append("\t".join(_text(cell) for cell in cells) + "\n")
            return
        if node.tag in block_tags or node.tag == "br":
            fragments.append("\n")
        for child in node.children:
            if isinstance(child, str):
                fragments.append(child)
            else:
                collect(child)
        if node.tag in block_tags:
            fragments.append("\n")

    collect(container)
    lines = []
    for line in "".join(fragments).splitlines():
        normalized = "\t".join(re.sub(r"\s+", " ", cell).strip() for cell in line.split("\t")).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


def _extract_document(container: Node, clauses: list[dict], videos: list[dict], clause_nodes: dict[int, str]) -> dict:
    """Describe the supplied law body, retaining assets as references only."""
    by_id = {row["clause_id"]: row for row in clauses}
    course = _ancestor(container, lambda item: item.attrs.get("id") == "course-content-area")
    titles = [item for item in _walk(course) if item.tag == "h1"] if course else []
    title = _text(titles[0]) if titles else None
    headings, sections, blocks, tables, images, captions, non_numbered, cross_references = [], [], [], [], [], [], [], []
    section = section_id = clause_id = None
    current_section = None
    pending_images = []
    table_rows = {}

    def add_block(block: dict) -> None:
        block.update({"section": section, "section_id": section_id})
        blocks.append(block)
        if current_section is not None:
            current_section["block_ids"].append(block["block_id"])

    def add_text_references(text: str, item_id: str, context_clause: str | None) -> None:
        for reference in _law_references(text):
            cross_references.append({
                "kind": "textual_reference", "context_item_id": item_id,
                "context_clause_id": context_clause, "section": section,
                "context_text": text, **reference, "href": None, "resolved_url": None,
                "external_content_included": False,
            })

    for node in _content_walk(container):
        if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            if _ancestor(node, lambda item: item.tag == "table"):
                continue
            pending_images = []
            text = _text(node)
            if node.tag == "h3":
                section, clause_id = text, None
                section_id = f"section_{len(sections) + 1:02d}"
                current_section = {"section_id": section_id, "heading": text, "heading_level": 3, "block_ids": []}
                sections.append(current_section)
            heading_id = f"heading_{len(headings) + 1:02d}"
            record = {"block_id": heading_id, "type": "heading", "level": int(node.tag[1]), "text": text, "parent_section_id": section_id if node.tag != "h3" else None}
            add_block(record)
            headings.append(record)
            add_text_references(text, heading_id, clause_id)
        elif node.tag == "table":
            if _ancestor(node, lambda item: item.tag == "table"):
                continue
            pending_images = []
            table_id = f"table_{len(tables) + 1:02d}"
            record, row_ids = _table(node, table_id, clause_id, section)
            table_rows.update(row_ids)
            tables.append(record)
            add_block({"block_id": table_id, "type": "table", "table_id": table_id, "context_clause_id": clause_id})
            for row in _content_walk(node):
                if row.tag == "tr" and _ancestor(row, lambda item: item.tag == "table") is node:
                    for cell in _content_walk(row):
                        if cell.tag in {"td", "th"} and _ancestor(cell, lambda item: item.tag == "tr") is row:
                            add_text_references(_text(cell, omit_links=True), row_ids.get(id(row), table_id), clause_id)
        elif node.tag == "img":
            image_id = f"diagram_{len(images) + 1:02d}"
            image = {
                "item_id": image_id, "src": node.attrs.get("src"),
                "resolved_src": _resolved_url(node.attrs.get("src")), "alt": node.attrs.get("alt"),
                "width": node.attrs.get("width"), "height": node.attrs.get("height"),
                "caption": None, "caption_clause_references": [],
                "context_clause_id": clause_id, "section": section,
                "context_association": "preceding_clause_in_same_section" if clause_id else "section_only",
                "semantic_clause_assignment": None,
                "downloaded": False, "content_inspected": False,
            }
            images.append(image)
            pending_images.append(image)
            add_block({"block_id": image_id, "type": "image", "item_id": image_id, "context_clause_id": clause_id})
        elif node.tag == "p" or node.tag == "figcaption":
            if _ancestor(node, lambda item: item.tag in {"table", "p"}):
                continue
            text = _text(node, paragraph=True)
            actual_id = clause_nodes.get(id(node))
            if actual_id:
                pending_images = []
                clause_id = actual_id
                record = by_id[actual_id]
                add_block({"block_id": f"clause:{actual_id}", "type": "clause", "clause_id": actual_id, "text": record["raw_paragraph_text"]})
                reference_text = _text(node, paragraph=True, omit_sanction=True, omit_links=True)
                reference_text = re.sub(r"^(?:19\.[0-9]+|[a-z]\.)\s*", "", reference_text)
                add_text_references(reference_text, actual_id, actual_id)
            elif text and (node.has_class("image-figure") or node.tag == "figcaption"):
                caption_id = f"caption_{len(captions) + 1:02d}"
                references = _law_references(text)
                caption = {"caption_id": caption_id, "text": text, "image_ids": [item["item_id"] for item in pending_images], "association_status": "adjacent_images" if pending_images else "unassigned"}
                for image in pending_images:
                    image["caption"] = text
                    image["caption_clause_references"] = [item["target"] for item in references if item["target_type"] == "law_clause"]
                captions.append(caption)
                add_block({"block_id": caption_id, "type": "image_caption", **caption})
                add_text_references(_text(node, omit_links=True), caption_id, clause_id)
                pending_images = []
            elif text:
                pending_images = []
                item_id = "principle" if section == "Principle" and not any(item["item_id"] == "principle" for item in non_numbered) else f"paragraph_{len(non_numbered) + 1:02d}"
                record = {"block_id": item_id, "item_id": item_id, "type": "non_numbered_paragraph", "text": text, "context_clause_id": clause_id}
                add_block(record)
                non_numbered.append(record)
                add_text_references(_text(node, omit_links=True), item_id, clause_id)
        elif node.tag == "a" and "href" in node.attrs:
            row = _ancestor(node, lambda item: item.tag == "tr")
            context_item = table_rows.get(id(row)) if row else None
            cross_references.append({
                "kind": "hyperlink", "context_item_id": context_item or clause_id,
                "context_clause_id": clause_id, "section": section, **_link(node),
                "targets": _law_references(_text(node)), "external_content_included": False,
            })
    for index, record in enumerate(cross_references, 1):
        record["reference_id"] = f"reference_{index:03d}"
    principle = [item for item in non_numbered if item["section"] == "Principle"]
    authority = by_id.get("19.39")
    return {
        "title": title,
        "declared_source_url": DECLARED_SOURCE_URL,
        "content_scope": ".page-law-number-page; article h1 retained separately; navigation, footer, scripts, modal player UI excluded",
        "headings": headings, "sections": sections, "blocks": blocks,
        "principle": {"item_id": "principle", "paragraphs": [item["text"] for item in principle], "text": "\n".join(item["text"] for item in principle)},
        "non_numbered_paragraphs": non_numbered,
        "tables": tables, "images": images, "image_captions": captions,
        "cross_references": cross_references,
        "variation_authority": {"clause_id": "19.39", "text": authority["law_text"], "external_rules_included": False, "linked_variation_url": None} if authority else None,
        "visible_body_text": _body_snapshot(container),
        "clauses": clauses, "reference_videos": videos,
        "scope_notes": [
            "Asset URLs and alt/caption text are literal source metadata; image pixels and reference videos were not downloaded or inspected.",
            "Preceding-clause image context records document order, not an exclusive interpretation of what a diagram depicts.",
            "Out-of-page laws and law variations are referenced only; their contents and historical applicability are not part of this supplied source.",
            "Visible text normalizes HTML layout whitespace; table cells retain explicit boundaries. This is not a rendered-browser or image transcription.",
        ],
    }


def extract_catalog(html_text: str) -> dict:
    """Extract clause/video records and a structured snapshot of the law body.

    Lettered clauses inherit the last major number, not the last subclause.
    A new major clause or h3 resets the active association. Unattached videos
    remain explicitly unassigned and produce a warning instead of guessing.
    """
    parser = _TreeParser()
    parser.feed(html_text)
    parser.close()
    containers = [node for node in _walk(parser.root) if node.has_class("page-law-number-page")]
    if len(containers) != 1:
        raise LawImportError("Expected exactly one page-law-number-page content container")
    clauses: list[dict] = []
    videos: list[dict] = []
    warnings: list[str] = []
    by_id: dict[str, dict] = {}
    clause_nodes: dict[int, str] = {}
    section = None
    major_id = None
    actual_id = None
    seen_references = set()

    for node in _walk(containers[0]):
        if node.tag in {"nav", "header", "footer"} or _ancestor(node, lambda item: item.tag in {"nav", "header", "footer"}):
            continue
        if node.tag == "h3":
            section = _text(node)
            major_id = actual_id = None
        if node.tag == "p":
            local_nodes = list(_paragraph_nodes(node))
            major_markers = [item for item in local_nodes if item.has_class("law-item-level-1")]
            child_markers = [item for item in local_nodes if item.has_class("law-number-level-1")]
            if len(major_markers) > 1 or len(child_markers) > 1 or major_markers and child_markers:
                raise LawImportError("Ambiguous law numbering inside one paragraph")
            marker = None
            parent_id = None
            if major_markers:
                marker = _text(major_markers[0])
                if not re.fullmatch(r"19\.[1-9][0-9]*", marker):
                    raise LawImportError(f"Invalid Law 19 major number: {marker!r}")
                major_id = actual_id = marker
            elif node.has_class("law-item-level-2") and child_markers:
                marker = _text(child_markers[0])
                letter = re.fullmatch(r"([a-z])\.", marker)
                if major_id is None or not letter:
                    raise LawImportError("Lettered clause has no valid current major number")
                parent_id = major_id
                actual_id = f"{major_id}({letter.group(1)})"
            if marker is not None:
                if actual_id in by_id:
                    raise LawImportError(f"Duplicate law clause: {actual_id}")
                raw = _text(node, paragraph=True)
                law_text = _text(node, omit_sanction=True, paragraph=True)
                if not law_text.startswith(marker):
                    raise LawImportError(f"Unexpected paragraph numbering for {actual_id}")
                law_text = law_text[len(marker):].strip()
                sanctions = [_text(item) for item in local_nodes if item.has_class("sanction-description")]
                if len(sanctions) > 1:
                    raise LawImportError(f"Multiple explicit sanctions require manual extraction: {actual_id}")
                explicit = sanctions[0] if sanctions else None
                labels = _qualifications(node)
                record = {
                    "clause_id": actual_id,
                    "parent_clause_id": parent_id,
                    "section": section,
                    "raw_paragraph_text": raw,
                    "law_text": law_text,
                    "printed_explicit_sanction": explicit,
                    "sanction_scope": "printed_text_requires_clause_and_parent_context" if explicit else None,
                    "sanction_qualification_quote": None,
                    "inherited_parent_context": by_id[parent_id]["law_text"] if parent_id else None,
                    "qualification_labels": labels,
                    "global_law_trial": "GLOBAL LAW TRIAL" in labels,
                    "automatic_infringement_label": None,
                }
                if actual_id == "19.34(e)" and explicit:
                    exception = re.search(r"\bException:\s*(.+)$", law_text)
                    if exception:
                        record["sanction_scope"] = "conditional_exception_only"
                        record["sanction_qualification_quote"] = "Exception: " + exception.group(1)
                    else:
                        record["sanction_scope"] = "manual_source_context_review_required"
                        warnings.append("19.34(e) prints a sanction but no Exception marker; do not automatically apply it")
                clauses.append(record)
                by_id[actual_id] = record
                clause_nodes[id(node)] = actual_id
        if node.tag == "video":
            account = _provider_id(node.attrs.get("data-account", ""), "data-account", r"[0-9]{1,30}")
            player = _provider_id(node.attrs.get("data-player", ""), "data-player", r"[A-Za-z0-9_-]{1,100}")
            video_id = _provider_id(node.attrs.get("data-video-id", ""), "data-video-id", r"[0-9]{1,30}")
            modal = _ancestor(node, lambda item: item.has_class("modal") and bool(item.attrs.get("id")))
            modal_id = modal.attrs["id"] if modal else None
            identity = (actual_id, modal_id, account, player, video_id)
            if identity in seen_references:
                raise LawImportError(f"Duplicate video reference for clause {actual_id}: {video_id}")
            seen_references.add(identity)
            clause = by_id.get(actual_id, {})
            if actual_id is None:
                warnings.append(f"Video {video_id} has no preceding clause in this section; association left unassigned")
            videos.append({
                "clause_id": actual_id,
                "parent_clause_id": clause.get("parent_clause_id"),
                "section": section,
                "modal_id": modal_id,
                "provider": "Brightcove",
                "account_id": account,
                "player_id": player,
                "video_id": video_id,
                "constructed_player_url": f"https://players.brightcove.net/{account}/{player}_default/index.html?videoId={video_id}",
                "association_status": "associated_from_document_order" if actual_id else "unassigned",
                "raw_paragraph_text": clause.get("raw_paragraph_text"),
                "printed_explicit_sanction": clause.get("printed_explicit_sanction"),
                "sanction_scope": clause.get("sanction_scope"),
                "sanction_qualification_quote": clause.get("sanction_qualification_quote"),
                "inherited_parent_context": clause.get("inherited_parent_context"),
                "global_law_trial": clause.get("global_law_trial", False),
                "role": "official_rule_reference",
                "playback_verified": False,
                "video_file": None,
                "camera_view": "unknown",
                "automatic_infringement_label": None,
            })
    if not clauses:
        raise LawImportError("No Law 19 clauses found")
    return {
        "clauses": clauses, "videos": videos, "warnings": warnings,
        "document": _extract_document(containers[0], clauses, videos, clause_nodes),
    }


def import_source(html_path: Path, output_dir: Path) -> dict:
    """Write a locally reproducible catalog, refusing existing output folders."""
    html_path, output_dir = Path(html_path), Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise LawImportError(f"Output already exists: {output_dir}")
    source_bytes = html_path.read_bytes()
    try:
        text = source_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise LawImportError("Expected UTF-8 HTML input") from error
    catalog = extract_catalog(text)
    provenance = {
        "acquisition_method": "user_supplied_html",
        "declared_source_url": DECLARED_SOURCE_URL,
        "source_filename": html_path.name,
        "source_bytes": len(source_bytes),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "independently_fetched": False,
        "edition_date": None,
        "historical_applicability_verified": False,
        "script_execution": False,
        "reference_role": "official_rule_reference_not_match_ground_truth",
        "association_method": "Last actual clause in document order; reset on new major clause or h3",
        "text_handling": "Literal visible paragraph text; HTML layout whitespace normalized, entities decoded",
        "catalog_scope": "Clause/video records remain numbered paragraphs and embed metadata. law19_document.json additionally preserves the principle, section headings, complete 19.1 restart table cells, diagram metadata, cross-references and a scoped visible-body text snapshot.",
        "assets_downloaded": False,
        "asset_content_inspected": False,
        "external_law_contents_included": False,
        "document_scope_note": "HTML assets are referenced, not downloaded or inspected. Out-of-page laws and law variations are not part of the supplied source. The text snapshot does not transcribe image pixels or establish historical applicability.",
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".law19-import-", dir=output_dir.parent) as temporary:
        staging = Path(temporary) / "catalog"
        staging.mkdir()
        document = {"schema_version": 1, "source_provenance": provenance, "clauses": catalog["clauses"], "warnings": catalog["warnings"]}
        (staging / "law19_clauses.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        full_document = {"schema_version": 1, "source_provenance": provenance, **catalog["document"], "warnings": catalog["warnings"]}
        (staging / "law19_document.json").write_text(json.dumps(full_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "source_provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fields = list(catalog["videos"][0]) if catalog["videos"] else ["clause_id", "parent_clause_id", "section", "modal_id", "provider", "account_id", "player_id", "video_id", "constructed_player_url", "association_status", "raw_paragraph_text", "printed_explicit_sanction", "sanction_scope", "sanction_qualification_quote", "inherited_parent_context", "global_law_trial", "role", "playback_verified", "video_file", "camera_view", "automatic_infringement_label"]
        with (staging / "law19_reference_videos.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for record in catalog["videos"]:
                writer.writerow({key: str(value).lower() if isinstance(value, bool) else value for key, value in record.items()})
        if output_dir.exists() or output_dir.is_symlink():
            raise LawImportError(f"Output appeared during import: {output_dir}")
        staging.rename(output_dir)
    return {
        "clauses": len(catalog["clauses"]),
        "major_clauses": sum(row["parent_clause_id"] is None for row in catalog["clauses"]),
        "videos": len(catalog["videos"]),
        "associated_videos": sum(row["clause_id"] is not None for row in catalog["videos"]),
        "tables": len(catalog["document"]["tables"]),
        "table_body_rows": sum(len(table["body_rows"]) for table in catalog["document"]["tables"]),
        "images": len(catalog["document"]["images"]),
        "cross_references": len(catalog["document"]["cross_references"]),
        "source_sha256": provenance["source_sha256"],
        "warnings": catalog["warnings"],
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html_path", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = import_source(args.html_path, args.output)
    except (LawImportError, OSError) as error:
        parser.exit(1, f"Law 19 import failed: {error}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
