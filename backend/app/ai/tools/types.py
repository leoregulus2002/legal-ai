import json
import logging
import math
import re
from dataclasses import dataclass
from time import perf_counter

from jsonschema import Draft202012Validator

from app.ai.providers.diagnostics import log_failure, safe_exception
from app.common.exceptions import AppError

MAX_TOOLS = 64
MAX_CALLS_PER_ROUND = 8
MAX_SCHEMA_BYTES = 32 * 1024
MAX_ARGUMENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 128 * 1024
TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
MAX_SCHEMA_NODES = 512
MAX_ARGUMENT_NODES = 2048
MAX_VALIDATION_WORK = 250_000
MAX_VALIDATION_DEPTH = 16
MAX_COMBINATOR_BRANCHES = 24
MAX_COMBINATOR_WIDTH = 4
MAX_COMBINATOR_DEPTH = 3
logger = logging.getLogger(__name__)


def validation_units(value: object, *, max_nodes: int) -> int:
    nodes = 0
    units = 0

    def inspect(item: object, depth: int) -> None:
        nonlocal nodes, units
        nodes += 1
        if nodes > max_nodes or depth > MAX_VALIDATION_DEPTH:
            raise ValueError("Tool validation node or depth budget exceeded")
        units += 1
        if isinstance(item, str):
            units += (len(item) + 63) // 64
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("Tool validation requires JSON keys")
                inspect(key, depth + 1)
                inspect(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                inspect(child, depth + 1)

    inspect(value, 0)
    return units


def json_value(value: object, *, depth: int = 0, counter: list[int] | None = None) -> object:
    """Narrow untrusted SDK/JSON values without permitting arbitrary Python objects."""
    nodes = counter if counter is not None else [0]
    nodes[0] += 1
    if depth > 32 or nodes[0] > 50_000:
        raise ValueError("JSON nesting or node limit exceeded")
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [json_value(item, depth=depth + 1, counter=nodes) for item in value]
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object key must be text")
            result[key] = json_value(item, depth=depth + 1, counter=nodes)
        return result
    raise ValueError("Unsupported JSON value")


def json_object(value: object) -> dict[str, object]:
    checked = json_value(value)
    if not isinstance(checked, dict):
        raise ValueError("Expected a JSON object")
    return {str(key): item for key, item in checked.items()}


def encode_json(value: object, *, limit: int) -> str:
    checked = json_value(value)
    encoded = json.dumps(checked, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > limit:
        raise AppError("agent_payload_too_large", "分析内容或工具数据过大，请缩减内容后重试")
    return encoded


def decode_object(value: str, *, limit: int) -> dict[str, object]:
    if len(value.encode("utf-8")) > limit:
        raise AppError("agent_payload_too_large", "模型返回的数据过大，请缩减内容后重试", 502)

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = item
        return result

    parsed: object = json.loads(value, object_pairs_hook=unique_object)
    return json_object(parsed)


def check_schema(schema: dict[str, object], *, max_nodes: int = MAX_SCHEMA_NODES) -> int:
    started = perf_counter()
    try:
        units = validation_units(schema, max_nodes=max_nodes)
        encode_json(schema, limit=MAX_SCHEMA_BYTES)
        if schema.get("type") != "object":
            raise ValueError("Tool schema must have object type")
        branches = 0

        def inspect(value: object, combinator_depth: int = 0) -> None:
            nonlocal branches
            if isinstance(value, bool):
                return
            if not isinstance(value, dict):
                raise ValueError("Tool subschema must be an object or boolean")
            for key, item in value.items():
                # No regular expressions or references reach jsonschema (or the
                # official MCP SDK). A timeout cannot interrupt Python re safely.
                if key in {
                    "pattern",
                    "patternProperties",
                    "$ref",
                    "$dynamicRef",
                    "$recursiveRef",
                    "$id",
                    "uniqueItems",
                    "unevaluatedProperties",
                    "unevaluatedItems",
                }:
                    raise ValueError("Tool schema uses a disabled validation keyword")
                if key == "$schema" and item not in (
                    "https://json-schema.org/draft/2020-12/schema",
                    "https://json-schema.org/draft/2020-12/schema#",
                ):
                    raise ValueError("Tool schema must use JSON Schema 2020-12")
                if key in {"allOf", "anyOf", "oneOf"}:
                    if not isinstance(item, list) or not 1 <= len(item) <= MAX_COMBINATOR_WIDTH:
                        raise ValueError("Tool schema combinator width budget exceeded")
                    branches += len(item)
                    if (
                        branches > MAX_COMBINATOR_BRANCHES
                        or combinator_depth >= MAX_COMBINATOR_DEPTH
                    ):
                        raise ValueError("Tool schema combinator budget exceeded")
                    for child in item:
                        inspect(child, combinator_depth + 1)
                elif key == "prefixItems":
                    if not isinstance(item, list) or len(item) > 16:
                        raise ValueError("Tool schema tuple budget exceeded")
                    for child in item:
                        inspect(child, combinator_depth)
                elif key in {"properties", "$defs", "dependentSchemas"}:
                    if not isinstance(item, dict):
                        raise ValueError("Tool schema mapping is invalid")
                    for child in item.values():
                        inspect(child, combinator_depth)
                elif key in {
                    "additionalProperties",
                    "items",
                    "contains",
                    "propertyNames",
                    "if",
                    "then",
                    "else",
                    "not",
                }:
                    inspect(item, combinator_depth)

        inspect(schema)
        # Regex/URI formats in the metaschema are unnecessary here. Runtime
        # validation also deliberately has no format checker.
        Draft202012Validator.check_schema(schema, format_checker=None)
        return units
    except Exception as exc:
        log_failure(
            logger,
            "tool_schema_validation",
            exc,
            duration_ms=(perf_counter() - started) * 1000,
        )
        raise AppError(
            "tool_schema_invalid", "工具参数规范不受支持，请检查工具配置"
        ) from safe_exception(exc)


def validate_tool_value(
    schema: dict[str, object], value: dict[str, object], *, output: bool = False
) -> None:
    started = perf_counter()
    try:
        schema_units = check_schema(schema)
        value_units = validation_units(value, max_nodes=MAX_ARGUMENT_NODES)
        if schema_units * value_units > MAX_VALIDATION_WORK:
            raise ValueError("Tool schema and value work budget exceeded")
        encode_json(value, limit=MAX_RESULT_BYTES if output else MAX_ARGUMENT_BYTES)
        Draft202012Validator(schema, format_checker=None).validate(value)
    except Exception as exc:
        log_failure(
            logger,
            "tool_output_validation" if output else "tool_arguments_validation",
            exc,
            duration_ms=(perf_counter() - started) * 1000,
        )
        code = "tool_output_invalid" if output else "tool_arguments_invalid"
        message = "工具返回数据格式无效，请检查工具服务" if output else "工具调用参数无效，请重试"
        raise AppError(code, message, 502) from safe_exception(exc)


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, object]

    def validate(self) -> None:
        if not TOOL_NAME.fullmatch(self.name) or len(self.description) > 4096:
            raise AppError("tool_definition_invalid", "工具定义无效，请检查工具配置")
        check_schema(self.input_schema)

    def validate_arguments(self, arguments: dict[str, object]) -> None:
        validate_tool_value(self.input_schema, arguments)
