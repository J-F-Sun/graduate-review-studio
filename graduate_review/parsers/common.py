from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..utils import clean_text, new_id, split_sentences, truncate

CHAPTER_PATTERN = re.compile(r"^\s*第[一二三四五六七八九十百零0-9]+章")
SECTION_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+){0,3})(?:[\s\u3000]+|(?=[\u4e00-\u9fffA-Za-z(（]))")
COMMON_TOP_LEVEL = {
    "摘要",
    "abstract",
    "英文摘要",
    "关键词",
    "关键字",
    "keywords",
    "引言",
    "绪论",
    "目录",
    "参考文献",
    "致谢",
    "附录",
    "结论",
    "总结",
}
KEYWORD_SECTION_TITLES = {"关键词", "关键字", "keywords", "key words"}
ACKNOWLEDGEMENT_TITLES = {"致谢", "acknowledgements", "acknowledgments"}
INLINE_PREFACE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(摘\s*要|摘要)\s*[：:]\s*(.+)$", re.IGNORECASE), "摘要"),
    (re.compile(r"^(abstract)\s*[：:]\s*(.+)$", re.IGNORECASE), "Abstract"),
    (re.compile(r"^(关\s*键\s*词|关键词|关键字)\s*[：:]\s*(.+)$", re.IGNORECASE), "关键词"),
    (re.compile(r"^(key\s*words?|keywords?)\s*[：:]\s*(.+)$", re.IGNORECASE), "Keywords"),
]


def looks_like_table_caption(text: str) -> bool:
    lowered = clean_text(text).lower()
    return bool(re.match(r"^(表|table)\s*[\d一二三四五六七八九十\-\.：: ]+", lowered))


def looks_like_figure_caption(text: str) -> bool:
    lowered = clean_text(text).lower()
    return bool(re.match(r"^(图|figure)\s*[\d一二三四五六七八九十\-\.：: ]+", lowered))


def split_inline_preface_heading(text: str) -> tuple[str, str] | None:
    stripped = clean_text(text)
    for pattern, normalized_title in INLINE_PREFACE_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return normalized_title, clean_text(match.group(2))
    return None


def is_keyword_section_title(text: str) -> bool:
    return clean_text(text).lower() in KEYWORD_SECTION_TITLES


def is_acknowledgement_title(text: str) -> bool:
    return clean_text(text).lower() in ACKNOWLEDGEMENT_TITLES


def looks_like_english_front_matter(text: str) -> bool:
    stripped = clean_text(text)
    lowered = stripped.lower()
    if not stripped:
        return False
    if any(lowered.startswith(prefix) for prefix in ("abstract:", "abstract：", "keywords:", "keywords：", "key words:", "key words：")):
        return False
    if re.search(r"[\u4e00-\u9fff]", stripped):
        return False
    if len(stripped) > 180 or len(stripped) < 8:
        return False
    if any(mark in stripped for mark in "。！？；"):
        return False
    if any(token in lowered for token in ("school of", "department of", "college of", "university", "institute", "faculty of")):
        return True
    alpha_count = sum(1 for ch in stripped if ch.isalpha())
    word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9\-()]*", stripped))
    if alpha_count >= 20 and 4 <= word_count <= 24 and not stripped.endswith("."):
        return True
    return False


def _looks_like_heading_candidate(text: str) -> bool:
    stripped = clean_text(text)
    if not stripped:
        return False
    if len(stripped) > 80:
        return False
    if any(mark in stripped for mark in "。！？；"):
        return False
    if "，" in stripped and len(stripped) > 20:
        return False
    return True


def infer_heading_level(text: str, style_level: int | None = None) -> int | None:
    stripped = clean_text(text)
    lowered = stripped.lower()
    if style_level:
        return style_level
    if lowered in COMMON_TOP_LEVEL:
        return 1
    if CHAPTER_PATTERN.match(stripped) and _looks_like_heading_candidate(stripped):
        return 1
    section_match = SECTION_PATTERN.match(stripped)
    if section_match and not _looks_like_heading_candidate(stripped):
        return None
    if section_match:
        number = section_match.group(1)
        return number.count(".") + 1
    return None


def infer_section_number(text: str) -> str:
    stripped = clean_text(text)
    if CHAPTER_PATTERN.match(stripped):
        return stripped.split()[0]
    match = SECTION_PATTERN.match(stripped)
    if match:
        return match.group(1)
    return ""


def format_location(section_path: list[str], page_number: int | None, element_label: str) -> str:
    parts = [part for part in section_path if part]
    if page_number:
        parts.append(f"第{page_number}页")
    parts.append(element_label)
    return " / ".join(parts)


@dataclass
class SectionState:
    id: str
    title: str
    level: int
    number: str
    parent_id: str | None
    source_anchor: dict[str, Any] | None = None
    page_start: int | None = None
    page_end: int | None = None
    child_ids: list[str] = field(default_factory=list)
    content_ids: list[str] = field(default_factory=list)


