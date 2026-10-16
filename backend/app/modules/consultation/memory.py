import hashlib
import json
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.common.exceptions import AppError
from app.modules.consultation.schemas import Memory
from app.modules.system_config.schemas import Policy

WRITE_MEMORY = """
local old = redis.call('GET', KEYS[1])
if old then
  local ok, parsed = pcall(cjson.decode, old)
  if ok and parsed.history_version > tonumber(ARGV[2]) then return 0 end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3])
return 1
"""


def policy_version(policy: Policy) -> str:
    # 压缩策略变化后从完整历史重建，避免旧滑动窗口快照错开批次边界。
    values = ["batch-v1", policy.recent_turns, policy.summary_chars, policy.keyword_count]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()[:16]


class MemoryStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(conversation_id: UUID) -> str:
        return f"legal-ai:consultation:{conversation_id}:memory"

    async def read(self, conversation_id: UUID, ttl: int) -> Memory | None:
        try:
            pipe = self.redis.pipeline(transaction=True)
            pipe.get(self.key(conversation_id))
            pipe.expire(self.key(conversation_id), ttl)
            raw, _ = await pipe.execute()
            if not raw:
                return None
            try:
                return Memory.model_validate_json(raw)
            except ValidationError:
                return None
        except (RedisError, OSError) as exc:
            raise AppError("memory_unavailable", "记忆服务暂不可用，请稍后重试", 503) from exc

    async def write(self, conversation_id: UUID, memory: Memory, ttl: int) -> bool:
        try:
            return bool(
                await self.redis.eval(
                    WRITE_MEMORY,
                    1,
                    self.key(conversation_id),
                    memory.model_dump_json(),
                    memory.history_version,
                    ttl,
                )
            )
        except (RedisError, OSError) as exc:
            raise AppError("memory_unavailable", "记忆服务暂不可用，请稍后重试", 503) from exc

    async def delete(self, conversation_id: UUID) -> None:
        await self.redis.delete(self.key(conversation_id))
