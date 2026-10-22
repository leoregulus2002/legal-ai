import asyncio
import logging
import re
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlsplit

import httpx

from app.ai.providers.client import Provider, estimate_text_tokens
from app.ai.providers.diagnostics import (
    log_failure,
    response_diagnostics,
    safe_exception,
    safe_sdk_logging,
    safe_url,
)
from app.ai.tools.types import (
    MAX_ARGUMENT_BYTES,
    MAX_CALLS_PER_ROUND,
    TOOL_NAME,
    ToolDefinition,
    decode_object,
    encode_json,
    json_object,
)
from app.common.exceptions import AppError

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ToolCall:
    identifier: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class AgentTurn:
    text: str
    calls: list[ToolCall]
    continuation: list[dict[str, object]]


def object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("Expected model response list")
    return [json_object(item) for item in value]


def tool_call(value: dict[str, object], *, responses: bool) -> ToolCall:
    identifier = value.get("call_id" if responses else "id")
    function = value if responses else json_object(value.get("function"))
    name, arguments = function.get("name"), function.get("arguments")
    if (
        not isinstance(identifier, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", identifier)
        or not isinstance(name, str)
        or not TOOL_NAME.fullmatch(name)
        or not isinstance(arguments, str)
    ):
        raise ValueError("Invalid model tool call")
    return ToolCall(identifier, name, decode_object(arguments, limit=MAX_ARGUMENT_BYTES))


class AgentProvider:
    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    def initial_history(self, system: str, user: str) -> list[dict[str, object]]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def append_results(
        self,
        history: list[dict[str, object]],
        turn: AgentTurn,
        results: list[str],
    ) -> None:
        if len(turn.calls) != len(results):
            raise ValueError("Tool result count mismatch")
        history.extend(turn.continuation)
        for call, result in zip(turn.calls, results, strict=True):
            if self.provider.protocol == "responses":
                history.append(
                    {"type": "function_call_output", "call_id": call.identifier, "output": result}
                )
            else:
                history.append({"role": "tool", "tool_call_id": call.identifier, "content": result})

    def check_budget(
        self, history: list[dict[str, object]], tools: list[ToolDefinition]
    ) -> dict[str, object]:
        provider = self.provider
        if (
            provider.protocol not in {"chat_completions", "responses"}
            or provider.context_tokens <= provider.max_output_tokens
            or provider.max_output_tokens < 1
            or provider.timeout < 1
            or provider.token_parameter not in {"max_tokens", "max_completion_tokens"}
        ):
            raise AppError("agent_provider_invalid", "分析模型配置不完整，请检查模型配置")
        parsed = urlsplit(provider.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise AppError("agent_provider_invalid", "分析模型地址配置无效")
        payload: dict[str, object] = {"model": provider.model_name, "stream": False}
        if provider.temperature is not None:
            payload["temperature"] = provider.temperature
        if provider.protocol == "responses":
            payload.update(
                input=history,
                max_output_tokens=provider.max_output_tokens,
                store=False,
                include=["reasoning.encrypted_content"],
            )
            if tools:
                payload["tools"] = [
                    {
                        "type": "function",
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                        "strict": False,
                    }
                    for tool in tools
                ]
            if provider.supports_json_mode:
                payload["text"] = {"format": {"type": "json_object"}}
        else:
            payload["messages"] = history
            payload[provider.token_parameter] = provider.max_output_tokens
            if tools:
                payload["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        },
                    }
                    for tool in tools
                ]
            if provider.supports_json_mode:
                payload["response_format"] = {"type": "json_object"}
        # 复用咨询的文本估算并加25%余量，覆盖工具定义、参数、历史和协议开销。
        # UTF-8字节数会把中文文书按约3倍预算拒绝，不能直接视作Token数。
        # 该值仍是估算，供应商真实超限响应继续按业务异常处理。
        serialized = encode_json(payload, limit=32 * 1024 * 1024)
        estimated_tokens = (estimate_text_tokens(serialized) * 5 + 3) // 4 + 512 + len(history) * 32
        if estimated_tokens + provider.max_output_tokens >= provider.context_tokens:
            raise AppError("context_exceeded", "文书或工具结果超过模型上下文，请缩减内容或切换模型")
        return payload

    async def complete(
        self, history: list[dict[str, object]], tools: list[ToolDefinition]
    ) -> AgentTurn:
        payload = self.check_budget(history, tools)
        provider = self.provider
        path = "/responses" if provider.protocol == "responses" else "/chat/completions"
        url = provider.base_url.rstrip("/") + path
        headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"
        response: httpx.Response | None = None
        captured = bytearray()
        complete = False
        started = perf_counter()
        try:
            with safe_sdk_logging():
                async with (
                    asyncio.timeout(provider.timeout),
                    httpx.AsyncClient(
                        timeout=httpx.Timeout(provider.timeout, connect=min(10, provider.timeout)),
                        follow_redirects=False,
                        trust_env=False,
                    ) as client,
                ):
                    async with client.stream(
                        "POST", url, json=payload, headers=headers
                    ) as response:
                        encoding = response.headers.get("content-encoding", "").strip().lower()
                        if encoding and encoding != "identity":
                            raise AppError(
                                "provider_encoding_unsupported",
                                "模型服务须返回未压缩的数据，请检查服务配置",
                                502,
                            )
                        limit = MAX_RESPONSE_BYTES if response.is_success else 64 * 1024
                        async for chunk in response.aiter_raw(chunk_size=16 * 1024):
                            captured.extend(chunk[: max(0, limit - len(captured))])
                            if len(captured) >= limit:
                                if not response.is_success:
                                    break
                                raise AppError(
                                    "provider_response_too_large", "模型返回的数据过大，请重试", 502
                                )
                        else:
                            complete = True
                        if not response.is_success:
                            raise AppError(
                                "provider_http_error", "模型服务请求失败，请稍后重试", 502
                            )
                        parsed = decode_object(bytes(captured).decode("utf-8"), limit=limit)
                        if parsed.get("error"):
                            raise AppError(
                                "provider_error", "模型服务未能完成分析，请稍后重试", 502
                            )
                        return (
                            self._responses_turn(parsed)
                            if provider.protocol == "responses"
                            else self._chat_turn(parsed)
                        )
        except Exception as exc:
            log_failure(
                logger,
                "provider_completion",
                exc,
                duration_ms=(perf_counter() - started) * 1000,
                details={
                    "protocol": provider.protocol,
                    "method": "POST",
                    "url": safe_url(url),
                    **response_diagnostics(response, bytes(captured), complete=complete),
                },
            )
            if isinstance(exc, AppError):
                raise
            if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                raise AppError(
                    "provider_timeout", "模型响应超时，请稍后重试", 504
                ) from safe_exception(exc)
            raise AppError(
                "provider_invalid_response", "模型返回异常，请重试或切换模型", 502
            ) from safe_exception(exc)

    def _chat_turn(self, value: dict[str, object]) -> AgentTurn:
        choices = object_list(value.get("choices"))
        if len(choices) != 1:
            raise ValueError("Expected exactly one model choice")
        choice = choices[0]
        reason = choice.get("finish_reason")
        if reason not in {"stop", "tool_calls"}:
            self._completion_error(reason)
        message = json_object(choice.get("message"))
        if message.get("role") != "assistant":
            raise ValueError("Invalid Chat Completions assistant role")
        if message.get("refusal") or message.get("function_call"):
            raise AppError(
                "provider_tool_unsupported", "模型未能使用分析工具，请切换支持工具调用的模型", 502
            )
        calls_value = message.get("tool_calls", [])
        raw_calls = object_list(calls_value)
        if len(raw_calls) > MAX_CALLS_PER_ROUND:
            raise AppError("agent_tool_limit", "模型一次请求的工具数量过多，请重试", 502)
        calls: list[ToolCall] = []
        for item in raw_calls:
            if item.get("type") != "function":
                raise ValueError("Unsupported model tool type")
            calls.append(tool_call(item, responses=False))
        self._check_calls(calls)
        if reason == "tool_calls" and not calls:
            raise ValueError("Model omitted tool calls")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("Invalid model message content")
        continuation: dict[str, object] = {"role": "assistant", "content": content}
        if raw_calls:
            continuation["tool_calls"] = [
                {
                    "id": call.identifier,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": encode_json(call.arguments, limit=MAX_ARGUMENT_BYTES),
                    },
                }
                for call in calls
            ]
        return AgentTurn(content or "", calls, [continuation])

    def _responses_turn(self, value: dict[str, object]) -> AgentTurn:
        if value.get("status") != "completed":
            details = value.get("incomplete_details")
            self._completion_error(details.get("reason") if isinstance(details, dict) else None)
        output = object_list(value.get("output"))
        calls: list[ToolCall] = []
        texts: list[str] = []
        for item in output:
            kind = item.get("type")
            if kind == "function_call":
                calls.append(tool_call(item, responses=True))
            elif kind == "message":
                if item.get("role") != "assistant" or item.get("status") not in {None, "completed"}:
                    raise ValueError("Invalid Responses assistant message")
                for part in object_list(item.get("content")):
                    if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                        raise AppError(
                            "provider_refused", "模型未能完成分析，请调整内容或切换模型", 502
                        )
                    text = part["text"]
                    if isinstance(text, str):
                        texts.append(text)
            elif kind != "reasoning":
                raise ValueError("Unsupported Responses output item")
        self._check_calls(calls)
        return AgentTurn("".join(texts), calls, output)

    @staticmethod
    def _check_calls(calls: list[ToolCall]) -> None:
        if len(calls) > MAX_CALLS_PER_ROUND or len({call.identifier for call in calls}) != len(
            calls
        ):
            raise ValueError("Invalid tool call count or duplicate identifier")

    @staticmethod
    def _completion_error(reason: object) -> None:
        if reason in ("length", "max_output_tokens"):
            raise AppError(
                "output_limit_exceeded", "模型输出达到上限，请提高最大输出 Token 后重试", 502
            )
        if reason == "content_filter":
            raise AppError("content_filtered", "模型未能完成分析，请调整内容或切换模型", 502)
        raise AppError("provider_incomplete", "模型分析未完成，请稍后重试", 502)
