import json
import logging
import math
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

import httpx

from app.common.exceptions import AppError

logger = logging.getLogger(__name__)


def diagnostic_identifier(value: object, api_key: str) -> str | None:
    # 只允许短标识进入日志，不记录供应商原文、凭据或咨询内容。
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value)
        or value.startswith("sk-")
        or (api_key and api_key in value)
    ):
        return None
    return value


@dataclass(frozen=True)
class StreamPart:
    kind: Literal["text", "reasoning"]
    text: str


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
        async for part in self.stream_parts(messages, structured=structured):
            if part.kind == "text":
                yield part.text

    async def stream_parts(
        self, messages: list[dict[str, Any]], *, structured: bool = False
    ) -> AsyncIterator[StreamPart]:
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
        started = perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10), follow_redirects=False
            ) as client:
                async with client.stream(
                    "POST", self.base_url + path, json=payload, headers=headers
                ) as response:
                    if response.status_code >= 300:
                        raise await self._http_error(response)
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
                                raise self._stream_error(response, item, started=started)
                            if self.protocol == "responses":
                                if item.get("type") == "response.output_text.delta":
                                    delta = item.get("delta")
                                    if isinstance(delta, str):
                                        yield StreamPart("text", delta)
                                elif item.get("type") in {
                                    "response.reasoning_text.delta",
                                    "response.reasoning_summary_text.delta",
                                }:
                                    delta = item.get("delta")
                                    if isinstance(delta, str):
                                        yield StreamPart("reasoning", delta)
                                if item.get("type") == "response.completed":
                                    completed = True
                                    break
                            else:
                                for choice in item.get("choices", []):
                                    if choice.get("finish_reason") in {
                                        "length",
                                        "content_filter",
                                        "tool_calls",
                                        "function_call",
                                    }:
                                        raise self._stream_error(
                                            response,
                                            item,
                                            started=started,
                                            finish_reason=choice["finish_reason"],
                                        )
                                    part = choice.get("delta", {})
                                    reasoning = part.get("reasoning_content")
                                    if isinstance(reasoning, str):
                                        yield StreamPart("reasoning", reasoning)
                                    content = part.get("content")
                                    if isinstance(content, str):
                                        yield StreamPart("text", content)
                            continue
                        if line.startswith("data:"):
                            frame_size += len(line)
                            if frame_size > 1_000_000:
                                raise ValueError
                            data_lines.append(line[5:].lstrip())
                    if not completed:
                        raise AppError("stream_interrupted", "模型连接中断，请重新发送", 502)
        except httpx.TimeoutException as exc:
            logger.warning(
                "模型连接超时 protocol=%s duration_ms=%.1f type=%s",
                self.protocol,
                (perf_counter() - started) * 1000,
                type(exc).__name__,
            )
            raise AppError("provider_timeout", "模型响应超时，请稍后重试或切换模型", 504) from exc
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

    def _stream_error(
        self,
        response: httpx.Response,
        item: dict[str, Any],
        *,
        started: float,
        finish_reason: str | None = None,
    ) -> AppError:
        # Responses 的失败原因和用量在 response 内，不能只检查顶层 error。
        result = item.get("response")
        result = result if isinstance(result, dict) else item
        error = result.get("error")
        error = error if isinstance(error, dict) else {}
        incomplete = result.get("incomplete_details")
        incomplete = incomplete if isinstance(incomplete, dict) else {}
        reason = diagnostic_identifier(finish_reason or incomplete.get("reason"), self.api_key)
        code = diagnostic_identifier(error.get("code") or item.get("code"), self.api_key)
        request_id = next(
            (
                identifier
                for value in (
                    response.headers.get("x-request-id"),
                    response.headers.get("x-acs-request-id"),
                    response.headers.get("request-id"),
                    item.get("request_id"),
                    result.get("request_id"),
                    result.get("id"),
                )
                if (identifier := diagnostic_identifier(value, self.api_key))
            ),
            None,
        )
        usage = result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        output_details = usage.get("output_tokens_details") or usage.get(
            "completion_tokens_details"
        )
        output_details = output_details if isinstance(output_details, dict) else {}

        def count(value: object) -> int | None:
            return value if type(value) is int and value >= 0 else None

        logger.warning(
            "模型流未完成 protocol=%s event=%s reason=%s provider_code=%s "
            "provider_request_id=%s duration_ms=%.1f max_output_tokens=%d "
            "output_tokens=%s reasoning_tokens=%s",
            self.protocol,
            diagnostic_identifier(item.get("type") or item.get("object"), self.api_key)
            or "unknown",
            reason or "unknown",
            code or "unknown",
            request_id or "unknown",
            (perf_counter() - started) * 1000,
            self.max_output_tokens,
            count(usage.get("output_tokens", usage.get("completion_tokens"))),
            count(output_details.get("reasoning_tokens")),
        )
        if reason in {"max_output_tokens", "length"}:
            return AppError(
                "output_limit_exceeded",
                "模型输出达到上限，请在模型配置中提高最大输出 Token 后重试",
                502,
            )
        if reason == "content_filter" or code in {"content_filter", "content_policy_violation"}:
            return AppError(
                "content_filtered", "模型服务因内容限制未能完成回答，请调整问题或切换模型", 502
            )
        if code == "context_length_exceeded":
            return AppError(
                "context_exceeded", "模型上下文超限，请减少附件或会话内容，或切换模型", 502
            )
        if code in {"rate_limit_exceeded", "too_many_requests"}:
            return AppError("provider_rate_limited", "模型服务繁忙，请稍后重试", 502)
        if code in {"timeout", "request_timeout"}:
            return AppError("provider_timeout", "模型响应超时，请稍后重试或切换模型", 504)
        if reason in {"tool_calls", "function_call"}:
            return AppError(
                "unsupported_tool_call", "模型返回了当前咨询不支持的工具调用，请切换模型", 502
            )
        return AppError("provider_error", "模型服务未完成回答，请稍后重试或切换模型", 502)

    async def _http_error(self, response: httpx.Response) -> AppError:
        details: dict[str, Any] = {}
        body = bytearray()
        try:
            async for chunk in response.aiter_bytes(chunk_size=1024):
                if len(body) + len(chunk) > 16_384:
                    break
                body.extend(chunk)
            else:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    details = parsed
        except (httpx.HTTPError, ValueError, RecursionError):
            # 非 JSON、过大或读取失败的错误响应仍保留 HTTP 状态和响应头中的请求 ID。
            pass
        error = details.get("error")
        code = diagnostic_identifier(
            error.get("code") if isinstance(error, dict) else details.get("code"), self.api_key
        )
        request_id = next(
            (
                identifier
                for value in (
                    response.headers.get("x-request-id"),
                    response.headers.get("x-acs-request-id"),
                    response.headers.get("request-id"),
                    details.get("request_id"),
                )
                if (identifier := diagnostic_identifier(value, self.api_key))
            ),
            None,
        )
        logger.warning(
            "模型请求被拒绝 status=%d protocol=%s provider_code=%s provider_request_id=%s",
            response.status_code,
            self.protocol,
            code or "unknown",
            request_id or "unknown",
        )
        if response.status_code == 401:
            return AppError(
                "provider_authentication_failed", "模型认证失败，请检查 API Key 配置", 502
            )
        if response.status_code == 403:
            return AppError(
                "provider_access_denied",
                "模型服务拒绝访问，请检查模型授权、工作空间及可用额度",
                502,
            )
        return AppError("provider_error", "模型请求失败，请检查模型配置或稍后重试", 502)

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
