import json
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.common.exceptions import AppError


@dataclass(frozen=True)
class Provider:
    protocol: str
    base_url: str
    model_name: str
    api_key: str
    context_tokens: int
    max_output_tokens: int
    temperature: float | None
    timeout: int
    token_parameter: str = "max_tokens"
    supports_json_mode: bool = False

    async def stream(
        self, messages: list[dict[str, Any]], *, structured: bool = False
    ) -> AsyncIterator[str]:
        # 文本按字符保守估算；附件由业务层另外预留预算。
        text_tokens = 0
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                text_tokens += estimate_text_tokens(content)
            else:
                for part in content:
                    if part["type"] == "text":
                        text_tokens += estimate_text_tokens(part["text"])
                    elif part["type"] == "image_url":
                        text_tokens += 4096
                    elif part["type"] == "file":
                        text_tokens += math.ceil(len(part["file"]["file_data"]) / 6)
        if text_tokens >= self.context_tokens - self.max_output_tokens:
            raise AppError("context_exceeded", "上下文过长，请减少记忆轮数或附件，或切换模型")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {"model": self.model_name, "stream": True}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.protocol == "responses":
            payload.update(
                input=self._responses_input(messages),
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
            if structured:
                payload["text"] = {"format": {"type": "json_object"}}
            path = "/responses"
        else:
            payload.update(messages=messages)
            payload[self.token_parameter] = self.max_output_tokens
            if structured:
                payload["response_format"] = {"type": "json_object"}
            path = "/chat/completions"
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10), follow_redirects=False
            ) as client:
                async with client.stream(
                    "POST", self.base_url + path, json=payload, headers=headers
                ) as response:
                    if response.status_code >= 300:
                        raise AppError(
                            "provider_error", "模型请求失败，请检查模型配置或稍后重试", 502
                        )
                    data_lines: list[str] = []
                    frame_size = 0
                    completed = False
                    async for line in response.aiter_lines():
                        if not line:
                            if not data_lines:
                                continue
                            event_data = "\n".join(data_lines)
                            data_lines, frame_size = [], 0
                            if event_data == "[DONE]":
                                completed = True
                                break
                            item = json.loads(event_data)
                            if not isinstance(item, dict):
                                raise ValueError
                            if item.get("error") or item.get("type") in {
                                "error",
                                "response.failed",
                                "response.incomplete",
                            }:
                                raise AppError(
                                    "provider_error", "模型未能完成回答，请稍后重试", 502
                                )
                            if self.protocol == "responses":
                                if item.get("type") == "response.output_text.delta":
                                    delta = item.get("delta")
                                    if isinstance(delta, str):
                                        yield delta
                                if item.get("type") == "response.completed":
                                    completed = True
                                    break
                            else:
                                for choice in item.get("choices", []):
                                    if choice.get("finish_reason") in {
                                        "length",
                                        "content_filter",
                                        "tool_calls",
                                    }:
                                        raise AppError(
                                            "incomplete_answer",
                                            "模型回答未完成，请调整模型输出上限或重新提问",
                                            502,
                                        )
                                    content = choice.get("delta", {}).get("content")
                                    if isinstance(content, str):
                                        yield content
                            continue
                        if line.startswith("data:"):
                            frame_size += len(line)
                            if frame_size > 1_000_000:
                                raise ValueError
                            data_lines.append(line[5:].lstrip())
                    if not completed:
                        raise AppError("stream_interrupted", "模型连接中断，请重新发送", 502)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            raise AppError(
                "provider_unavailable", "模型连接异常，请检查配置或稍后重试", 502
            ) from exc

    async def json_result(self, messages: list[dict[str, Any]]) -> object:
        content = ""
        async for delta in self.stream(messages, structured=self.supports_json_mode):
            content += delta
            if len(content) > 50000:
                raise AppError("invalid_memory", "记忆摘要生成失败，请调整模型配置", 502)
        try:
            content = content.strip()
            if content.startswith("```json\n") and content.endswith("```"):
                content = content[8:-3].strip()
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise AppError("invalid_memory", "记忆摘要生成失败，请调整模型配置", 502) from exc

    @staticmethod
    def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for message in messages:
            content = message["content"]
            if isinstance(content, str):
                converted.append(message)
                continue
            parts = []
            for part in content:
                if part["type"] == "text":
                    parts.append({"type": "input_text", "text": part["text"]})
                elif part["type"] == "image_url":
                    parts.append({"type": "input_image", "image_url": part["image_url"]["url"]})
                elif part["type"] == "file":
                    parts.append({"type": "input_file", **part["file"]})
            converted.append({"role": message["role"], "content": parts})
        return converted


def estimate_text_tokens(text: str) -> int:
    # 中文等非 ASCII 字符按一个 token、ASCII 按每三字符估算；非精确计数。
    return sum(1 for char in text if not char.isascii()) + math.ceil(
        sum(1 for char in text if char.isascii()) / 3
    )