class StructureBuilder:
    def __init__(self, source_type: str) -> None:
        self.source_type = source_type
        self.sections: list[dict[str, Any]] = []
        self.paragraphs: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self._stack: list[SectionState] = []
        self._section_paragraph_counts: dict[str, int] = {}
        self._section_table_counts: dict[str, int] = {}
        self._section_image_counts: dict[str, int] = {}

    def _ensure_default_section(self) -> SectionState:
        if self._stack:
            return self._stack[-1]
        root = SectionState(
            id=new_id("section"),
            title="前置信息",
            level=1,
            number="",
            parent_id=None,
        )
        self.sections.append(self._serialize_section(root))
        self._stack.append(root)
        return root

    def _serialize_section(self, section: SectionState) -> dict[str, Any]:
        return {
            "id": section.id,
            "title": section.title,
            "level": section.level,
            "number": section.number,
            "parent_id": section.parent_id,
            "source_anchor": section.source_anchor,
            "page_start": section.page_start,
            "page_end": section.page_end,
            "child_ids": list(section.child_ids),
            "content_ids": list(section.content_ids),
            "path_titles": [],
        }

    def add_heading(
        self,
        title: str,
        level: int,
        page_number: int | None = None,
        source_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        title = clean_text(title)
        while self._stack and self._stack[-1].level >= level:
            self._stack.pop()
        parent = self._stack[-1] if self._stack else None
        section = SectionState(
            id=new_id("section"),
            title=title,
            level=level,
            number=infer_section_number(title),
            parent_id=parent.id if parent else None,
            source_anchor=source_anchor,
            page_start=page_number,
            page_end=page_number,
        )
        serialized = self._serialize_section(section)
        self.sections.append(serialized)
        self._stack.append(section)
        if parent:
            parent.child_ids.append(section.id)
            parent_record = self._find_section(parent.id)
            parent_record["child_ids"] = list(parent.child_ids)
        return serialized

    def _find_section(self, section_id: str) -> dict[str, Any]:
        for section in self.sections:
            if section["id"] == section_id:
                return section
        raise KeyError(section_id)

    def _current_section(self) -> dict[str, Any]:
        active = self._ensure_default_section()
        return self._find_section(active.id)

    def current_section_title(self) -> str:
        return self._current_section().get("title", "")

    def _section_path_titles(self, section_id: str) -> list[str]:
        mapping = {section["id"]: section for section in self.sections}
        titles: list[str] = []
        current = mapping.get(section_id)
        while current:
            titles.append(current["title"])
            current = mapping.get(current["parent_id"])
        return list(reversed(titles))

    def _touch_section_page(self, section_id: str, page_number: int | None) -> None:
        if not page_number:
            return
        current = self._find_section(section_id)
        if current["page_start"] is None or page_number < current["page_start"]:
            current["page_start"] = page_number
        if current["page_end"] is None or page_number > current["page_end"]:
            current["page_end"] = page_number

    def add_paragraph(
        self,
        text: str,
        *,
        role: str,
        page_number: int | None,
        source_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        section = self._current_section()
        section_id = section["id"]
        self._touch_section_page(section_id, page_number)
        count = self._section_paragraph_counts.get(section_id, 0) + 1
        self._section_paragraph_counts[section_id] = count
        paragraph_id = new_id("paragraph")
        section_path = self._section_path_titles(section_id)
        paragraph = {
            "id": paragraph_id,
            "section_id": section_id,
            "section_path_titles": section_path,
            "page_number": page_number,
            "role": role,
            "source_anchor": source_anchor,
            "text": clean_text(text),
            "sentences": split_sentences(text),
            "location_label": format_location(section_path, page_number, f"第{count}段"),
            "excerpt": truncate(text, 120),
        }
        self.paragraphs.append(paragraph)
        section["content_ids"].append(paragraph_id)
        return paragraph

    def add_table(
        self,
        rows: list[list[str]],
        *,
        caption: str,
        page_number: int | None,
        source_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        section = self._current_section()
        section_id = section["id"]
        self._touch_section_page(section_id, page_number)
        count = self._section_table_counts.get(section_id, 0) + 1
        self._section_table_counts[section_id] = count
        table_id = new_id("table")
        section_path = self._section_path_titles(section_id)
        preview_cells = [" | ".join(row) for row in rows[:3]]
        table = {
            "id": table_id,
            "section_id": section_id,
            "section_path_titles": section_path,
            "page_number": page_number,
            "source_anchor": source_anchor,
            "caption": clean_text(caption),
            "rows": rows,
            "location_label": format_location(section_path, page_number, f"表格{count}"),
            "preview": truncate(" ".join(preview_cells), 160),
        }
        self.tables.append(table)
        section["content_ids"].append(table_id)
        return table

    def add_image(
        self,
        *,
        caption: str,
        page_number: int | None,
        relative_path: str,
        nearby_text: str,
        width: int | None,
        height: int | None,
        analysis: str,
        analysis_status: str,
        source_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        section = self._current_section()
        section_id = section["id"]
        self._touch_section_page(section_id, page_number)
        count = self._section_image_counts.get(section_id, 0) + 1
        self._section_image_counts[section_id] = count
        image_id = new_id("image")
        section_path = self._section_path_titles(section_id)
        image = {
            "id": image_id,
            "section_id": section_id,
            "section_path_titles": section_path,
            "page_number": page_number,
            "source_anchor": source_anchor,
            "caption": clean_text(caption),
            "asset_relative_path": relative_path,
            "nearby_text": truncate(nearby_text, 260),
            "width": width,
            "height": height,
            "content_summary": clean_text(analysis),
            "analysis_status": analysis_status,
            "location_label": format_location(section_path, page_number, f"图片{count}"),
        }
        self.images.append(image)
        section["content_ids"].append(image_id)
        return image

    def finalize(self) -> dict[str, Any]:
        path_map = {section["id"]: self._section_path_titles(section["id"]) for section in self.sections}
        for section in self.sections:
            section["path_titles"] = path_map.get(section["id"], [])
        return {
            "source_type": self.source_type,
            "sections": self.sections,
            "paragraphs": self.paragraphs,
            "tables": self.tables,
            "images": self.images,
            "stats": {
                "section_count": len(self.sections),
                "paragraph_count": len(self.paragraphs),
                "table_count": len(self.tables),
                "image_count": len(self.images),
                "character_count": sum(len(paragraph["text"]) for paragraph in self.paragraphs),
            },
        }
