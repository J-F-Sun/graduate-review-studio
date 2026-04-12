from __future__ import annotations

from pathlib import Path

import fitz
from docx import Document

from .utils import clean_text


DEFAULT_RULES = [
    {
        "id": "builtin-structure",
        "title": "章节结构合理性",
        "body": "检查各章各节的安排是否完整、顺序是否合理、内容是否能支撑论文题目和研究目标。",
    },
    {
        "id": "builtin-logic",
        "title": "论述逻辑连贯性",
        "body": "检查章与章、节与节、段与段之间是否衔接自然，是否存在明显跳步、重复或论证缺口。",
    },
    {
        "id": "builtin-language",
        "title": "语言表达与可读性",
        "body": "定位语句不通顺、语法不当、指代不清、术语定义缺失等问题，并给出可执行的润色建议。",
    },
    {
        "id": "builtin-validation",
        "title": "实验与测试有效性",
        "body": "重点关注仿真实验、系统测试或案例验证是否足够，是否能支撑理论、算法或系统设计结论。",
    },
]


def extract_text_from_rule_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return clean_text(path.read_text(encoding="utf-8"))
    if suffix == ".docx":
        document = Document(str(path))
        return clean_text("\n".join(paragraph.text for paragraph in document.paragraphs))
    if suffix == ".pdf":
        document = fitz.open(path)
        pages = [clean_text(document.load_page(index).get_text("text")) for index in range(document.page_count)]
        return clean_text("\n".join(pages))
    raise ValueError(f"Unsupported rule file: {path.suffix}")


def parse_rule_content(content: str) -> list[dict]:
    items: list[dict] = []
    blocks = [block.strip() for block in content.split("\n") if block.strip()]
    for index, block in enumerate(blocks, start=1):
        items.append(
            {
                "id": f"rule-item-{index}",
                "title": block[:24] if len(block) > 24 else block,
                "body": block,
            }
        )
    return items


def build_active_rule_text(rule_sets: list[dict]) -> str:
    lines = []
    for builtin in DEFAULT_RULES:
        lines.append(f"- {builtin['title']}：{builtin['body']}")
    for rule_set in rule_sets:
        if not rule_set.get("enabled", True):
            continue
        for item in rule_set.get("items", []):
            lines.append(f"- {rule_set['name']} / {item['title']}：{item['body']}")
    return "\n".join(lines)
