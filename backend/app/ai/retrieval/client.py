from typing import Literal

from pydantic import BaseModel, Field


class Source(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=12000)
    source: str = Field(max_length=2000)
    score: float = Field(ge=0, le=1)


class InternalSource(Source):
    # 内部检索的分数来源与排名独立记录；历史来源仍兼容基础 Source 字段。
    score_type: Literal["cosine", "keyword_coverage"] | None = None
    fusion_score: float | None = None
    bm25_score: float | None = None
    cosine_score: float | None = None
    keyword_coverage: float | None = None
    lexical_rank: int | None = None
    vector_rank: int | None = None
    retrieval_method: Literal["hybrid", "keyword"] | None = None
