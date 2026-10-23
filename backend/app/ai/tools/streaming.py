import hashlib
import json
import logging
from dataclasses import dataclass, field
from time import perf_counter

from app.ai.providers.diagnostics import log_failure, safe_excerpt
from app.ai.tools.types import (
    MAX_ARGUMENT_BYTES,
    MAX_CALLS_PER_ROUND,
    ToolDefinition,
    decode_object,
)
from app.common.exceptions import AppError

logger = logging.getLogger(__name__)


@dataclass
class PendingCall:
    name: str = ""
    arguments: str = ""
    item_id: str | None = None
    call_id: str | None = None
    snapshots: dict[str, str] = field(default_factory=dict)
    delta_events: int = 0

    def evidence(self, value: str, error: Exception | None = None) -> dict[str, object]:
        encoded = value.encode("utf-8")
        position = error.pos if isinstance(error, json.JSONDecodeError) else None
        start = max(0, position - 160) if position is not None else 0
        excerpt = value[start : start + 320]
        details: dict[str, object] = {
            "argument_chars": len(value),
            "argument_bytes": len(encoded),
            "encoding": "utf-8",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "nul_count": encoded.count(b"\x00"),
            "utf8_bom": encoded.startswith(b"\xef\xbb\xbf"),
            "raw_excerpt": safe_excerpt(excerpt, 640),
            "excerpt_start": start,
            "excerpt_truncated": start > 0 or start + len(excerpt) < len(value),
            "delta_events": self.delta_events,
        }
        if isinstance(error, json.JSONDecodeError):
            details.update(
                json_error=error.msg,
                json_error_position=error.pos,
                json_error_line=error.lineno,
                json_error_column=error.colno,
                error_at_end=error.pos >= len(value),
            )
        return details


