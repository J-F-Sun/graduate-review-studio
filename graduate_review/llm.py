from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .utils import truncate


class LLMRequestError(RuntimeError):
    def __init__(self, message: str, *, stage: str = "chat") -> None:
        super().__init__(message)
        self.stage = stage


def infer_provider(settings: dict[str, Any]) -> str:
    base_url = str(settings.get("base_url", "")).lower()
    text_model = str(settings.get("text_model", "")).lower()
    vision_model = str(settings.get("vision_model", "")).lower()
    combined = " ".join(part for part in [base_url, text_model, vision_model] if part)
    if "localhost:11434" in combined or "127.0.0.1:11434" in combined or "ollama" in combined:
        return "ollama"
    if "deepseek" in combined:
        return "deepseek"
    if "dashscope" in combined or "qwen" in combined:
        return "dashscope-compatible"
    if "openrouter" in combined:
        return "openrouter"
    if "openai" in combined:
        return "openai-compatible"
    return str(settings.get("provider") or "openai-compatible")


def provider_display_name(settings: dict[str, Any]) -> str:
    provider = infer_provider(settings)
    mapping = {
        "ollama": "Ollama",
        "deepseek": "DeepSeek",
        "dashscope-compatible": "百炼兼容接口",
        "openrouter": "OpenRouter",
        "openai-compatible": "OpenAI 兼容接口",
    }
    return mapping.get(provider, provider or "LLM 接口")


class LLMClient:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings | {"provider": infer_provider(settings)}
        self.logger = logging.getLogger("uvicorn.error")

    @property
    def configured(self) -> bool:
        return bool(self.settings.get("api_key"))

    def _effective_response_format(self, response_format: dict[str, Any] | None) -> dict[str, Any] | None:
        if response_format is None:
            return None
        if self.settings.get("provider") == "deepseek" and response_format.get("type") == "json_schema":
            return {"type": "json_object"}
        return response_format

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        if not self.configured:
            raise LLMRequestError(f"未配置 {provider_display_name(self.settings)} API Key。", stage="configuration")
        target_model = model or self.settings["text_model"]
        effective_response_format = self._effective_response_format(response_format)
        payload = {
            "model": target_model,
            "messages": messages,
            "temperature": self.settings.get("temperature", 0.2),
            "max_tokens": max_tokens if max_tokens is not None else self.settings.get("max_tokens", 4096),
        }
        if effective_response_format is not None:
            payload["response_format"] = effective_response_format
        self.logger.info(
            "llm request start provider=%s model=%s max_tokens=%s message_count=%s structured=%s response_format=%s",
            self.settings.get("provider"),
            target_model,
            payload["max_tokens"],
            len(messages),
            bool(effective_response_format),
            effective_response_format.get("type") if effective_response_format else "text",
        )
        started = time.perf_counter()
        try:
            request_timeout = timeout_seconds or 1200.0
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(request_timeout, read=request_timeout),
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{self.settings['base_url'].rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            elapsed = time.perf_counter() - started
            self.logger.exception(
                "llm request failed model=%s elapsed=%.2fs stage=network error=%s",
                target_model,
                elapsed,
                exc,
            )
            raise LLMRequestError(
                f"调用 {provider_display_name(self.settings)} 失败：{exc.__class__.__name__}: {exc}",
                stage="network",
            ) from exc

        if response.is_error:
            detail = truncate(response.text, 360)
            if (
                self.settings.get("provider") == "deepseek"
                and effective_response_format is not None
                and "response_format type is unavailable now" in response.text
            ):
                self.logger.warning(
                    "llm request retry without response_format provider=%s model=%s status=%s body=%s",
                    self.settings.get("provider"),
                    target_model,
                    response.status_code,
                    detail,
                )
                retry_payload = payload.copy()
                retry_payload.pop("response_format", None)
                try:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(request_timeout, read=request_timeout),
                        trust_env=False,
                    ) as client:
                        response = await client.post(
                            f"{self.settings['base_url'].rstrip('/')}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {self.settings['api_key']}",
                                "Content-Type": "application/json",
                            },
                            json=retry_payload,
                        )
                    detail = truncate(response.text, 360)
                except httpx.HTTPError as exc:
                    raise LLMRequestError(
                        f"调用 {provider_display_name(self.settings)} 失败：{exc.__class__.__name__}: {exc}",
                        stage="network",
                    ) from exc
            elapsed = time.perf_counter() - started
            if response.is_error:
                self.logger.error(
                    "llm request failed model=%s elapsed=%.2fs stage=http status=%s body=%s",
                    target_model,
                    elapsed,
                    response.status_code,
                    detail,
                )
                raise LLMRequestError(
                    f"{provider_display_name(self.settings)} 返回错误（HTTP {response.status_code}）：{detail}",
                    stage="http",
                )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            elapsed = time.perf_counter() - started
            usage = body.get("usage", {})
            self.logger.info(
                "llm request finish model=%s elapsed=%.2fs prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                target_model,
                elapsed,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
            self.logger.info(
                "llm output preview model=%s preview=%s",
                target_model,
                truncate(str(content), 1600),
            )
            self.logger.info(
                "===== LLM输出预览开始 provider=%s model=%s =====\n%s\n===== LLM输出预览结束 provider=%s model=%s =====",
                self.settings["provider"],
                target_model,
                truncate(str(content), 2000),
                self.settings["provider"],
                target_model,
            )
            return content
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.logger.exception(
                "llm request failed model=%s elapsed=%.2fs stage=response-format raw=%s",
                target_model,
                elapsed,
                truncate(response.text, 360),
            )
            raise LLMRequestError(
                f"{provider_display_name(self.settings)} 响应格式异常，未能提取 message.content：{truncate(response.text, 360)}",
                stage="response-format",
            ) from exc

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        content = await self.chat(
            messages,
            model=model,
            max_tokens=max_tokens,
            response_format=response_format,
            timeout_seconds=timeout_seconds,
        )
        try:
            candidate = self._extract_json_object(content)
            return json.loads(candidate)
        except Exception as exc:
            self.logger.exception(
                "llm json parse failed model=%s preview=%s",
                model or self.settings.get("text_model"),
                truncate(content, 500),
            )
            raise LLMRequestError(
                f"{provider_display_name(self.settings)} 返回内容不是合法 JSON：{truncate(content, 360)}",
                stage="json-parse",
            ) from exc

    async def analyze_image(self, image_path: Path, prompt: str) -> str:
        if not self.configured or not self.settings.get("vision_model"):
            raise LLMRequestError("未配置可用的视觉模型，当前将跳过图片理解。", stage="vision-configuration")
        suffix = image_path.suffix.lower().lstrip(".") or "png"
        if suffix not in {"png", "jpg", "jpeg", "webp", "gif"}:
            raise LLMRequestError(f"当前暂不将 {suffix} 格式图片送入视觉模型。", stage="vision-format")
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_url = f"data:image/{suffix};base64,{encoded}"
        messages = [
            {
                "role": "system",
                "content": "你是严谨的毕业论文图像审查助手。请用中文提炼图片自身表达的内容、结构关系和可能承载的结论。",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        vision_max_tokens = self.settings.get("vision_max_tokens", 1024)
        return await self.chat(messages, model=self.settings["vision_model"], max_tokens=vision_max_tokens)

    @staticmethod
    def _extract_json_object(content: str) -> str:
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", content, re.S)
        if fenced:
            return fenced.group(1)
        inline = re.search(r"(\{.*\})", content, re.S)
        if inline:
            return inline.group(1)
        raise ValueError("No JSON object found in model output.")
