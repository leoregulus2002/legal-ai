import hashlib
import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.common.exceptions import AppError
from app.core.logging import current_log_context, redact_log_text

_sensitive_upstream: ContextVar[bool] = ContextVar("ai_sensitive_upstream", default=False)
_KNOWN = frozenset(
    "error code message type status detail request id invalid unsupported tool function "
    "model context length exceeded max tokens rate limit quota insufficient authentication "
    "unauthorized forbidden denied not found bad gateway timeout timed out unavailable "
    "internal server overload overloaded content filter policy violation request_id "
    "invalid_api_key invalid_request_error rate_limit_exceeded context_length_exceeded "
    "insufficient_quota server_error invalid_request content_filter max_output_tokens "
    "html head body title script style src href div span document cookie window location "
    "eval atob challenge captcha access cloudflare nginx javascript enable security "
    "validation failed json jsonrpc parse method params result data arguments name "
    "authorization token api key password secret null true false utf content_type "
    "session terminated protocol version unsupported_protocol_version "
    "tools functions parameters parameter required missing supported support does must be "
    "one of expected got schema json_object response_format max_tokens max_completion_tokens "
    "temperature invalid_function_parameters unsupported_parameter model_not_found "
    "application/json application/xml application/octet-stream text/html text/plain "
    "text/event-stream gzip br deflate utf-8 utf-16 utf-16le utf-16be ascii gbk gb18030".split()
)


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        visible_segments = {"api", "v1", "v2", "mcp", "sse", "responses", "chat", "completions"}
        path = "/".join(
            segment if not segment or segment in visible_segments else "[redacted]"
            for segment in parsed.path.split("/")
        )
        return urlunsplit((parsed.scheme, host + port, path, "", ""))[:512]
    except ValueError:
        return "[invalid URL]"


def safe_excerpt(value: str, limit: int = 2048) -> str:
    # Upstreams may echo document passages, tool arguments or even credentials. Retain
    # diagnostic vocabulary and source syntax, but never arbitrary response strings.
    value = redact_log_text(value[: 16 * 1024])
    value = re.sub(
        r"[\w@./:+%=-]+",
        lambda match: match[0] if match[0].lower() in _KNOWN else "[redacted]",
        value,
    )
    return value[:limit]


def safe_exception(exc: BaseException, seen: set[int] | None = None) -> Exception:
    visited = seen if seen is not None else set()
    if id(exc) in visited:
        return RuntimeError("exception chain cycle")
    visited.add(id(exc))
    message = f"{type(exc).__module__}.{type(exc).__qualname__}: {safe_excerpt(str(exc), 512)}"
    if isinstance(exc, AppError) and re.fullmatch(r"[a-z_]{1,80}", exc.code):
        message += f" code={exc.code} status={exc.status_code}"
    if isinstance(exc, BaseExceptionGroup):
        result: Exception = ExceptionGroup(
            message, [safe_exception(item, visited) for item in exc.exceptions]
        )
    else:
        result = RuntimeError(message)
    result = result.with_traceback(exc.__traceback__)
    if exc.__cause__ is not None:
        result.__cause__ = safe_exception(exc.__cause__, visited)
    elif exc.__context__ is not None and not exc.__suppress_context__:
        result.__context__ = safe_exception(exc.__context__, visited)
    return result


def log_failure(
    logger: logging.Logger,
    stage: str,
    exc: BaseException,
    *,
    duration_ms: float,
    details: dict[str, object] | None = None,
) -> None:
    logger.error(
        "AI operation failed stage=%s duration_ms=%.1f context=%s details=%s",
        stage,
        duration_ms,
        current_log_context(),
        details or {},
        exc_info=safe_exception(exc),
    )


class _SafeSDKLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if _sensitive_upstream.get():
            record.msg = safe_excerpt(record.getMessage())
            record.args = ()
            if record.exc_info and record.exc_info[1]:
                exc = safe_exception(record.exc_info[1])
                record.exc_info = (type(exc), exc, exc.__traceback__)
                record.exc_text = None
        return True


