import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings

logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self, settings: Settings) -> None:
        self.client: Redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    async def initialize(self) -> None:
        try:
            await self.ping()
        except (RedisError, OSError):
            # 允许进程启动，readiness 会准确报告依赖不可用；不记录含凭据异常文本。
            logger.warning("Redis 暂不可用，请检查连接配置及服务；readiness 将返回失败")

    async def ping(self) -> None:
        await self.client.ping()

    async def close(self) -> None:
        await self.client.aclose()
