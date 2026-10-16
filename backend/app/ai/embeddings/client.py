import asyncio
import hashlib
import json
import logging
import math
from array import array
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.ai.providers.client import diagnostic_identifier, estimate_text_tokens
from app.common.exceptions import AppError

EmbeddingProtocol = Literal["openai_embeddings", "dashscope_embeddings"]
EmbeddingPurpose = Literal["document", "query"]
DASHSCOPE_PATH = "/services/embeddings/text-embedding/text-embedding"
logger = logging.getLogger(__name__)


class EmbeddingItem(BaseModel):
    index: int = Field(ge=0)
    embedding: list[float] = Field(min_length=1, max_length=4096)


class EmbeddingResponse(BaseModel):
    data: list[EmbeddingItem] = Field(min_length=1, max_length=32)


class DashScopeEmbeddingItem(BaseModel):
    text_index: int = Field(ge=0)
    embedding: list[float] = Field(min_length=1, max_length=4096)


class DashScopeOutput(BaseModel):
    embeddings: list[DashScopeEmbeddingItem] = Field(min_length=1, max_length=32)


class DashScopeResponse(BaseModel):
    output: DashScopeOutput
    code: str | None = None
    status_code: int | None = None


@dataclass(frozen=True)
class EmbeddingProvider:
    base_url: str
    model_name: str
    api_key: str
    protocol: EmbeddingProtocol = "openai_embeddings"
    dimensions: int | None = None
    batch_size: int = 8
    timeout: int = 90
    max_input_tokens: int = 32000
    query_instruction: str = ""

    @property
    def endpoint(self) -> str:
        base = self.base_url.strip().rstrip("/")
        url = urlsplit(base)
        hostname = url.hostname or ""
        is_dashscope_host = hostname in {
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "dashscope-us.aliyuncs.com",
        } or hostname.endswith(".maas.aliyuncs.com")
        # 百炼的两种地址按所选协议双向适配；保留业务空间、地域及原始配置。
        if is_dashscope_host and url.path in {
            "",
            "/api/v1",
            "/api/v1" + DASHSCOPE_PATH,
            "/compatible-mode/v1",
            "/compatible-mode/v1/embeddings",
        }:
            target = "/api/v1" if self.protocol == "dashscope_embeddings" else "/compatible-mode/v1"
            base = url._replace(path=target).geturl()
        path = DASHSCOPE_PATH if self.protocol == "dashscope_embeddings" else "/embeddings"
        return base if base.endswith(path) else base + path

    @property
    def fingerprint(self) -> str:
        # 保留既有 OpenAI 默认配置的指纹；影响向量语义的配置独立编码。
        path = DASHSCOPE_PATH if self.protocol == "dashscope_embeddings" else "/embeddings"
        base = self.endpoint.removesuffix(path)
        values: list[object] = [base, self.model_name]
        if (
            self.protocol != "openai_embeddings"
            or self.dimensions is not None
            or self.query_instruction
        ):
            values.append(
                {
                    "protocol": self.protocol,
                    "dimensions": self.dimensions,
                    "query_instruction": self.query_instruction,
                }
            )
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def provider_error(self, response: httpx.Response, details: dict[str, object]) -> AppError:
        error = details.get("error")
        code = diagnostic_identifier(
            error.get("code") if isinstance(error, dict) else details.get("code"), self.api_key
        )
        request_id = next(
            (
                identifier
                for value in (
                    response.headers.get("x-request-id"),
                    response.headers.get("x-acs-request-id"),
                    response.headers.get("request-id"),
                    details.get("request_id"),
                )
                if (identifier := diagnostic_identifier(value, self.api_key))
            ),
            None,
        )
        status = response.status_code
        logger.warning(
            "向量服务请求被拒绝 status=%d protocol=%s provider_code=%s provider_request_id=%s",
            status,
            self.protocol,
            code or "unknown",
            request_id or "unknown",
        )
        normalized_code = (code or "").lower()
        if status == 401 or normalized_code in {"invalidapikey", "invalid_api_key"}:
            return AppError(
                "embedding_authentication_failed",
                "向量服务认证失败，请重新填写对应地域、业务空间的 API Key",
                502,
            )
        if status == 402 or normalized_code in {"arrearage", "insufficient_quota"}:
            return AppError(
                "embedding_quota_exhausted", "向量服务额度不足，请检查账户余额及可用额度", 502
            )
        messages = {
            400: ("parameters", "向量服务不接受当前参数，请检查模型标识、向量维度和每批文本数量"),
            403: ("access_denied", "向量服务拒绝访问，请检查模型授权、业务空间及地域配置"),
            404: ("not_found", "向量接口或模型不存在，请检查接口地址、协议和模型标识"),
            405: ("endpoint", "向量接口不接受请求，请检查接口地址和协议"),
            408: ("timeout", "向量服务请求超时，请稍后重试或调整请求超时"),
            413: ("input_limit", "向量请求内容过大，请减小每批文本数量或文档切分长度"),
            422: ("parameters", "向量服务不接受当前参数，请检查模型标识、向量维度和每批文本数量"),
            429: ("rate_limited", "向量服务请求频率或 Token 用量超限，请稍后重试或减小批次"),
            504: ("timeout", "向量服务请求超时，请稍后重试或调整请求超时"),
        }
        if status in messages:
            reason, message = messages[status]
            return AppError(f"embedding_{reason}", message, 502)
        if 300 <= status < 400:
            return AppError("embedding_endpoint", "向量地址发生跳转，请填写最终接口地址", 502)
        if status >= 500:
            return AppError("embedding_unavailable", "向量服务暂不可用，请稍后重试", 502)
        return AppError(
            "embedding_provider", "向量服务拒绝请求，请检查模型配置或联系服务提供方", 502
        )

    async def http_error(self, response: httpx.Response) -> AppError:
        details: dict[str, object] = {}
        body = bytearray()
        try:
            async for chunk in response.aiter_bytes(chunk_size=1024):
                if len(body) + len(chunk) > 16_384:
                    break
                body.extend(chunk)
            else:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    details = parsed
        except (httpx.HTTPError, ValueError, RecursionError):
            pass
        return self.provider_error(response, details)

    async def embed(
        self, texts: list[str], *, purpose: EmbeddingPurpose = "document"
    ) -> list[list[float]]:
        if not texts or len(texts) > self.batch_size:
            raise AppError("embedding_batch_size", "向量化批次超过模型配置上限，请减小批次大小")
        if any(
            not text.strip() or estimate_text_tokens(text) > self.max_input_tokens for text in texts
        ):
            raise AppError(
                "embedding_input_limit", "文本为空或超出向量模型输入上限，请调整文档切分或输入内容"
            )
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        if self.protocol == "dashscope_embeddings":
            parameters: dict[str, object] = {"text_type": purpose}
            if self.dimensions is not None:
                parameters["dimension"] = self.dimensions
            if purpose == "query" and self.query_instruction:
                parameters["instruct"] = self.query_instruction
            payload: dict[str, object] = {
                "model": self.model_name,
                "input": {"texts": texts},
                "parameters": parameters,
            }
        else:
            payload = {"model": self.model_name, "input": texts, "encoding_format": "float"}
            if self.dimensions is not None:
                payload["dimensions"] = self.dimensions
        try:
            async with (
                asyncio.timeout(self.timeout + 10),
                httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client,
            ):
                async with client.stream(
                    "POST", self.endpoint, headers=headers, json=payload
                ) as response:
                    if response.status_code >= 300:
                        raise await self.http_error(response)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 8_000_000:
                            raise ValueError("embedding response too large")
            parsed = json.loads(body)
            if isinstance(parsed, dict) and (parsed.get("code") or parsed.get("error")):
                raise self.provider_error(response, parsed)
            if self.protocol == "dashscope_embeddings":
                result = DashScopeResponse.model_validate_json(bytes(body))
                if result.code or result.status_code not in {None, 200}:
                    raise ValueError("dashscope error response")
                ordered = sorted(
                    (
                        EmbeddingItem(index=item.text_index, embedding=item.embedding)
                        for item in result.output.embeddings
                    ),
                    key=lambda item: item.index,
                )
            else:
                ordered = sorted(
                    EmbeddingResponse.model_validate_json(bytes(body)).data,
                    key=lambda item: item.index,
                )
            if [item.index for item in ordered] != list(range(len(texts))):
                raise ValueError("embedding indices")
            dimensions = len(ordered[0].embedding)
            if self.dimensions is not None and dimensions != self.dimensions:
                raise ValueError("embedding dimensions do not match configuration")
            vectors: list[list[float]] = []
            for item in ordered:
                vector = list(array("f", item.embedding))
                if (
                    len(vector) != dimensions
                    or not all(math.isfinite(value) for value in vector)
                    or not any(vector)
                ):
                    raise ValueError("invalid vector")
                vectors.append(vector)
            return vectors
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AppError(
                "embedding_timeout", "向量服务请求超时，请稍后重试或调整请求超时", 502
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "embedding_connection", "无法连接向量服务，请检查接口地址或网络后重试", 502
            ) from exc
        except (ValidationError, ValueError, OverflowError, RecursionError) as exc:
            logger.warning(
                "向量响应校验失败 protocol=%s type=%s", self.protocol, type(exc).__name__
            )
            raise AppError("embedding_failed", "向量化未完成，请检查模型配置并重试", 502) from exc