@contextmanager
def safe_sdk_logging() -> Iterator[None]:
    # SDK debug logs contain full JSON-RPC messages; filter only this task's context.
    for name in (
        "mcp.client.streamable_http",
        "mcp.shared.session",
        "mcp.client.session",
        "client",
        "httpx",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
    ):
        sdk_logger = logging.getLogger(name)
        if not any(isinstance(item, _SafeSDKLogFilter) for item in sdk_logger.filters):
            sdk_logger.addFilter(_SafeSDKLogFilter())
    token = _sensitive_upstream.set(True)
    try:
        yield
    finally:
        _sensitive_upstream.reset(token)


class _HTMLSummary(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.visible: list[str] = []
        self.in_title = False
        self.hidden = 0
        self.scripts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "script":
            self.scripts += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        if not self.hidden:
            self.visible.append(data)


def response_diagnostics(
    response: httpx.Response | None, body: bytes = b"", *, complete: bool = False
) -> dict[str, object]:
    if response is None:
        return {"response_received": False}
    encoding = response.charset_encoding or "utf-8"
    try:
        text = body[: 16 * 1024].decode(encoding, errors="replace")
    except LookupError:
        encoding = "utf-8"
        text = body[: 16 * 1024].decode(encoding, errors="replace")
    credential = response.request.headers.get("Authorization", "").removeprefix("Bearer ")
    upstream_id = next(
        (
            value
            for name in ("x-request-id", "request-id", "x-amz-request-id", "x-acs-request-id")
            if (value := response.headers.get(name))
            and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", value)
            and not value.startswith("sk-")
            and not (credential and credential in value)
        ),
        None,
    )
    details: dict[str, object] = {
        "method": response.request.method,
        "url": safe_url(str(response.request.url)),
        "status": response.status_code,
        "response_type": safe_excerpt(response.headers.get("content-type", ""), 128),
        "content_encoding": safe_excerpt(response.headers.get("content-encoding", ""), 64),
        "response_size": len(body),
        "declared_size": (
            int(value)
            if (value := response.headers.get("content-length", ""))
            and value.isascii()
            and value.isdigit()
            and len(value) <= 16
            else None
        ),
        "upstream_request_id": upstream_id,
        "encoding": safe_excerpt(encoding, 64),
        "byte_features": {
            "nul_count": body.count(b"\x00"),
            "decode_replacements": text.count("\ufffd"),
            "utf8_bom": body.startswith(b"\xef\xbb\xbf"),
            "gzip": body.startswith(b"\x1f\x8b"),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        "body_complete": complete,
        "raw_excerpt": safe_excerpt(text),
        "excerpt_truncated": len(body) > 16 * 1024 or len(text) > 2048 or not complete,
    }
    is_html = bool(re.search(r"<(?:!doctype|html|head|body|script|title)\b", text, re.I))
    if is_html:
        parser = _HTMLSummary()
        try:
            parser.feed(text)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "AI diagnostic HTML parsing failed", exc_info=safe_exception(exc)
            )
            details["html_parse_error"] = type(exc).__name__
        details.update(
            page_title=safe_excerpt(" ".join(parser.title), 256),
            visible_text=safe_excerpt(" ".join(parser.visible)),
            script_count=parser.scripts,
            page_markers=[
                marker
                for marker in (
                    "captcha",
                    "challenge",
                    "access denied",
                    "document.cookie",
                    "window.location",
                    "eval(",
                    "atob(",
                )
                if marker in text.lower()
            ],
        )
    elif (
        response.headers.get("content-type", "").lower().startswith("text/")
        or "json" in response.headers.get("content-type", "").lower()
        or "xml" in response.headers.get("content-type", "").lower()
        or text.lstrip().startswith(("{", "["))
    ):
        details["visible_text"] = safe_excerpt(text)
    else:
        details["raw_excerpt"] = "[non-text body omitted]"
        details["visible_text"] = "[non-text body omitted]"
    return details
