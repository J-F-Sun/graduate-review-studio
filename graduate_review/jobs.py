from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .llm import LLMRequestError
from .parsers import parse_docx, parse_pdf
from .review import generate_review
from .storage import Storage
from .utils import now_iso


class JobManager:
    def __init__(self, storage: Storage, app_root: Path) -> None:
        self.storage = storage
        self.app_root = app_root
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self.logger = logging.getLogger("uvicorn.error")

    def enqueue_parse(self, paper_id: str) -> None:
        self.logger.info("enqueue parse job paper_id=%s", paper_id)
        self._tasks[f"parse:{paper_id}"] = asyncio.create_task(self._run_parse(paper_id))

    def enqueue_review(
        self,
        paper_id: str,
        *,
        review_mode: str | None = None,
        rule_ids: list[str] | None = None,
        builtin_rule_ids: list[str] | None = None,
    ) -> None:
        self.logger.info(
            "enqueue review job paper_id=%s review_mode=%s rule_count=%s builtin_rule_count=%s",
            paper_id,
            review_mode,
            len(rule_ids or []),
            len(builtin_rule_ids or []),
        )
        self._tasks[f"review:{paper_id}"] = asyncio.create_task(
            self._run_review(
                paper_id,
                review_mode=review_mode,
                rule_ids=rule_ids or [],
                builtin_rule_ids=builtin_rule_ids,
            )
        )

    def cancel_tasks_for_paper(self, paper_id: str) -> None:
        for prefix in ("parse", "review"):
            task_key = f"{prefix}:{paper_id}"
            task = self._tasks.pop(task_key, None)
            if task and not task.done():
                task.cancel()
                self.logger.info("cancelled %s job for paper_id=%s", prefix, paper_id)

    def cancel_all_tasks(self) -> None:
        for task_key, task in list(self._tasks.items()):
            if task and not task.done():
                task.cancel()
                self.logger.info("cancelled job task_key=%s", task_key)
        self._tasks.clear()

    def _progress_callback(self, paper_id: str, phase: str):
        def callback(message: str) -> None:
            self.storage.update_paper_metadata(paper_id, status_message=message)
            self.logger.info("%s progress paper_id=%s step=%s", phase, paper_id, message)

        return callback

    async def _run_parse(self, paper_id: str) -> None:
        self.logger.info("parse started paper_id=%s", paper_id)
        metadata = self.storage.update_paper_metadata(
            paper_id,
            parse_status="running",
            status_message="正在解析论文结构、表格和图片",
            last_error="",
            last_warning="",
        )
        self.storage.reset_paper_outputs(paper_id)
        source_path = self.storage.get_source_path(paper_id)
        suffix = source_path.suffix.lower()
        try:
            self.storage.update_paper_metadata(paper_id, status_message=f"正在读取{suffix}论文文件")
            if suffix == ".docx":
                parsed = await asyncio.to_thread(parse_docx, source_path, storage=self.storage, paper_id=paper_id)
            elif suffix == ".pdf":
                parsed = await asyncio.to_thread(parse_pdf, source_path, storage=self.storage, paper_id=paper_id)
            else:
                raise ValueError(f"暂不支持的论文格式：{suffix}")
            self.storage.write_parsed(paper_id, parsed)
            self.storage.update_paper_metadata(
                paper_id,
                parse_status="done",
                review_status="idle",
                status_message="解析完成，可以开始审稿",
                page_count=parsed.get("page_count"),
                source_type=parsed.get("source_type", suffix.lstrip(".")),
                last_warning="",
            )
            self.logger.info(
                "parse finished paper_id=%s sections=%s paragraphs=%s tables=%s images=%s",
                paper_id,
                parsed.get("stats", {}).get("section_count"),
                parsed.get("stats", {}).get("paragraph_count"),
                parsed.get("stats", {}).get("table_count"),
                parsed.get("stats", {}).get("image_count"),
            )
        except asyncio.CancelledError:
            self.logger.warning("parse cancelled paper_id=%s", paper_id)
            raise
        except Exception as exc:
            self.logger.exception("parse failed paper_id=%s error=%s", paper_id, exc)
            self.storage.update_paper_metadata(
                paper_id,
                parse_status="failed",
                status_message="解析失败",
                last_error=str(exc),
                last_warning="",
            )
        finally:
            self._tasks.pop(f"parse:{paper_id}", None)

    async def _run_review(
        self,
        paper_id: str,
        *,
        review_mode: str | None,
        rule_ids: list[str],
        builtin_rule_ids: list[str] | None,
    ) -> None:
        self.logger.info("review started paper_id=%s requested_mode=%s", paper_id, review_mode)
        metadata = self.storage.read_paper_metadata(paper_id)
        if review_mode and review_mode != metadata.get("review_mode"):
            metadata = self.storage.update_paper_metadata(paper_id, review_mode=review_mode)
        if metadata.get("parse_status") != "done":
            self.logger.warning("review skipped paper_id=%s parse_status=%s", paper_id, metadata.get("parse_status"))
            return
        self.storage.update_paper_metadata(
            paper_id,
            review_status="running",
            status_message="正在准备模型审稿任务",
            last_error="",
            last_warning="",
        )
        parsed = self.storage.read_parsed(paper_id)
        settings = self.storage.read_settings()
        rules = [
            self.storage.read_rule(rule_id)
            for rule_id in rule_ids
            if self.storage.read_rule(rule_id)
        ]
        rules = [rule for rule in rules if rule]
        try:
            review, updated_parsed = await generate_review(
                metadata,
                parsed,
                rules,
                settings,
                builtin_rule_ids=builtin_rule_ids,
                data_root=self.storage.data_dir,
                progress_callback=self._progress_callback(paper_id, "review"),
            )
            self.storage.write_parsed(paper_id, updated_parsed)
            self.storage.write_review(paper_id, review)
            self.storage.update_paper_metadata(
                paper_id,
                review_status="done",
                status_message="审稿完成，已使用模型生成报告",
                last_review_at=review.get("generated_at"),
                last_error="",
                last_warning="",
            )
            self.logger.info(
                "review finished paper_id=%s provider=%s issues=%s total_score=%s",
                paper_id,
                review.get("provider"),
                len(review.get("issues", [])),
                review.get("total_score"),
            )
        except asyncio.CancelledError:
            self.logger.warning("review cancelled paper_id=%s", paper_id)
            raise
        except Exception as exc:
            provider = settings.get("llm", {}).get("provider", "openai-compatible")
            failure_review = {
                "generated_at": now_iso(),
                "mode": metadata.get("review_mode", "快速审稿"),
                "provider": provider,
                "generation_mode": "failed",
                "generation_notes": [f"模型审稿失败：{exc}"],
                "error_message": str(exc),
                "summary": "",
                "general_assessment": "",
                "dimension_scores": [],
                "total_score": None,
                "pass": False,
                "chapter_reviews": [],
                "issues": [],
                "rule_hits": [],
                "innovation": None,
            }
            self.storage.write_review(paper_id, failure_review)
            self.storage.update_paper_metadata(
                paper_id,
                review_status="failed",
                status_message="模型审稿失败",
                last_error=str(exc),
                last_warning="",
            )
            self.logger.exception("review failed paper_id=%s provider=%s error=%s", paper_id, provider, exc)
        finally:
            self._tasks.pop(f"review:{paper_id}", None)
