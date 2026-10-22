import asyncio
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from time import perf_counter
from urllib.parse import urlsplit

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from mcp.types import CallToolResult

from app.ai.providers.diagnostics import (
    log_failure,
    response_diagnostics,
    safe_exception,
    safe_sdk_logging,
    safe_url,
)
from app.ai.tools.types import (
    MAX_ARGUMENT_NODES,
    MAX_RESULT_BYTES,
    MAX_TOOLS,
    TOOL_NAME,
    ToolDefinition,
    check_schema,
    encode_json,
    json_object,
    validate_tool_value,
    validation_units,
)
from app.common.exceptions import AppError

logger = logging.getLogger(__name__)
MAX_WIRE_BYTES = 2 * 1024 * 1024
MAX_DISCOVERY_PAGES = 16


class _SafeClientSession(ClientSession):
    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        *,
        timeout: int,
    ) -> None:
        super().__init__(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout))
        self.output_schemas: dict[str, dict[str, object]] = {}

    async def _validate_tool_result(self, name: str, result: CallToolResult) -> None:
        # The SDK otherwise validates output synchronously before our caller can
        # enforce node/work limits. Keep its real tools/call procedure and replace
        # only that pre-return validation hook (SDK version is constrained to <2).
        output = json_object(result.model_dump(mode="json", by_alias=True, exclude_none=True))
        validation_units(output, max_nodes=MAX_ARGUMENT_NODES)
        encode_json(output, limit=MAX_RESULT_BYTES)
        schema = self.output_schemas.get(name)
        if schema is not None:
            if result.structuredContent is None:
                raise AppError("mcp_output_missing", "MCP 工具未返回规范要求的数据", 502)
            validate_tool_value(schema, json_object(result.structuredContent), output=True)


def validated_url(value: str) -> httpx.URL:
    try:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or "?" in value
            or "#" in value
            or "\\" in value
            or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            or len(value) > 2048
        ):
            raise ValueError("MCP endpoint must be an HTTP URL without credentials or query")
        url = httpx.URL(value)
        if not 1 <= (url.port or (443 if url.scheme == "https" else 80)) <= 65535:
            raise ValueError("Invalid MCP endpoint port")
        return url
    except (ValueError, httpx.InvalidURL) as exc:
        raise AppError(
            "mcp_url_invalid", "MCP 地址无效，请使用不含凭据或参数的 HTTP 地址"
        ) from safe_exception(exc)


def permitted_ip(value: str, *, allow_private: bool) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if isinstance(address, ipaddress.IPv6Address) and any(
        address in network
        for network in (
            ipaddress.ip_network("64:ff9b::/96"),
            ipaddress.ip_network("64:ff9b:1::/48"),
            ipaddress.ip_network("2002::/16"),
            ipaddress.ip_network("2001::/32"),
        )
    ):
        # Translation/tunneling prefixes can hide an embedded private IPv4 target.
        return False
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        return False
    # Link-local metadata services stay blocked even when a private MCP is enabled.
    return address.is_global or (allow_private and (address.is_private or address.is_loopback))


class _LimitedStream(httpx.AsyncByteStream):
    def __init__(
        self, response: httpx.Response, *, limit: int, diagnostics: dict[str, object]
    ) -> None:
        self.response = response
        self.limit = limit
        self.received = 0
        self.captured = bytearray()
        self.diagnostics = diagnostics
        self.complete = False
        self.started = perf_counter()

    def _update_diagnostics(self) -> None:
        if self.response.request.method == "POST":
            self.diagnostics.update(
                response_diagnostics(
                    self.response,
                    bytes(self.captured),
                    complete=self.complete and self.received == len(self.captured),
                ),
                response_size=self.received,
            )

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.response.aiter_raw(chunk_size=16 * 1024):
                self.received += len(chunk)
                self.captured.extend(chunk[: max(0, 64 * 1024 - len(self.captured))])
                if self.received > self.limit:
                    raise AppError(
                        "mcp_response_too_large", "MCP 返回的数据过大，请缩小查询范围", 502
                    )
                yield chunk
            self.complete = True
        except Exception as exc:
            log_failure(
                logger,
                "mcp_response_read",
                exc,
                duration_ms=(perf_counter() - self.started) * 1000,
                details=response_diagnostics(self.response, bytes(self.captured)),
            )
            raise
        finally:
            self._update_diagnostics()

    async def aclose(self) -> None:
        self._update_diagnostics()
        await self.response.aclose()


