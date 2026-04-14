from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .llm import LLMClient, LLMRequestError, provider_display_name
from .parsers.common import is_acknowledgement_title
from .rules import build_active_rule_text
from .utils import clean_text, new_id, now_iso, truncate


DIMENSIONS = [
    "论文概括",
    "章节设置",
    "论述逻辑",
    "标题匹配",
    "实验与测试",
    "工作量",
    "语言表达",
]

ProgressCallback = Callable[[str], None]
logger = logging.getLogger("uvicorn.error")

CHAPTER_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "chapter_review",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "section_title": {"type": "string"},
                "assessment": {"type": "string"},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "severity": {"type": "string", "enum": ["严重", "重要", "一般"]},
                            "type": {"type": "string"},
                            "location_label": {"type": "string"},
                            "paragraph_ids": {"type": "array", "items": {"type": "string"}},
                            "table_ids": {"type": "array", "items": {"type": "string"}},
                            "image_ids": {"type": "array", "items": {"type": "string"}},
                            "evidence": {"type": "string"},
                            "analysis": {"type": "string"},
                            "suggestion": {"type": "string"},
                            "polish_suggestion": {"type": "string"},
                        },
                        "required": [
                            "title",
                            "severity",
                            "type",
                            "location_label",
                            "paragraph_ids",
                            "table_ids",
                            "image_ids",
                            "evidence",
                            "analysis",
                            "suggestion",
                            "polish_suggestion",
                        ],
                    },
                },
            },
            "required": ["section_title", "assessment", "issues"],
        },
    },
}

FINAL_REVIEW_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "final_review",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "general_assessment": {"type": "string"},
                "dimension_scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string"},
                            "score": {"type": "number"},
                        },
                        "required": ["name", "score"],
                    },
                },
                "total_score": {"type": "number"},
                "pass": {"type": "boolean"},
                "rule_hits": {"type": "array", "items": {"type": "string"}},
                "innovation": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "points": {"type": "array", "items": {"type": "string"}},
                        "assessment": {"type": "string"},
                    },
                    "required": ["points", "assessment"],
                },
            },
            "required": [
                "summary",
                "general_assessment",
                "dimension_scores",
                "total_score",
                "pass",
                "rule_hits",
                "innovation",
            ],
        },
    },
}


def _severity_rank(value: str) -> int:
    return {"严重": 0, "重要": 1, "一般": 2}.get(value, 99)


def _compact_issue_for_aggregation(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": issue.get("title", ""),
        "severity": issue.get("severity", "一般"),
        "type": issue.get("type", ""),
        "location_label": issue.get("location_label", ""),
        "evidence": truncate(issue.get("evidence", ""), 120),
        "analysis": truncate(issue.get("analysis", ""), 160),
        "suggestion": truncate(issue.get("suggestion", ""), 120),
    }