@dataclass
class StreamingCalls:
    calls: dict[int, PendingCall] = field(default_factory=dict)

    def add(
        self,
        index: object,
        name: object,
        arguments: object,
        *,
        replace: bool = False,
        source: str = "snapshot",
        item_id: object = None,
        call_id: object = None,
        name_complete: bool = False,
    ) -> None:
        # Responses 的终态列表下标可能与中途事件不同，优先使用稳定的调用标识关联。
        for key, pending in self.calls.items():
            if (isinstance(item_id, str) and item_id and pending.item_id == item_id) or (
                isinstance(call_id, str) and call_id and pending.call_id == call_id
            ):
                index = key
                break
        if type(index) is not int or index < 0 or index > 1024:
            raise AppError("invalid_file_call", "文件生成请求格式异常，请重试", 502)
        if index not in self.calls and len(self.calls) >= MAX_CALLS_PER_ROUND:
            raise AppError("file_call_limit", "文件请求过多，请分批生成", 502)
        call = self.calls.setdefault(index, PendingCall())
        if isinstance(item_id, str) and item_id:
            if len(item_id) > 256 or (call.item_id and call.item_id != item_id):
                raise AppError("invalid_file_call", "文件生成请求标识异常，请重试", 502)
            call.item_id = item_id
        if isinstance(call_id, str) and call_id:
            if len(call_id) > 256 or (call.call_id and call.call_id != call_id):
                raise AppError("invalid_file_call", "文件生成请求标识异常，请重试", 502)
            call.call_id = call_id
        if isinstance(name, str):
            if (replace or name_complete) and name:
                if call.name and call.name != name:
                    raise AppError("invalid_file_call", "文件生成工具名称不一致，请重试", 502)
                call.name = name
            elif not replace and not name_complete:
                call.name += name
        if isinstance(arguments, str):
            if len(arguments.encode("utf-8")) > MAX_ARGUMENT_BYTES:
                raise AppError("file_request_too_large", "文件内容过多，请减少内容或分批生成", 502)
            if replace:
                call.snapshots[source] = arguments
            else:
                call.arguments += arguments
                call.delta_events += 1
        if len(call.name) > 64 or len(call.arguments.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise AppError("file_request_too_large", "文件内容过多，请减少内容或分批生成", 502)

    def response_event(self, event: dict[str, object]) -> None:
        kind = event.get("type")
        if kind in {"response.output_item.added", "response.output_item.done"}:
            output = event.get("item")
            if isinstance(output, dict) and output.get("type") == "function_call":
                done = kind == "response.output_item.done"
                self.add(
                    event.get("output_index"),
                    output.get("name"),
                    output.get("arguments") if done else None,
                    replace=True,
                    source="output_item_done",
                    item_id=output.get("id"),
                    call_id=output.get("call_id"),
                )
        elif kind in {
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }:
            done = kind == "response.function_call_arguments.done"
            self.add(
                event.get("output_index"),
                event.get("name"),
                event.get("arguments") if done else event.get("delta"),
                replace=done,
                source="arguments_done",
                item_id=event.get("item_id"),
                call_id=event.get("call_id"),
                name_complete=True,
            )
        elif kind == "response.completed":
            response = event.get("response")
            outputs = response.get("output") if isinstance(response, dict) else None
            if isinstance(outputs, list):
                for index, output in enumerate(outputs):
                    if isinstance(output, dict) and output.get("type") == "function_call":
                        self.add(
                            index,
                            output.get("name"),
                            output.get("arguments"),
                            replace=True,
                            source="response_completed",
                            item_id=output.get("id"),
                            call_id=output.get("call_id"),
                        )

    def diagnostics(self) -> dict[str, object]:
        return {
            "tool_calls": [
                {
                    "output_index": index,
                    "delta_events": call.delta_events,
                    "delta_argument_bytes": len(call.arguments.encode("utf-8")),
                    "snapshot_bytes": {
                        source: len(value.encode("utf-8"))
                        for source, value in call.snapshots.items()
                    },
                }
                for index, call in sorted(self.calls.items())
            ]
        }

    def results(self, tools: list[ToolDefinition]) -> list[tuple[str, dict[str, object]]]:
        allowed = {tool.name: tool for tool in tools}
        results: list[tuple[str, dict[str, object]]] = []
        for index, call in sorted(self.calls.items()):
            started = perf_counter()
            tool = allowed.get(call.name)
            if tool is None:
                raise AppError("unexpected_tool", "模型请求了不可用的文件工具，请重试", 502)
            candidates = dict(call.snapshots)
            if call.delta_events or not candidates:
                candidates["deltas"] = call.arguments
            parsed: list[tuple[str, dict[str, object]]] = []
            failures: list[dict[str, object]] = []
            last_error: Exception | None = None
            for source, value in candidates.items():
                try:
                    parsed.append((source, decode_object(value, limit=MAX_ARGUMENT_BYTES)))
                except (
                    json.JSONDecodeError,
                    ValueError,
                    TypeError,
                    RecursionError,
                    AppError,
                ) as exc:
                    last_error = exc
                    failures.append({"source": source, **call.evidence(value, exc)})
            if not parsed:
                error = last_error or ValueError("No tool arguments were received")
                log_failure(
                    logger,
                    "tool_arguments_decode",
                    error,
                    duration_ms=(perf_counter() - started) * 1000,
                    details={"output_index": index, "tool_name": tool.name, "candidates": failures},
                )
                raise AppError(
                    "invalid_tool_arguments", "模型返回的文件内容格式不完整，请重新生成", 502
                ) from error
            # 只接收已存在且一致的合法参数，不通过补括号或改正文来猜测模型意图。
            canonical = {
                json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
                for _, value in parsed
            }
            if len(canonical) != 1:
                error = ValueError("Completed tool argument sources disagree")
                log_failure(
                    logger,
                    "tool_arguments_conflict",
                    error,
                    duration_ms=(perf_counter() - started) * 1000,
                    details={
                        "output_index": index,
                        "tool_name": tool.name,
                        "candidates": [
                            {"source": source, **call.evidence(candidates[source])}
                            for source, _ in parsed
                        ],
                    },
                )
                raise AppError(
                    "inconsistent_tool_arguments", "模型返回的文件内容不一致，请重新生成", 502
                ) from error
            if failures:
                logger.warning(
                    "工具参数使用完整来源 stage=tool_arguments_recovery "
                    "output_index=%d tool_name=%s "
                    "accepted_sources=%s rejected_sources=%s duration_ms=%.1f",
                    index,
                    tool.name,
                    [source for source, _ in parsed],
                    failures,
                    (perf_counter() - started) * 1000,
                    exc_info=last_error,
                )
            arguments = parsed[0][1]
            tool.validate_arguments(arguments)
            results.append((call.name, arguments))
        return results