class _PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, endpoint: httpx.URL, *, allow_private: bool, timeout: int) -> None:
        self.endpoint = endpoint
        self.allow_private = allow_private
        self.timeout = timeout
        self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.diagnostics: dict[str, object] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = perf_counter()
        upstream: httpx.Response | None = None
        captured = bytearray()
        try:
            if request.url != self.endpoint:
                raise AppError("mcp_redirect_blocked", "MCP 地址发生变更，请检查配置", 502)
            port = self.endpoint.port or (443 if self.endpoint.scheme == "https" else 80)
            async with asyncio.timeout(min(10, self.timeout)):
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    self.endpoint.host, port, type=socket.SOCK_STREAM
                )
            resolved = list(dict.fromkeys(str(item[4][0]) for item in addresses))
            if not resolved or any(
                not permitted_ip(address, allow_private=self.allow_private) for address in resolved
            ):
                raise AppError("mcp_address_blocked", "MCP 地址不在允许的网络范围内，请联系管理员")
            # Connect directly to the validated address: the HTTP transport cannot
            # resolve the hostname again, so DNS rebinding cannot change the target.
            headers = request.headers.copy()
            host = self.endpoint.host
            host = f"[{host}]" if ":" in host else host
            default_port = 443 if self.endpoint.scheme == "https" else 80
            headers["Host"] = host + (f":{port}" if port != default_port else "")
            headers["Accept-Encoding"] = "identity"
            extensions = {**request.extensions, "sni_hostname": self.endpoint.host}
            pinned = httpx.Request(
                request.method,
                self.endpoint.copy_with(host=resolved[0]),
                headers=headers,
                stream=request.stream,
                extensions=extensions,
            )
            upstream = await self.transport.handle_async_request(pinned)
            upstream.request = request
            if request.method == "POST":
                self.diagnostics.update(response_diagnostics(upstream))
            encoding = upstream.headers.get("content-encoding", "").strip().lower()
            if encoding and encoding != "identity":
                # Even one aiter_bytes() step can inflate an entire gzip/brotli
                # bomb before a byte limit or asyncio deadline can intervene.
                # Never invoke a decoder for an untrusted MCP response.
                raise AppError(
                    "mcp_encoding_unsupported", "MCP 服务须返回未压缩的数据，请检查服务配置", 502
                )
            declared_size = upstream.headers.get("content-length", "")
            if declared_size and (
                len(declared_size) > 12
                or not declared_size.isascii()
                or not declared_size.isdigit()
                or int(declared_size) > MAX_WIRE_BYTES
            ):
                raise AppError("mcp_response_too_large", "MCP 返回的数据过大，请缩小查询范围", 502)
            content_type = upstream.headers.get("content-type", "").split(";", 1)[0].lower()
            unexpected_type = (
                request.method == "POST"
                and upstream.status_code == 200
                and content_type not in {"application/json", "text/event-stream"}
            )
            # Never follow redirects, including an HTTPS -> HTTP Location.
            if (
                upstream.status_code >= 300
                and not (request.method in {"GET", "DELETE"} and upstream.status_code in {404, 405})
            ) or unexpected_type:
                async for chunk in upstream.aiter_raw(chunk_size=16 * 1024):
                    captured.extend(chunk[: max(0, 64 * 1024 - len(captured))])
                    if len(captured) >= 64 * 1024:
                        break
                await upstream.aclose()
                raise AppError("mcp_http_error", "MCP 服务请求失败，请检查地址或访问配置", 502)
            # The inner stream and the SDK only ever see bounded identity bytes.
            response_headers = upstream.headers.copy()
            response_headers.pop("content-encoding", None)
            response_headers.pop("content-length", None)
            return httpx.Response(
                upstream.status_code,
                headers=response_headers,
                stream=_LimitedStream(upstream, limit=MAX_WIRE_BYTES, diagnostics=self.diagnostics),
                extensions=upstream.extensions,
            )
        except Exception as exc:
            if upstream is not None:
                await upstream.aclose()
            log_failure(
                logger,
                "mcp_transport",
                exc,
                duration_ms=(perf_counter() - started) * 1000,
                details={
                    "method": request.method,
                    "url": safe_url(str(request.url)),
                    **response_diagnostics(upstream, bytes(captured)),
                },
            )
            if isinstance(exc, AppError):
                raise
            raise AppError(
                "mcp_connection_failed", "MCP 连接失败，请检查配置后重试", 502
            ) from safe_exception(exc)

    async def aclose(self) -> None:
        await self.transport.aclose()


