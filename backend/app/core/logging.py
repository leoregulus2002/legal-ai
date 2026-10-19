import json
import logging
import re
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from types import TracebackType
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi.exceptions import RequestValidationError
from psycopg import Error as PsycopgError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_context: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)
_urls = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>\"']+")
_secrets = re.compile(
    r"(?i)([\"']?\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|"
    r"password|passwd|credential|signature|access[_-]?key[_-]?id|secret[_-]?access[_-]?key)"
    r"[\"']?\s*[:=]\s*)"
    r"(?:\[REDACTED\]|\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)


def redact_log_text(value: str) -> str:
    def redact_url(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match.group())
            host = parsed.netloc.rsplit("@", 1)[-1]
            return urlunsplit(
                (parsed.scheme, host, parsed.path, "REDACTED" if parsed.query else "", "")
            )
        except ValueError:
            return "[REDACTED_URL]"

    value = _urls.sub(redact_url, value)
    value = _secrets.sub(r"\1[REDACTED]", value)
    value = re.sub(
        r"(?is)<(token|secret|password|credential|accesskeyid|secretaccesskey)>.*?</\1>",
        r"<\1>[REDACTED]</\1>",
        value,
    )
    value = re.sub(
        r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*"
        r"(?:\[REDACTED\]|\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\r\n]*)",
        r"\1=[REDACTED]",
        value,
    )
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{10,}", "[REDACTED_KEY]", value)
    return re.sub(
        r"(?im)^\s*(?:\[parameters:|DETAIL:|CONTEXT:).*$", "[REDACTED_DATABASE_DETAIL]", value
    )


def current_log_context() -> dict[str, str]:
    return dict(_context.get() or {})


@contextmanager
def log_context(**values: str) -> Iterator[None]:
    token = _context.set({**(_context.get() or {}), **values})
    try:
        yield
    finally:
        _context.reset(token)


class SafeLogFormatter(logging.Formatter):
    def formatException(
        self, ei: tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
    ) -> str:
        if ei[1] is None:
            return "NoneType: None"
        seen: set[int] = set()

        def render(exc: BaseException) -> str:
            if id(exc) in seen:
                return "[exception chain cycle omitted]\n"
            seen.add(id(exc))
            parts: list[str] = []
            if exc.__cause__ is not None:
                parts.append(render(exc.__cause__))
                parts.append("\nThe above exception was the direct cause of the following:\n\n")
            elif exc.__context__ is not None and not exc.__suppress_context__:
                parts.append(render(exc.__context__))
                parts.append(
                    "\nDuring handling of the above exception, another exception occurred:\n\n"
                )
            if exc.__traceback__ is not None:
                parts.append("Traceback (most recent call last):\n")
                parts.extend(traceback.format_tb(exc.__traceback__))
            name = f"{type(exc).__module__}.{type(exc).__qualname__}"
            if isinstance(exc, (SQLAlchemyError, PsycopgError)):
                original = getattr(exc, "orig", exc)
                # 数据库异常原文可能带完整失败行，保留 SQLSTATE 与堆栈即可定位。
                description = (
                    f"sqlstate={getattr(original, 'sqlstate', None)} database detail redacted"
                )
            elif isinstance(exc, (ValidationError, RequestValidationError)):
                description = "validation_errors=" + json.dumps(
                    [{"loc": row["loc"], "type": row["type"]} for row in exc.errors()],
                    ensure_ascii=False,
                    default=str,
                )
            else:
                description = redact_log_text(str(exc))
                if len(description) > 4096:
                    description = description[:4096] + " [exception message truncated]"
            parts.append(f"{name}: {description}\n")
            if isinstance(exc, BaseExceptionGroup):
                for index, nested in enumerate(exc.exceptions, 1):
                    parts.append(f"\nNested exception {index}:\n{render(nested)}")
            return "".join(parts)

        return redact_log_text(render(ei[1])).rstrip()

    def formatMessage(self, record: logging.LogRecord) -> str:
        output = super().formatMessage(record)
        context = _context.get()
        if context:
            output += " context=" + json.dumps(context, ensure_ascii=False)
        return output

    def format(self, record: logging.LogRecord) -> str:
        return redact_log_text(super().format(record))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    formatter = SafeLogFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in ("", "uvicorn", "uvicorn.error"):
        for configured in logging.getLogger(name).handlers:
            configured.setFormatter(formatter)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("legal_ai.requests")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        with log_context(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            finally:
                self.logger.info(
                    "%s %s status=%d duration_ms=%.1f request_id=%s",
                    scope["method"],
                    scope["path"],
                    status,
                    (perf_counter() - started) * 1000,
                    request_id,
                )
