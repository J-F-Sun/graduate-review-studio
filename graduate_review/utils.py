from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(value: str) -> str:
    compact = re.sub(r"\s+", "-", value.strip().lower())
    compact = re.sub(r"[^a-z0-9\-_]+", "", compact)
    return compact or uuid.uuid4().hex[:8]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？；!?;])", text)
    return [part.strip() for part in parts if part.strip()]


def truncate(value: str, limit: int = 240) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    return f"{value[: limit - 1]}…"


def pick(iterable: Iterable[Any], default: Any = None) -> Any:
    for item in iterable:
        return item
    return default
