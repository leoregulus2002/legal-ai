import httpx
from pydantic import BaseModel, Field, ValidationError

from app.common.exceptions import AppError
from app.modules.system_config.schemas import Policy


class Source(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=12000)
    source: str = Field(max_length=2000)
    score: float = Field(ge=0, le=1)


class RetrievalResponse(BaseModel):
    matches: list[Source] = Field(max_length=100)


async def retrieve(
    query: str, summary: str, keywords: list[str], policy: Policy, api_key: str
) -> list[Source]:
    if not policy.knowledge_url:
        return []
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(
            timeout=policy.knowledge_timeout, follow_redirects=False
        ) as client:
            async with client.stream(
                "POST",
                policy.knowledge_url,
                headers=headers,
                json={
                    "query": query,
                    "history_summary": summary,
                    "keywords": keywords,
                    "limit": policy.knowledge_limit,
                },
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise ValueError
        result = RetrievalResponse.model_validate_json(bytes(body))
        return sorted(
            (source for source in result.matches if source.score >= policy.knowledge_threshold),
            key=lambda source: source.score,
            reverse=True,
        )[: policy.knowledge_limit]
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        raise AppError("knowledge_unavailable", "知识库暂时不可用，请稍后重试", 502) from exc
