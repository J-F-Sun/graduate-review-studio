from __future__ import annotations

import statistics
from pathlib import Path

import fitz
import pdfplumber

from ..storage import Storage
from ..utils import clean_text, slugify, truncate
from .common import (
    StructureBuilder,
    infer_heading_level,
    looks_like_figure_caption,
    looks_like_table_caption,
    split_inline_preface_heading,
)


def _extract_text_blocks(page_dict: dict) -> list[dict]:
    blocks: list[dict] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        font_sizes = []
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            line_text = clean_text(line_text)
            if line_text:
                lines.append(line_text)
            font_sizes.extend(
                span.get("size", 0)
                for span in line.get("spans", [])
                if span.get("text", "").strip()
            )
        text = clean_text(" ".join(lines))
        if not text:
            continue
        blocks.append(
            {
                "text": text,
                "bbox": block.get("bbox"),
                "font_size": max(font_sizes or [0]),
            }
        )
    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return blocks


def _heading_level(text: str, font_size: float, median_font: float) -> int | None:
    inferred = infer_heading_level(text)
    if inferred:
        return inferred
    if len(text) < 40 and font_size >= median_font * 1.2:
        return 2
    return None


def _nearest_caption(blocks: list[dict], y_anchor: float, *, kind: str) -> str:
    best = ""
    best_distance = None
    checker = looks_like_figure_caption if kind == "figure" else looks_like_table_caption
    for block in blocks:
        if not checker(block["text"]):
            continue
        y_center = (block["bbox"][1] + block["bbox"][3]) / 2
        distance = abs(y_center - y_anchor)
        if best_distance is None or distance < best_distance:
            best = block["text"]
            best_distance = distance
    return best


def parse_pdf(
    source_path: Path,
    *,
    storage: Storage,
    paper_id: str,
) -> dict:
    document = fitz.open(source_path)
    builder = StructureBuilder("pdf")
    parser_notes: list[str] = [
        "PDF 按文本块、字号、章节编号和常见标题词推断结构。",
        "PDF 表格使用 pdfplumber 进行抽取，复杂跨页表格可能需要人工复核。",
    ]

    all_font_sizes: list[float] = []
    page_blocks: dict[int, list[dict]] = {}
    for page_index in range(document.page_count):
        page = document.load_page(page_index)
        blocks = _extract_text_blocks(page.get_text("dict"))
        page_blocks[page_index + 1] = blocks
        all_font_sizes.extend(block["font_size"] for block in blocks if block["font_size"])
    median_font = statistics.median(all_font_sizes) if all_font_sizes else 11

    with pdfplumber.open(source_path) as pdf:
        for page_number in range(1, document.page_count + 1):
            blocks = page_blocks.get(page_number, [])
            for block_index, block in enumerate(blocks):
                block_anchor = {
                    "kind": "pdf_block",
                    "page": page_number,
                    "index": block_index,
                }
                inline_heading = split_inline_preface_heading(block["text"])
                if inline_heading:
                    heading_title, body = inline_heading
                    builder.add_heading(heading_title, 1, page_number=page_number, source_anchor=block_anchor)
                    if body:
                        builder.add_paragraph(body, role="body", page_number=page_number, source_anchor=block_anchor)
                    continue
                level = _heading_level(block["text"], block["font_size"], median_font)
                if level:
                    builder.add_heading(block["text"], level, page_number=page_number, source_anchor=block_anchor)
                    continue
                role = "caption" if looks_like_figure_caption(block["text"]) or looks_like_table_caption(block["text"]) else "body"
                builder.add_paragraph(block["text"], role=role, page_number=page_number, source_anchor=block_anchor)

            plumber_page = pdf.pages[page_number - 1]
            for index, table in enumerate(plumber_page.find_tables(), start=1):
                rows = table.extract() or []
                cleaned_rows = [[clean_text(cell or "") for cell in row] for row in rows]
                caption = _nearest_caption(blocks, table.bbox[1], kind="table") or f"第{page_number}页表格{index}"
                builder.add_table(
                    cleaned_rows,
                    caption=caption,
                    page_number=page_number,
                    source_anchor={
                        "kind": "pdf_table",
                        "page": page_number,
                        "index": index - 1,
                        "bbox": [float(value) for value in table.bbox],
                    },
                )

            page = document.load_page(page_number - 1)
            seen_xrefs: set[int] = set()
            for index, image in enumerate(page.get_images(full=True), start=1):
                xref = image[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                rect = rects[0]
                if rect.width * rect.height < 2500:
                    continue
                extracted = document.extract_image(xref)
                extension = extracted.get("ext", "png")
                filename = f"{slugify(f'page-{page_number}-image-{index}')}.{extension}"
                relative_path = storage.save_asset(
                    paper_id,
                    category="images",
                    filename=filename,
                    data=extracted["image"],
                )
                caption = _nearest_caption(blocks, rect.y1, kind="figure") or f"第{page_number}页图片{index}"
                nearby_text = " ".join(
                    block["text"]
                    for block in blocks
                    if abs(((block["bbox"][1] + block["bbox"][3]) / 2) - rect.y1) < 180
                )
                builder.add_image(
                    caption=caption,
                    page_number=page_number,
                    relative_path=relative_path,
                    nearby_text=truncate(nearby_text, 260),
                    width=int(rect.width),
                    height=int(rect.height),
                    analysis=f"图片来自 PDF 第{page_number}页，当前根据图题和邻近文本推断其主题与“{truncate(caption, 120)}”相关。",
                    analysis_status="context-only",
                    source_anchor={
                        "kind": "pdf_image",
                        "page": page_number,
                        "index": index - 1,
                        "xref": xref,
                    },
                )

    parsed = builder.finalize()
    parsed["page_count"] = document.page_count
    parsed["parser_notes"] = parser_notes
    return parsed