class MCPConnection:
    def __init__(
        self,
        url: str,
        token: str = "",
        allowed_tools: list[str] | None = None,
        timeout: int = 30,
        allow_private: bool = False,
    ) -> None:
        self.url = validated_url(url)
        if not 1 <= timeout <= 120 or len(token) > 8192 or any(ord(char) < 32 for char in token):
            raise AppError("mcp_configuration_invalid", "MCP 连接配置无效")
        allowed = allowed_tools or []
        if len(allowed) > MAX_TOOLS or any(not TOOL_NAME.fullmatch(name) for name in allowed):
            raise AppError("mcp_configuration_invalid", "MCP 工具清单配置无效")
        self.token = token
        self.allowed_tools = frozenset(allowed)
        self.timeout = timeout
        self.allow_private = allow_private

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[_SafeClientSession]:
        started = perf_counter()
        transport = _PinnedTransport(
            self.url, allow_private=self.allow_private, timeout=self.timeout
        )
        try:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            with safe_sdk_logging():
                # The total deadline includes initialization, pagination, tool call,
                # and cleanup, not just an individual socket read.
                async with asyncio.timeout(self.timeout):
                    async with httpx.AsyncClient(
                        headers=headers,
                        timeout=httpx.Timeout(self.timeout, connect=min(10, self.timeout)),
                        follow_redirects=False,
                        trust_env=False,
                        transport=transport,
                    ) as client:
                        async with streamable_http_client(
                            str(self.url), http_client=client
                        ) as streams:
                            async with _SafeClientSession(
                                streams[0],
                                streams[1],
                                timeout=self.timeout,
                            ) as session:
                                await session.initialize()
                                yield session
        except Exception as exc:
            log_failure(
                logger,
                "mcp_session",
                exc,
                duration_ms=(perf_counter() - started) * 1000,
                details={
                    "url": safe_url(str(self.url)),
                    "retry_count": 0,
                    **transport.diagnostics,
                },
            )
            if isinstance(exc, AppError):
                raise
            raise AppError(
                "mcp_unavailable", "MCP 工具暂时不可用，请检查配置后重试", 502
            ) from safe_exception(exc)

    async def _discover(self, session: _SafeClientSession) -> list[ToolDefinition]:
        tools: dict[str, ToolDefinition] = {}
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(MAX_DISCOVERY_PAGES):
            result = await session.list_tools(cursor=cursor)
            for item in result.tools:
                if item.outputSchema is not None:
                    output_schema = json_object(item.outputSchema)
                    check_schema(output_schema)
                    session.output_schemas[item.name] = output_schema
                definition = ToolDefinition(
                    name=item.name,
                    description=item.description or "",
                    input_schema=json_object(item.inputSchema),
                )
                definition.validate()
                if definition.name in tools or len(tools) >= MAX_TOOLS:
                    raise AppError("mcp_tool_catalog_invalid", "MCP 工具清单重复或数量过多", 502)
                tools[definition.name] = definition
            if not result.nextCursor:
                return list(tools.values())
            if result.nextCursor in seen_cursors or len(result.nextCursor) > 2048:
                raise AppError("mcp_tool_catalog_invalid", "MCP 工具清单分页异常", 502)
            cursor = result.nextCursor
            seen_cursors.add(cursor)
        raise AppError("mcp_tool_catalog_limit", "MCP 工具清单过大，请缩减工具数量", 502)

    async def discover(self) -> list[ToolDefinition]:
        # Discovery is explicitly requested by the configuration UI. Discovery never
        # authorizes execution; only the backend's saved allowlist permits call().
        async with self._session() as session:
            return await self._discover(session)

    async def call(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name not in self.allowed_tools:
            raise AppError("mcp_tool_not_allowed", "此 MCP 工具未获授权，请先在配置中启用")
        async with self._session() as session:
            definitions = await self._discover(session)
            definition = next((tool for tool in definitions if tool.name == name), None)
            if definition is None:
                raise AppError("mcp_tool_missing", "已配置的 MCP 工具不存在，请重新发现工具", 502)
            definition.validate_arguments(arguments)
            result = await session.call_tool(
                name, arguments=arguments, read_timeout_seconds=timedelta(seconds=self.timeout)
            )
            output = json_object(result.model_dump(mode="json", by_alias=True, exclude_none=True))
            validation_units(output, max_nodes=MAX_ARGUMENT_NODES)
            encode_json(output, limit=MAX_RESULT_BYTES)
            if result.isError:
                # The untrusted server's error text is neither success data nor a UI message.
                raise AppError("mcp_tool_failed", "MCP 工具执行失败，请检查服务后重试", 502)
            return output
