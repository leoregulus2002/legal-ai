import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Literal

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.common.exceptions import AppError
from app.core.logging import redact_log_text

logger = logging.getLogger(__name__)
OFFICIAL_ORIGIN = "https://flk.npc.gov.cn"
FILE_HOST = "flkoss.obs-bj2.cucloud.cn"
MAX_REDIRECTS = 3
REDIRECT_BODY_LIMIT = 64 * 1024
_request_interval: ContextVar[int] = ContextVar("public_law_request_interval_ms", default=0)
_RATE_LIMIT_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local interval = tonumber(ARGV[1])
local previous = redis.call('HMGET', KEYS[1], 'started_at', 'interval_ms')
if previous[1] then
    local required = math.max(interval, tonumber(previous[2]) or interval)
    local remaining = tonumber(previous[1]) + required - now
    if remaining > 0 then
        return remaining
    end
end
redis.call('HSET', KEYS[1], 'started_at', now, 'interval_ms', interval)
redis.call('PEXPIRE', KEYS[1], math.max(interval, 60000) * 2)
return 0
"""


class OfficialLawRedirectError(httpx.HTTPStatusError):
    def __init__(self, response: httpx.Response, reason: str, body: bytes, complete: bool) -> None:
        super().__init__(
            f"Official law redirect rejected: {reason}",
            request=response.request,
            response=response,
        )
        self.body = body
        self.body_complete = complete


@contextmanager
def request_interval(milliseconds: int) -> Iterator[None]:
    token = _request_interval.set(milliseconds)
    try:
        yield
    finally:
        _request_interval.reset(token)


class OfficialLawClient:
    def __init__(self, redis: Redis, *, minimum_interval_ms: int = 1000) -> None:
        self.redis = redis
        self.minimum_interval_ms = minimum_interval_ms
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            headers={"Referer": OFFICIAL_ORIGIN + "/"},
        )
        # 同一进程串行发送，保证下一次请求使用更新后的 Cookie。
        self.lock = asyncio.Lock()

    async def close(self) -> None:
        await self.client.aclose()

    async def wait_for_slot(self) -> None:
        interval = max(self.minimum_interval_ms, _request_interval.get())
        started = perf_counter()
        try:
            while True:
                remaining = await self.redis.eval(
                    _RATE_LIMIT_SCRIPT, 1, "legal_ai:public_laws:request_timing", interval
                )
                if remaining <= 0:
                    return
                await asyncio.sleep(remaining / 1000)
        except (RedisError, OSError) as exc:
            logger.warning(
                "公开法律库请求限速失败 stage=RATE_LIMIT interval_ms=%s duration_ms=%.1f",
                interval,
                (perf_counter() - started) * 1000,
                exc_info=exc,
            )
            # 不在共享限速失效时继续集中访问官网。
            raise AppError(
                "public_law_unavailable", "公开法律库暂时不可用，请稍后重试", 502
            ) from exc

    @staticmethod
    def allowed_url(url: httpx.URL, host: str) -> bool:
        return (
            url.scheme == "https"
            and url.host == host
            and url.port in (None, 443)
            and not url.userinfo
        )

    @staticmethod
    async def redirect_error(response: httpx.Response, reason: str) -> OfficialLawRedirectError:
        body = bytearray()
        complete = True
        try:
            async with asyncio.timeout(3):
                async for chunk in response.aiter_bytes():
                    body.extend(chunk[: max(0, REDIRECT_BODY_LIMIT + 1 - len(body))])
                    if len(body) > REDIRECT_BODY_LIMIT:
                        complete = False
                        break
        except (httpx.HTTPError, TimeoutError) as exc:
            complete = False
            logger.warning(
                "公开法律库重定向证据读取失败 method=%s url=%s status=%s reason=%s bytes=%s",
                response.request.method,
                redact_log_text(str(response.request.url)),
                response.status_code,
                reason,
                len(body),
                exc_info=exc,
            )
        return OfficialLawRedirectError(
            response, reason, bytes(body[:REDIRECT_BODY_LIMIT]), complete
        )

    @asynccontextmanager
    async def stream(
        self,
        method: Literal["GET", "POST"],
        url: str,
        *,
        payload: object = None,
        params: dict[str, str] | None = None,
        download: bool = False,
    ) -> AsyncIterator[httpx.Response]:
        host = FILE_HOST if download else "flk.npc.gov.cn"
        target = httpx.URL(url)
        if not self.allowed_url(target, host):
            raise ValueError("Official law request URL is not allowed")
        async with self.lock:
            request = self.client.build_request(
                method,
                target,
                params=params,
                **({"json": payload} if payload is not None else {}),
                headers={"Accept": "*/*" if download else "application/json"},
                timeout=httpx.Timeout(45 if download else 30, connect=10),
            )
            for redirects in range(MAX_REDIRECTS + 1):
                await self.wait_for_slot()
                response = await self.client.send(request, stream=True, follow_redirects=False)
                try:
                    if not response.has_redirect_location:
                        yield response
                        return
                    next_request = response.next_request
                    reason = (
                        "redirect_limit"
                        if redirects == MAX_REDIRECTS
                        else "redirect_target_not_allowed"
                        if next_request is None or not self.allowed_url(next_request.url, host)
                        else "redirect_method_changed"
                        if next_request.method != method
                        else None
                    )
                    if reason:
                        raise await self.redirect_error(response, reason)
                    logger.info(
                        "公开法律库跟随重定向 method=%s url=%s status=%s target=%s hop=%s",
                        request.method,
                        redact_log_text(str(request.url)),
                        response.status_code,
                        redact_log_text(str(next_request.url)),
                        redirects + 1,
                    )
                    request = next_request
                finally:
                    await response.aclose()

    async def request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        payload: object = None,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with self.stream(
            method, OFFICIAL_ORIGIN + path, payload=payload, params=params
        ) as response:
            await response.aread()
            return response
