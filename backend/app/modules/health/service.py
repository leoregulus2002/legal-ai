import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.core.database import Database
from app.core.redis import RedisClient
from app.modules.health.schemas import DependencyChecks, ReadinessResponse

logger = logging.getLogger(__name__)


async def check_dependency(name: str, ping: Callable[[], Awaitable[None]]) -> str:
    try:
        async with asyncio.timeout(3):
            await ping()
        return "ok"
    except Exception:
        logger.warning("readiness dependency=%s unavailable", name)
        return "unavailable"


async def check_readiness(database: Database, redis: RedisClient) -> ReadinessResponse:
    db_status, redis_status = await asyncio.gather(
        check_dependency("database", database.ping), check_dependency("redis", redis.ping)
    )
    checks = DependencyChecks(database=db_status, redis=redis_status)
    status = "ok" if db_status == redis_status == "ok" else "unavailable"
    return ReadinessResponse(status=status, checks=checks)
