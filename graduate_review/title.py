from __future__ import annotations

import re
from pathlib import Path

import fitz
from docx import Document

from .llm import LLMClient
from .utils import clean_text, truncate


TITLE_STOP_PATTERNS = [
    r"^摘要[:：]?",
    r"^abstract[:：]?",
    r"^关键词[:：]?",
    r"^key\s*words?[:：]?",
]

AUTHOR_LINE_PATTERNS = [
    r"school of",
    r"学院",
    r"专业",
    r"学号",
    r"指导教师",
    r"作者",
    r"student",
    r"college",
    r"university",
]


def _clean_lines(lines: list[str]) -> list[str]:
    return [clean_text(line) for line in lines if clean_text(line)]


def _stop_index(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        lowered = line.lower()
        if any(re.match(pattern, lowered, re.IGNORECASE) for pattern in TITLE_STOP_PATTERNS):
            return index
    return len(lines)


def _looks_like_author_line(line: str) -> bool:
    lowered = line.lower()
    return any(pattern in lowered for pattern in AUTHOR_LINE_PATTERNS)


def _extract_docx_title_page_lines(source_path: Path) -> list[str]:
    document = Document(str(source_path))
    lines = []
    for paragraph in document.paragraphs[:20]:
        text = clean_text(paragraph.text)
        if text:
            lines.append(text)
    return _clean_lines(lines)


def _extract_pdf_title_page_lines(source_path: Path) -> list[str]:
    document = fitz.open(source_path)
    first_page_text = document.load_page(0).get_text("text") if document.page_count else ""
    return _clean_lines(first_page_text.splitlines())


def extract_title_page_excerpt(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix == ".docx":
        lines = _extract_docx_title_page_lines(source_path)
    elif suffix == ".pdf":
        lines = _extract_pdf_title_page_lines(source_path)
    else:
        lines = []
    stop = _stop_index(lines)
    excerpt_lines = lines[: max(stop, min(len(lines), 8))]
    return truncate("\n".join(excerpt_lines), 1800)


def guess_title_from_title_page(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix == ".docx":
        lines = _extract_docx_title_page_lines(source_path)
    elif suffix == ".pdf":
        lines = _extract_pdf_title_page_lines(source_path)
    else:
        lines = []

    stop = _stop_index(lines)
    candidate_lines = []
    for line in lines[:stop]:
        if _looks_like_author_line(line):
            continue
        if len(line) < 6 or len(line) > 140:
            continue
        if re.fullmatch(r"[A-Za-z]", line):
            continue
        candidate_lines.append(line)
        if len(candidate_lines) >= 3:
            break

    if candidate_lines:
        title = " ".join(candidate_lines[:2]).strip()
        return truncate(title, 180)

    fallback_lines = [line for line in lines[:stop] if not _looks_like_author_line(line)]
    if fallback_lines:
        return truncate(max(fallback_lines, key=len), 180)
    return ""


async def infer_title_with_llm(source_path: Path, llm_settings: dict) -> str:
    llm_client = LLMClient(llm_settings)
    if not llm_client.configured:
        return ""
    excerpt = extract_title_page_excerpt(source_path)
    if not excerpt:
        return ""
    content = await llm_client.chat(
        [
            {
                "role": "system",
                "content": "你是论文标题抽取助手。请从标题页或首页文字中识别论文标题，只返回标题本身，不要解释，不要加引号。",
            },
            {
                "role": "user",
                "content": f"请从下面内容中识别论文标题。若无法可靠判断，只返回空字符串。\n\n{excerpt}",
            },
        ],
        max_tokens=96,
        timeout_seconds=90.0,
    )
    title = clean_text(str(content))
    if not title:
        return ""
    if len(title) > 180:
        title = title[:180].strip()
    if any(marker in title.lower() for marker in ["摘要", "abstract", "keywords", "key words"]):
        return ""
    return title
