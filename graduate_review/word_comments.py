from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"

COMMENTS_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"

ET.register_namespace("w", W_NS)
ET.register_namespace("r", R_NS)
ET.register_namespace("", PKG_REL_NS)


@dataclass
class CommentSpec:
    paragraph_index: int
    text: str
    highlight_color: str | None = None


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def _w(name: str) -> str:
    return _tag(W_NS, name)


def _pkg_rel(name: str) -> str:
    return _tag(PKG_REL_NS, name)


def _content_type(name: str) -> str:
    return _tag(CONTENT_TYPES_NS, name)


def _new_comment_reference_run(comment_id: int) -> ET.Element:
    run = ET.Element(_w("r"))
    run_props = ET.SubElement(run, _w("rPr"))
    ET.SubElement(run_props, _w("rStyle"), {_w("val"): "CommentReference"})
    ET.SubElement(run, _w("commentReference"), {_w("id"): str(comment_id)})
    return run


def _comment_paragraph(text: str, *, include_ref: bool) -> ET.Element:
    paragraph = ET.Element(_w("p"))
    if include_ref:
        ref_run = ET.SubElement(paragraph, _w("r"))
        ref_props = ET.SubElement(ref_run, _w("rPr"))
        ET.SubElement(ref_props, _w("rStyle"), {_w("val"): "CommentReference"})
        ET.SubElement(ref_run, _w("annotationRef"))
    text_run = ET.SubElement(paragraph, _w("r"))
    text_element = ET.SubElement(text_run, _w("t"))
    if text[:1].isspace() or text[-1:].isspace():
        text_element.set(_tag(XML_NS, "space"), "preserve")
    text_element.text = text
    return paragraph


def _append_comment_to_paragraph(paragraph: ET.Element, comment_id: int) -> None:
    children = list(paragraph)
    has_content = any(child.tag != _w("pPr") for child in children)
    if not has_content:
        run = ET.SubElement(paragraph, _w("r"))
        ET.SubElement(run, _w("t")).text = ""
        children = list(paragraph)

    insert_pos = 1 if children and children[0].tag == _w("pPr") else 0
    paragraph.insert(insert_pos, ET.Element(_w("commentRangeStart"), {_w("id"): str(comment_id)}))
    paragraph.append(ET.Element(_w("commentRangeEnd"), {_w("id"): str(comment_id)}))
    paragraph.append(_new_comment_reference_run(comment_id))


def _apply_highlight_to_paragraph(paragraph: ET.Element, color: str | None) -> None:
    if not color or color == "none":
        return

    runs = [child for child in list(paragraph) if child.tag == _w("r")]
    if not runs:
        run = ET.SubElement(paragraph, _w("r"))
        ET.SubElement(run, _w("t")).text = ""
        runs = [run]

    for run in runs:
        if run.find(_w("commentReference")) is not None:
            continue
        run_props = run.find(_w("rPr"))
        if run_props is None:
            run_props = ET.Element(_w("rPr"))
            run.insert(0, run_props)
        highlight = run_props.find(_w("highlight"))
        if highlight is None:
            highlight = ET.SubElement(run_props, _w("highlight"))
        highlight.set(_w("val"), color)


def _next_relationship_id(rels_root: ET.Element) -> str:
    used_numbers = []
    for rel in rels_root.findall(_pkg_rel("Relationship")):
        rel_id = rel.get("Id", "")
        if rel_id.startswith("rId") and rel_id[3:].isdigit():
            used_numbers.append(int(rel_id[3:]))
    next_number = 1
    while next_number in used_numbers:
        next_number += 1
    return f"rId{next_number}"


def _ensure_comments_relationship(rels_root: ET.Element) -> None:
    for rel in rels_root.findall(_pkg_rel("Relationship")):
        if rel.get("Type") == COMMENTS_REL_TYPE:
            return
    ET.SubElement(
        rels_root,
        _pkg_rel("Relationship"),
        {
            "Id": _next_relationship_id(rels_root),
            "Type": COMMENTS_REL_TYPE,
            "Target": "comments.xml",
        },
    )


def _ensure_comments_override(content_types_root: ET.Element) -> None:
    for override in content_types_root.findall(_content_type("Override")):
        if override.get("PartName") == "/word/comments.xml":
            return
    ET.SubElement(
        content_types_root,
        _content_type("Override"),
        {
            "PartName": "/word/comments.xml",
            "ContentType": COMMENTS_CONTENT_TYPE,
        },
    )


def _comment_id_sequence(comments_root: ET.Element) -> Iterable[int]:
    used_ids = []
    for comment in comments_root.findall(_w("comment")):
        comment_id = comment.get(_w("id")) or comment.get("w:id")
        if comment_id and str(comment_id).isdigit():
            used_ids.append(int(comment_id))
    next_id = (max(used_ids) + 1) if used_ids else 0
    while True:
        yield next_id
        next_id += 1


def inject_comments_into_docx(
    docx_path: Path,
    comments: list[CommentSpec],
    *,
    author: str,
    initials: str,
) -> None:
    if not comments:
        return

    with ZipFile(docx_path, "r") as input_zip:
        archive = {name: input_zip.read(name) for name in input_zip.namelist()}

    document_root = ET.fromstring(archive["word/document.xml"])
    body = document_root.find(_w("body"))
    if body is None:
        return
    body_paragraphs = [child for child in list(body) if child.tag == _w("p")]

    comments_root = (
        ET.fromstring(archive["word/comments.xml"])
        if "word/comments.xml" in archive
        else ET.Element(_w("comments"))
    )
    rels_root = (
        ET.fromstring(archive["word/_rels/document.xml.rels"])
        if "word/_rels/document.xml.rels" in archive
        else ET.Element(_pkg_rel("Relationships"))
    )
    content_types_root = ET.fromstring(archive["[Content_Types].xml"])

    _ensure_comments_relationship(rels_root)
    _ensure_comments_override(content_types_root)
    comment_ids = _comment_id_sequence(comments_root)

    for spec in comments:
        if spec.paragraph_index < 0 or spec.paragraph_index >= len(body_paragraphs):
            continue
        comment_id = next(comment_ids)
        target_paragraph = body_paragraphs[spec.paragraph_index]
        _apply_highlight_to_paragraph(target_paragraph, spec.highlight_color)
        _append_comment_to_paragraph(target_paragraph, comment_id)

        comment = ET.SubElement(
            comments_root,
            _w("comment"),
            {
                _w("id"): str(comment_id),
                _w("author"): author,
                _w("initials"): initials,
                _w("date"): datetime.now(timezone.utc).isoformat(),
            },
        )
        lines = [line.strip() for line in spec.text.split("\n") if line.strip()] or ["审稿意见"]
        for index, line in enumerate(lines):
            comment.append(_comment_paragraph(line, include_ref=index == 0))

    archive["word/document.xml"] = ET.tostring(document_root, encoding="utf-8", xml_declaration=True)
    archive["word/comments.xml"] = ET.tostring(comments_root, encoding="utf-8", xml_declaration=True)
    ET.register_namespace("", PKG_REL_NS)
    archive["word/_rels/document.xml.rels"] = ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)
    ET.register_namespace("", CONTENT_TYPES_NS)
    archive["[Content_Types].xml"] = ET.tostring(content_types_root, encoding="utf-8", xml_declaration=True)

    with NamedTemporaryFile("wb", suffix=".docx", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    with ZipFile(temp_path, "w", compression=ZIP_DEFLATED) as output_zip:
        for name, data in archive.items():
            output_zip.writestr(name, data)

    temp_path.replace(docx_path)
