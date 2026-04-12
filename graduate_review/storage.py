from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

from .utils import ensure_dir, new_id, now_iso, read_json, write_json


DEFAULT_SETTINGS = {
    "llm": {
        "provider": "dashscope-compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "text_model": "qwen-plus",
        "vision_model": "qwen-vl-max",
        "temperature": 0.2,
        "max_tokens": 4096,
        "vision_max_tokens": 1024,
        "image_analysis_limit": 8,
    },
    "export": {
        "include_basic_info": True,
        "include_summary": True,
        "include_dimension_scores": True,
        "include_chapter_reviews": True,
        "include_issue_list": True,
        "include_evidence": True,
        "include_polish_suggestions": True,
        "include_rule_hits": True,
        "include_innovation": True,
    },
}


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.data_dir = ensure_dir(root / "data")
        self.papers_dir = ensure_dir(self.data_dir / "papers")
        self.rules_dir = ensure_dir(self.data_dir / "rules")
        self.exports_dir = ensure_dir(self.data_dir / "exports")
        self.settings_path = self.data_dir / "settings.json"
        self._lock = threading.Lock()
        self.ensure_bootstrap()

    def ensure_bootstrap(self) -> None:
        if not self.settings_path.exists():
            write_json(self.settings_path, DEFAULT_SETTINGS)

    def _paper_dir(self, paper_id: str) -> Path:
        return self.papers_dir / paper_id

    def _paper_meta_path(self, paper_id: str) -> Path:
        return self._paper_dir(paper_id) / "metadata.json"

    def _paper_parsed_path(self, paper_id: str) -> Path:
        return self._paper_dir(paper_id) / "parsed.json"

    def _paper_review_path(self, paper_id: str) -> Path:
        return self._paper_dir(paper_id) / "review.json"

    def _paper_source_dir(self, paper_id: str) -> Path:
        return ensure_dir(self._paper_dir(paper_id) / "source")

    def _paper_assets_dir(self, paper_id: str) -> Path:
        return ensure_dir(self._paper_dir(paper_id) / "assets")

    def create_paper(
        self,
        *,
        title: str,
        degree_type: str,
        review_mode: str,
        original_filename: str,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        with self._lock:
            paper_id = new_id("paper")
            paper_dir = ensure_dir(self._paper_dir(paper_id))
            source_dir = self._paper_source_dir(paper_id)
            stored_filename = original_filename
            source_path = source_dir / stored_filename
            source_path.write_bytes(file_bytes)

            metadata = {
                "id": paper_id,
                "title": title,
                "degree_type": degree_type,
                "review_mode": review_mode,
                "original_filename": original_filename,
                "source_relative_path": str(source_path.relative_to(self.data_dir)),
                "parse_status": "queued",
                "review_status": "idle",
                "status_message": "文件已上传，等待解析",
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "page_count": None,
                "source_type": Path(original_filename).suffix.lstrip(".").lower(),
                "last_error": "",
                "last_warning": "",
                "last_review_at": None,
            }
            write_json(self._paper_meta_path(paper_id), metadata)
            write_json(self._paper_parsed_path(paper_id), {})
            write_json(self._paper_review_path(paper_id), {})
            return metadata

    def list_papers(self) -> list[dict[str, Any]]:
        papers: list[dict[str, Any]] = []
        for meta_path in self.papers_dir.glob("*/metadata.json"):
            papers.append(read_json(meta_path, {}))
        return sorted(papers, key=lambda item: item.get("created_at", ""), reverse=True)

    def read_paper_metadata(self, paper_id: str) -> dict[str, Any]:
        return read_json(self._paper_meta_path(paper_id), {})

    def update_paper_metadata(self, paper_id: str, **updates: Any) -> dict[str, Any]:
        with self._lock:
            metadata = self.read_paper_metadata(paper_id)
            metadata.update(updates)
            metadata["updated_at"] = now_iso()
            write_json(self._paper_meta_path(paper_id), metadata)
            return metadata

    def get_source_path(self, paper_id: str) -> Path:
        metadata = self.read_paper_metadata(paper_id)
        return self.data_dir / metadata["source_relative_path"]

    def write_parsed(self, paper_id: str, parsed: dict[str, Any]) -> None:
        write_json(self._paper_parsed_path(paper_id), parsed)

    def read_parsed(self, paper_id: str) -> dict[str, Any]:
        return read_json(self._paper_parsed_path(paper_id), {})

    def write_review(self, paper_id: str, review: dict[str, Any]) -> None:
        write_json(self._paper_review_path(paper_id), review)

    def read_review(self, paper_id: str) -> dict[str, Any]:
        return read_json(self._paper_review_path(paper_id), {})

    def save_asset(self, paper_id: str, *, category: str, filename: str, data: bytes) -> str:
        asset_dir = ensure_dir(self._paper_assets_dir(paper_id) / category)
        asset_path = asset_dir / filename
        asset_path.write_bytes(data)
        return str(asset_path.relative_to(self.data_dir))

    def reset_paper_outputs(self, paper_id: str) -> None:
        paper_dir = self._paper_dir(paper_id)
        assets_dir = paper_dir / "assets"
        if assets_dir.exists():
            shutil.rmtree(assets_dir)
        write_json(self._paper_parsed_path(paper_id), {})
        write_json(self._paper_review_path(paper_id), {})

    def list_rules(self) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        for rule_path in self.rules_dir.glob("*.json"):
            rules.append(read_json(rule_path, {}))
        return sorted(rules, key=lambda item: item.get("created_at", ""), reverse=True)

    def create_rule(self, *, name: str, source_format: str, content: str) -> dict[str, Any]:
        rule_id = new_id("rule")
        payload = {
            "id": rule_id,
            "name": name,
            "source_format": source_format,
            "content": content,
            "enabled": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "items": [],
        }
        write_json(self.rules_dir / f"{rule_id}.json", payload)
        return payload

    def update_rule(self, rule_id: str, **updates: Any) -> dict[str, Any]:
        rule_path = self.rules_dir / f"{rule_id}.json"
        payload = read_json(rule_path, {})
        payload.update(updates)
        payload["updated_at"] = now_iso()
        write_json(rule_path, payload)
        return payload

    def read_rule(self, rule_id: str) -> dict[str, Any]:
        return read_json(self.rules_dir / f"{rule_id}.json", {})

    def delete_rule(self, rule_id: str) -> bool:
        rule_path = self.rules_dir / f"{rule_id}.json"
        if not rule_path.exists():
            return False
        with self._lock:
            rule_path.unlink(missing_ok=True)
        return True

    def read_settings(self) -> dict[str, Any]:
        settings = read_json(self.settings_path, DEFAULT_SETTINGS)
        merged = DEFAULT_SETTINGS | settings
        merged["llm"] = DEFAULT_SETTINGS["llm"] | settings.get("llm", {})
        merged["export"] = DEFAULT_SETTINGS["export"] | settings.get("export", {})
        return merged

    def write_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        settings = self.read_settings()
        if "llm" in updates:
            settings["llm"] = settings["llm"] | updates["llm"]
        if "export" in updates:
            settings["export"] = settings["export"] | updates["export"]
        write_json(self.settings_path, settings)
        return settings

    def recover_interrupted_jobs(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        for meta_path in self.papers_dir.glob("*/metadata.json"):
            metadata = read_json(meta_path, {})
            changed = False
            review = self.read_review(metadata["id"]) if metadata.get("id") else {}
            if metadata.get("parse_status") in {"queued", "running"}:
                metadata["parse_status"] = "terminated"
                metadata["review_status"] = "idle"
                metadata["status_message"] = "上次解析已中断，请点击重新解析后再继续"
                metadata["last_error"] = ""
                metadata["last_warning"] = "应用重启时检测到解析任务未完成，已标记为中断。"
                changed = True
            elif metadata.get("review_status") in {"queued", "running"}:
                metadata["review_status"] = "terminated"
                metadata["status_message"] = "上次审稿已中断，请点击重新审稿后重新开始"
                metadata["last_error"] = ""
                metadata["last_warning"] = "应用重启时检测到审稿任务未完成，已标记为中断。"
                review = review if isinstance(review, dict) else {}
                review["generated_at"] = now_iso()
                review["mode"] = metadata.get("review_mode", "快速审稿")
                review["provider"] = review.get("provider") or self.read_settings()["llm"].get("provider", "dashscope-compatible")
                review["generation_mode"] = "terminated"
                review["generation_notes"] = ["应用重启时检测到任务中断，当前报告已失效，请手动重新审稿。"]
                review["error_message"] = "应用在审稿过程中重启，任务已中断。请点击“开始审稿”重新生成。"
                review.setdefault("summary", "")
                review.setdefault("general_assessment", "")
                review.setdefault("dimension_scores", [])
                review.setdefault("total_score", None)
                review.setdefault("pass", False)
                review.setdefault("chapter_reviews", [])
                review.setdefault("issues", [])
                review.setdefault("rule_hits", [])
                review.setdefault("innovation", None)
                self.write_review(metadata["id"], review)
                changed = True
            if changed:
                metadata["updated_at"] = now_iso()
                write_json(meta_path, metadata)
                recovered.append(metadata)
        return recovered

    def delete_paper(self, paper_id: str) -> None:
        paper_dir = self._paper_dir(paper_id)
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
        export_path = self.exports_dir / f"{paper_id}.md"
        export_path.unlink(missing_ok=True)