def _chapter_outputs_to_review_payload(chapter_outputs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chapter_reviews: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for item in chapter_outputs:
        section_id = item.get("section_id", "")
        chapter_reviews.append(
            {
                "section_id": section_id,
                "title": item.get("section_title", ""),
                "assessment": item.get("assessment", ""),
            }
        )
        for issue in item.get("issues", []):
            issues.append(
                {
                    "title": issue.get("title", ""),
                    "severity": issue.get("severity", "一般"),
                    "type": issue.get("type", ""),
                    "location_label": issue.get("location_label", ""),
                    "evidence": issue.get("evidence", ""),
                    "analysis": issue.get("analysis", ""),
                    "suggestion": issue.get("suggestion", ""),
                    "polish_suggestion": issue.get("polish_suggestion", ""),
                    "target_ids": {
                        "paragraph_ids": issue.get("paragraph_ids", []),
                        "section_ids": [section_id] if section_id else [],
                        "table_ids": issue.get("table_ids", []),
                        "image_ids": issue.get("image_ids", []),
                    },
                }
            )
    return chapter_reviews, issues


def _build_final_aggregation_payload(
    chapter_outputs: list[dict[str, Any]],
    *,
    degree_type: str,
    mode: str,
) -> list[dict[str, Any]]:
    compact_sections = []
    all_issue_count = 0
    severity_counter = {"严重": 0, "重要": 0, "一般": 0}
    type_counter: dict[str, int] = {}

    for item in chapter_outputs:
        issues = sorted(item.get("issues", []), key=lambda x: (_severity_rank(x.get("severity", "一般")), x.get("title", "")))
        all_issue_count += len(issues)
        for issue in issues:
            severity = issue.get("severity", "一般")
            severity_counter[severity] = severity_counter.get(severity, 0) + 1
            issue_type = issue.get("type", "") or "综合问题"
            type_counter[issue_type] = type_counter.get(issue_type, 0) + 1
        compact_sections.append(
            {
                "section_id": item.get("section_id", ""),
                "section_title": item.get("section_title", ""),
                "assessment": truncate(item.get("assessment", ""), 260),
                "issue_count": len(issues),
                "top_issues": [_compact_issue_for_aggregation(issue) for issue in issues[:3]],
            }
        )

    top_issue_types = sorted(type_counter.items(), key=lambda pair: (-pair[1], pair[0]))[:8]
    return [
        {
            "degree_type": degree_type,
            "review_mode": mode,
            "chapter_count": len(chapter_outputs),
            "issue_count": all_issue_count,
            "severity_counts": severity_counter,
            "top_issue_types": [{"type": name, "count": count} for name, count in top_issue_types],
        },
        {"sections": compact_sections},
    ]


def _notify_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback:
        callback(message)


def _chunk_sections(parsed: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    section_map = {section["id"]: section for section in parsed.get("sections", [])}
    paragraphs_by_section: dict[str, list[dict[str, Any]]] = {}
    for paragraph in parsed.get("paragraphs", []):
        paragraphs_by_section.setdefault(paragraph["section_id"], []).append(paragraph)
    tables_by_section: dict[str, list[dict[str, Any]]] = {}
    for table in parsed.get("tables", []):
        tables_by_section.setdefault(table["section_id"], []).append(table)
    images_by_section: dict[str, list[dict[str, Any]]] = {}
    for image in parsed.get("images", []):
        images_by_section.setdefault(image["section_id"], []).append(image)

    top_sections = [
        section
        for section in parsed.get("sections", [])
        if section.get("level") == 1 and not is_acknowledgement_title(section.get("title", ""))
    ]
    if not top_sections:
        top_sections = [
            section for section in parsed.get("sections", []) if not is_acknowledgement_title(section.get("title", ""))
        ]

    chunks: list[dict[str, Any]] = []
    paragraph_limit = 12 if mode == "快速审稿" else 24
    for section in top_sections:
        section_id = section["id"]
        child_ids = [child["id"] for child in parsed.get("sections", []) if child.get("parent_id") == section_id]
        relevant_section_ids = [section_id] + child_ids
        paragraphs = [
            paragraph
            for sec_id in relevant_section_ids
            for paragraph in paragraphs_by_section.get(sec_id, [])
        ][:paragraph_limit]
        tables = [
            table for sec_id in relevant_section_ids for table in tables_by_section.get(sec_id, [])
        ][:6]
        images = [
            image for sec_id in relevant_section_ids for image in images_by_section.get(sec_id, [])
        ][:6]
        chunks.append(
            {
                "section": section,
                "paragraphs": paragraphs,
                "tables": tables,
                "images": images,
            }
        )
    return chunks


async def _analyze_images_with_model(
    parsed: dict[str, Any],
    *,
    llm_client: LLMClient,
    data_root: Path,
    limit: int,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    updated = False
    warnings: list[str] = parsed.setdefault("image_analysis_warnings", [])
    images = parsed.get("images", [])[:limit]
    if not images:
        return parsed
    if not llm_client.settings.get("vision_model"):
        warnings.append("当前未配置视觉模型，已跳过图片理解，审稿将仅基于正文、表格与已有图片说明。")
        logger.info("image analysis skipped reason=no-vision-model image_count=%s", len(images))
        for image in images:
            image["analysis_status"] = image.get("analysis_status") or "vision-skipped"
            image["content_summary"] = image.get("content_summary") or "未配置视觉模型，已跳过图片理解。"
        return parsed
    if images:
        _notify_progress(progress_callback, f"正在解析图片内容（0/{len(images)}）")
    for index, image in enumerate(images, start=1):
        if image.get("analysis_status") == "vision-done":
            continue
        image_path = data_root / image["asset_relative_path"]
        prompt = (
            "请阅读这张毕业论文中的图片，只输出一小段中文总结，内容包括：图片类型、关键元素、变量关系、实验趋势"
            "或界面模块。不要臆造数值。图题为："
            f"{image.get('caption', '未命名图片')}；邻近正文为：{image.get('nearby_text', '')}"
        )
        try:
            image["content_summary"] = clean_text(await llm_client.analyze_image(image_path, prompt))
            image["analysis_status"] = "vision-done"
            updated = True
            logger.info(
                "image analysis result paper_image=%s caption=%s summary=%s",
                image.get("id"),
                image.get("caption"),
                truncate(image["content_summary"], 500),
            )
            logger.info(
                "===== 图片解析结果开始 image=%s =====\n%s\n===== 图片解析结果结束 image=%s =====",
                image.get("id"),
                truncate(image["content_summary"], 1000),
                image.get("id"),
            )
        except Exception as exc:
            image["analysis_status"] = "vision-failed"
            image["content_summary"] = image.get("content_summary") or f"图片视觉解析未完成：{truncate(str(exc), 120)}"
            warnings.append(f"{image.get('caption') or image.get('id')}：{truncate(str(exc), 140)}")
            logger.warning(
                "image analysis failed image=%s caption=%s error=%s",
                image.get("id"),
                image.get("caption"),
                exc,
            )
            logger.info(
                "===== 图片解析失败 image=%s =====\n%s\n===== 图片解析失败结束 image=%s =====",
                image.get("id"),
                truncate(str(exc), 1000),
                image.get("id"),
            )
            if isinstance(exc, LLMRequestError) and exc.stage in {
                "network",
                "http",
                "configuration",
                "response-format",
                "json-parse",
            }:
                raise LLMRequestError(
                    f"图片“{image.get('caption') or image.get('id')}”解析失败：{exc}",
                    stage=f"vision-{exc.stage}",
                ) from exc
        _notify_progress(progress_callback, f"正在解析图片内容（{index}/{len(images)}）")
    if updated:
        parsed["stats"]["image_count"] = len(parsed.get("images", []))
    return parsed


async def _model_review(
    metadata: dict[str, Any],
    parsed: dict[str, Any],
    rules: list[dict[str, Any]],
    settings: dict[str, Any],
    *,
    builtin_rule_ids: list[str] | None = None,
    data_root: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    llm_client = LLMClient(settings["llm"])
    image_limit = int(settings["llm"].get("image_analysis_limit", 8))
    _notify_progress(progress_callback, "正在准备模型审稿输入")
    parsed = await _analyze_images_with_model(
        parsed,
        llm_client=llm_client,
        data_root=data_root,
        limit=image_limit,
        progress_callback=progress_callback,
    )
    chunks = _chunk_sections(parsed, metadata.get("review_mode", "快速审稿"))
    _notify_progress(progress_callback, f"正在分章节审稿（共 {len(chunks)} 个章节块）")
    chapter_outputs = []
    rule_text = build_active_rule_text(rules, builtin_rule_ids=builtin_rule_ids)

    for index, chunk in enumerate(chunks, start=1):
        section = chunk["section"]
        _notify_progress(progress_callback, f"正在审稿章节 {index}/{len(chunks)}：{section['title']}")
        section_payload = {
            "section": section["title"],
            "subsections": [
                s["title"]
                for s in parsed.get("sections", [])
                if s.get("parent_id") == section["id"]
            ],
            "paragraphs": [
                {
                    "id": paragraph["id"],
                    "location": paragraph["location_label"],
                    "text": truncate(paragraph["text"], 420 if metadata.get("review_mode") == "快速审稿" else 760),
                }
                for paragraph in chunk["paragraphs"]
            ],
            "tables": [
                {
                    "id": table["id"],
                    "location": table["location_label"],
                    "caption": table["caption"],
                    "preview": table["preview"],
                }
                for table in chunk["tables"]
            ],
            "images": [
                {
                    "id": image["id"],
                    "location": image["location_label"],
                    "caption": image["caption"],
                    "content_summary": image["content_summary"],
                }
                for image in chunk["images"]
            ],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是严格的中国本科/硕士毕业论文审稿助手。请根据提供的章节材料进行审查，必须指出明确问题位置。"
                    "只输出 JSON，不要输出额外解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请审查以下论文章节。审稿模式："
                    f"{metadata.get('review_mode', '快速审稿')}；论文类型：{metadata.get('degree_type')}。\n"
                    "需要重点依据这些规则：\n"
                    f"{rule_text}\n\n"
                    "请返回 JSON，结构为："
                    '{"section_title":"","assessment":"","issues":[{"title":"","severity":"严重|重要|一般","type":"","location_label":"","paragraph_ids":[],"table_ids":[],"image_ids":[],"evidence":"","analysis":"","suggestion":"","polish_suggestion":""}]}'
                    "\n\n章节材料如下：\n"
                    f"{section_payload}"
                ),
            },
        ]
        try:
            chapter_result = await llm_client.chat_json(
                messages,
                response_format=CHAPTER_REVIEW_RESPONSE_FORMAT,
            )
            chapter_result["section_id"] = section["id"]
            chapter_outputs.append(chapter_result)
            logger.info(
                "chapter review result section=%s issue_count=%s assessment=%s",
                section["title"],
                len(chapter_result.get("issues", [])),
                truncate(chapter_result.get("assessment", ""), 500),
            )
            logger.info(
                "===== 章节审稿结果开始 section=%s =====\n%s\n===== 章节审稿结果结束 section=%s =====",
                section["title"],
                truncate(str(chapter_result), 2000),
                section["title"],
            )
        except Exception as exc:
            raise LLMRequestError(
                f"章节“{section['title']}”审稿失败：{exc}",
                stage="chapter-review",
            ) from exc

    chapter_reviews, flattened_issues = _chapter_outputs_to_review_payload(chapter_outputs)
    aggregate_payload = _build_final_aggregation_payload(
        chapter_outputs,
        degree_type=metadata.get("degree_type", ""),
        mode=metadata.get("review_mode", "快速审稿"),
    )
    logger.info(
        "final aggregation payload chapter_count=%s issue_count=%s payload_chars=%s",
        len(chapter_outputs),
        len(flattened_issues),
        len(str(aggregate_payload)),
    )
    aggregate_messages = [
        {
            "role": "system",
            "content": (
                "你是论文终审助手。请基于分章审稿摘要输出总评 JSON，只负责生成摘要、总评、分项评分、总分、是否通过、规则命中概述和硕士创新点评价。"
                "只输出 JSON。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请综合以下分章审稿摘要并生成最终总评。\n"
                "分值范围固定为 0-10，6 分以下不合格。逐章评价和详细问题清单已由系统保存，本次不要重复生成它们。"
                "请重点给出：论文内容概括、整体评价、各维度分数、总分、是否通过、用户规则命中概述、硕士论文创新点评价。"
                "返回 JSON 格式："
                '{"summary":"","general_assessment":"","dimension_scores":[{"name":"","score":0}],"total_score":0,"pass":true,"rule_hits":[""],"innovation":{"points":[""],"assessment":""}}'
                f"\n论文类型：{metadata.get('degree_type')}。\n"
                f"分章审稿摘要：{aggregate_payload}"
            ),
        },
    ]
    _notify_progress(progress_callback, "正在汇总章节意见并生成总评")
    try:
        review = await llm_client.chat_json(
            aggregate_messages,
            response_format=FINAL_REVIEW_RESPONSE_FORMAT,
            max_tokens=2048,
            timeout_seconds=180.0,
        )
    except Exception as exc:
        raise LLMRequestError(f"汇总总评失败：{exc}", stage="final-aggregation") from exc
    review["chapter_reviews"] = chapter_reviews
    review["issues"] = flattened_issues
    _notify_progress(progress_callback, "模型审稿完成，正在整理结果")
    logger.info(
        "final review result summary=%s total_score=%s issue_count=%s",
        truncate(review.get("summary", ""), 500),
        review.get("total_score"),
        len(review.get("issues", [])),
    )
    logger.info(
        "===== 总评结果开始 =====\n%s\n===== 总评结果结束 =====",
        truncate(str(review), 3000),
    )
    review["generated_at"] = now_iso()
    review["mode"] = metadata.get("review_mode", "快速审稿")
    review["provider"] = llm_client.settings.get("provider", settings["llm"].get("provider", "openai-compatible"))
    review["generation_mode"] = "model"
    generation_notes = [
        f"当前报告已使用 {provider_display_name(llm_client.settings)} 生成，总评与评分由模型汇总，逐章评价与问题清单沿用分章审稿结果。"
    ]
    if any(is_acknowledgement_title(section.get("title", "")) for section in parsed.get("sections", [])):
        generation_notes.append("检测到“致谢”章节，已按规则跳过详细审查，仅保留章节存在信息。")
    review["generation_notes"] = generation_notes
    review["fallback_info"] = None
    review.setdefault("dimension_scores", [])
    review.setdefault("chapter_reviews", [])
    review.setdefault("issues", [])
    if metadata.get("degree_type") != "硕士":
        review["innovation"] = None
    return _normalize_review(review)


def _normalize_review(review: dict[str, Any]) -> dict[str, Any]:
    review["dimension_scores"] = [
        {"name": item.get("name", f"维度{index + 1}"), "score": float(item.get("score", 0))}
        for index, item in enumerate(review.get("dimension_scores", []))
    ]
    if "total_score" in review:
        try:
            review["total_score"] = round(float(review["total_score"]), 1)
        except Exception:
            review["total_score"] = 0.0
    review["chapter_reviews"] = [
        {
            "section_id": item.get("section_id", ""),
            "title": item.get("title", f"章节{index + 1}"),
            "assessment": item.get("assessment", ""),
        }
        for index, item in enumerate(review.get("chapter_reviews", []))
    ]
    normalized_issues = []
    for issue in review.get("issues", []):
        normalized_issues.append(
            {
                "id": issue.get("id") or new_id("issue"),
                "title": issue.get("title", "未命名问题"),
                "severity": issue.get("severity", "一般"),
                "type": issue.get("type", "综合问题"),
                "location_label": issue.get("location_label", ""),
                "evidence": issue.get("evidence", ""),
                "analysis": issue.get("analysis", ""),
                "suggestion": issue.get("suggestion", ""),
                "polish_suggestion": issue.get("polish_suggestion", ""),
                "target_ids": {
                    "paragraph_ids": issue.get("target_ids", {}).get("paragraph_ids", issue.get("paragraph_ids", [])),
                    "section_ids": issue.get("target_ids", {}).get("section_ids", issue.get("section_ids", [])),
                    "table_ids": issue.get("target_ids", {}).get("table_ids", issue.get("table_ids", [])),
                    "image_ids": issue.get("target_ids", {}).get("image_ids", issue.get("image_ids", [])),
                },
            }
        )
    review["issues"] = normalized_issues
    review["rule_hits"] = [item for item in review.get("rule_hits", []) if clean_text(str(item))]
    review["generation_mode"] = review.get("generation_mode", "model")
    review["generation_notes"] = review.get("generation_notes", [])
    review["fallback_info"] = review.get("fallback_info")
    return review


async def generate_review(
    metadata: dict[str, Any],
    parsed: dict[str, Any],
    rules: list[dict[str, Any]],
    settings: dict[str, Any],
    *,
    builtin_rule_ids: list[str] | None = None,
    data_root: Path,
    progress_callback: ProgressCallback | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    llm_client = LLMClient(settings["llm"])
    if not llm_client.configured:
        raise LLMRequestError(
            f"未配置 {provider_display_name(llm_client.settings)} API Key，当前版本禁止回退到本地启发式审稿。",
            stage="configuration",
        )
    review = _normalize_review(
        await _model_review(
            metadata,
            parsed,
            rules,
            settings,
            builtin_rule_ids=builtin_rule_ids,
            data_root=data_root,
            progress_callback=progress_callback,
        )
    )
    return review, parsed
