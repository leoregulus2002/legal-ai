import asyncio
import hashlib
import json
import logging
import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from time import perf_counter
from typing import Literal
from urllib.parse import urlencode, urljoin, urlsplit

import httpx

from app.common.exceptions import AppError
from app.core.logging import redact_log_text
from app.modules.knowledge.metadata import CATEGORY_VALUES
from app.modules.knowledge.schemas import LegalMetadata, LegalStatus, SourceMetadata
from app.modules.public_laws.schemas import (
    DownloadLink,
    DownloadRequest,
    FilterNode,
    PreviewLink,
    PublicLaw,
    PublicLawDetail,
    PublicLawOptions,
    PublicLawPage,
    PublicLawSearch,
)

logger = logging.getLogger(__name__)
OFFICIAL_ORIGIN = "https://flk.npc.gov.cn"
ERROR_BODY_LIMIT = 8192


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parser = PlainText()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts).strip()


def response_diagnostics(
    response: httpx.Response | None, body: bytes | None = None, *, body_complete: bool = True
) -> dict[str, object]:
    if response is None:
        return {"response_received": False}
    details: dict[str, object] = {
        "host": response.url.host,
        "path": response.url.path,
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "content_length": response.headers.get("content-length"),
        "server": response.headers.get("server"),
        "upstream_request_id": response.headers.get("x-request-id")
        or response.headers.get("x-amz-request-id"),
        "retry_after": response.headers.get("retry-after"),
        "location": redact_log_text(response.headers.get("location", "")),
    }
    if body is None:
        return details
    details["captured_bytes"] = len(body)
    details["body_sha256" if body_complete else "body_excerpt_sha256"] = hashlib.sha256(
        body
    ).hexdigest()
    # 只保留可见文字；不把 HTML 脚本、隐藏字段、Cookie 或原件内容写入日志。
    try:
        value = body[: 64 * 1024].decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        value = body[: 64 * 1024].decode("utf-8", errors="replace")
    is_html = "html" in response.headers.get("content-type", "").lower() or bool(
        re.search(r"<(?:!doctype\s+html|html|head|body|script|title)\b", value, flags=re.I)
    )
    content_type = response.headers.get("content-type", "").lower()
    if not is_html and not (
        content_type.startswith("text/") or "json" in content_type or "xml" in content_type
    ):
        details["body_omitted"] = "non_text_response"
        details["body_truncated"] = not body_complete
        return details
    if is_html:
        title = re.search(r"<title\b[^>]*>(.*?)</title\s*>", value, flags=re.I | re.S)
        details["page_title"] = redact_log_text(text(title.group(1)))[:300] if title else None
        markers = (
            "captcha",
            "challenge",
            "安全验证",
            "访问过于频繁",
            "访问异常",
            "人机验证",
            "验证码",
            "访问受限",
            "访问限制",
            "网站防火墙",
            "__jsl",
            "acw_sc__v2",
            "$_ts",
            "access denied",
            'id="app"',
        )
        details["page_markers"] = [marker for marker in markers if marker in value.lower()]
        scripts = re.findall(r"<script\b[^>]*\bsrc=[\"']([^\"']+)", value, flags=re.I)
        script_paths: list[str] = []
        for source in scripts[:8]:
            try:
                script_paths.append(urlsplit(source).path[:200])
            except ValueError:
                script_paths.append("[invalid script URL]")
        details["script_paths"] = script_paths
        value = re.sub(r"<!--.*?-->", " ", value, flags=re.S)
        value = re.sub(
            r"<(script|style|noscript)\b[^>]*>.*?(?:</\1\s*>|$)",
            " ",
            value,
            flags=re.I | re.S,
        )
        value = text(value)
    value = redact_log_text(" ".join(value.split()))
    details["body_excerpt"] = value[:ERROR_BODY_LIMIT]
    details["body_truncated"] = (
        not body_complete or len(body) > 64 * 1024 or len(value) > ERROR_BODY_LIMIT
    )
    return details


def invalid_response(reason: str = "unexpected_structure") -> AppError:
    logger.warning("公开法律库返回数据校验失败 reason=%s", reason)
    return AppError("public_law_response", "公开法律库数据暂时无法读取，请稍后重试", 502)


async def official_request(
    method: Literal["GET", "POST"],
    path: str,
    payload: object = None,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    response: httpx.Response | None = None
    started = perf_counter()
    safe_params = {
        key: value for key, value in (params or {}).items() if key in {"bbbs", "format", "fileId"}
    }
    try:
        async with httpx.AsyncClient(
            base_url=OFFICIAL_ORIGIN,
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            headers={"Accept": "application/json", "Referer": OFFICIAL_ORIGIN + "/"},
        ) as client:
            response = await client.request(method, path, json=payload, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "公开法律库请求失败 method=%s path=%s params=%s type=%s duration_ms=%.1f response=%s",
            method,
            path,
            json.dumps(safe_params, ensure_ascii=False),
            type(exc).__name__,
            (perf_counter() - started) * 1000,
            json.dumps(
                response_diagnostics(response, response.content if response is not None else None),
                ensure_ascii=False,
            ),
            exc_info=exc,
        )
        if isinstance(exc, httpx.TimeoutException):
            raise AppError("public_law_timeout", "公开法律库响应超时，请稍后重试", 504) from exc
        raise AppError("public_law_unavailable", "公开法律库暂时不可用，请稍后重试", 502) from exc
    if not isinstance(data, dict) or data.get("code") != 200:
        logger.warning(
            "公开法律库接口返回异常 method=%s path=%s params=%s code=%s "
            "duration_ms=%.1f response=%s",
            method,
            path,
            json.dumps(safe_params, ensure_ascii=False),
            data.get("code")
            if isinstance(data, dict) and isinstance(data.get("code"), int)
            else None,
            (perf_counter() - started) * 1000,
            json.dumps(response_diagnostics(response, response.content), ensure_ascii=False),
        )
        raise invalid_response("upstream_response")
    return data


def resource_url(value: object, *, preview: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid_response("preview_url_missing" if preview else "download_url_missing")
    if preview:
        value = urljoin(OFFICIAL_ORIGIN + "/", value.strip())
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise invalid_response("resource_url_malformed") from exc
    allowed_hosts = {"flkoss.obs-bj2.cucloud.cn"}
    if preview:
        allowed_hosts.update({"flk.npc.gov.cn", "flkofd.npc.gov.cn"})
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        logger.warning(
            "公开法律库资源地址校验失败 preview=%s scheme=%s host=%s port=%s",
            preview,
            parsed.scheme,
            parsed.hostname,
            port,
        )
        raise invalid_response("resource_url_not_allowed")
    return value


def filter_nodes(value: object, prefix: str) -> list[FilterNode]:
    if not isinstance(value, list):
        raise invalid_response()
    nodes: list[FilterNode] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise invalid_response()
        key = f"{prefix}/{item.get('id', index)}"
        children = filter_nodes(item.get("children") or [], key)
        codes = item.get("codeIdList")
        if not isinstance(codes, list):
            codes = [item["codeId"]] if item.get("codeId") is not None else []
        try:
            code_ids = [int(code) for code in codes]
        except (ValueError, TypeError) as exc:
            raise invalid_response() from exc
        nodes.append(
            FilterNode(
                key=key,
                label=text(item["name"]),
                code_ids=sorted(set(code_ids + [c for child in children for c in child.code_ids])),
                children=children,
            )
        )
    return nodes


async def options() -> PublicLawOptions:
    result = await official_request("GET", "/law-search/search/enumData")
    data = result.get("data")
    if not isinstance(data, dict):
        raise invalid_response()
    categories, authorities = data.get("flfgfl"), data.get("zdjgfl")
    if not isinstance(categories, dict) or not isinstance(authorities, dict):
        raise invalid_response()
    return PublicLawOptions(
        categories=filter_nodes(categories.get("children"), "category"),
        authorities=filter_nodes(authorities.get("children"), "authority"),
    )


def law_item(value: object) -> PublicLaw:
    if not isinstance(value, dict):
        raise invalid_response()
    identifier, title = value.get("bbbs"), text(value.get("title"))
    if not isinstance(identifier, str) or not identifier or not title:
        raise invalid_response()
    category = text(value.get("flxz"))
    query = {"id": identifier}
    if category == "修改、废止的决定":
        query["type"] = "decision"
    raw_status = value.get("sxx")
    status = int(str(raw_status)) if str(raw_status) in {"1", "2", "3", "4"} else None
    return PublicLaw(
        id=identifier,
        title=title,
        published_on=text(value.get("gbrq")) or None,
        effective_on=text(value.get("sxrq")) or None,
        status=status,
        category=category,
        authority=text(value.get("zdjgName")),
        source_url=f"{OFFICIAL_ORIGIN}/detail?{urlencode(query)}",
    )


async def search(query: PublicLawSearch) -> PublicLawPage:
    result = await official_request(
        "POST",
        "/law-search/search/list",
        query.model_dump(mode="json", by_alias=True, exclude={"vectorization", "cursor"}),
    )
    rows, total = result.get("rows"), result.get("total")
    if not isinstance(rows, list) or type(total) is not int or total < 0:
        raise invalid_response()
    search_type = result.get("searchType", query.search_type)
    if search_type not in (1, 2):
        raise invalid_response()
    return PublicLawPage(
        items=[law_item(row) for row in rows],
        total=total,
        page=query.page_num,
        page_size=query.page_size,
        search_type=search_type,
        has_more=query.page_num * query.page_size < total,
    )


async def downloads(query: DownloadRequest) -> list[DownloadLink]:
    result = await official_request(
        "POST",
        "/law-search/download/batch",
        [{"bbbs": identifier, "format": "docx"} for identifier in dict.fromkeys(query.ids)],
    )
    data = result.get("data")
    if not isinstance(data, list) or not data:
        raise invalid_response()
    links: list[DownloadLink] = []
    for item in data:
        links.append(
            DownloadLink(url=resource_url(item.get("url") if isinstance(item, dict) else None))
        )
    return links


async def detail_data(identifier: str, *, decision: bool = False) -> dict[str, object]:
    result = await official_request(
        "GET",
        "/law-search/search/xgwjDetails" if decision else "/law-search/search/flfgDetails",
        params={"bbbs": identifier},
    )
    data = result.get("data")
    if not isinstance(data, dict) or data.get("bbbs") != identifier:
        raise invalid_response("law_detail_structure")
    return data


def preview_files(data: dict[str, object]) -> dict[Literal["docx", "pdf"], str]:
    files = data.get("ossFile")
    if not isinstance(files, dict):
        return {}
    paths: dict[Literal["docx", "pdf"], str] = {}
    fields: tuple[tuple[Literal["docx", "pdf"], str], ...] = (
        ("docx", "ossWordOfdPath"),
        ("pdf", "ossPdfOfdPath"),
    )
    for kind, field in fields:
        path = files.get(field)
        if isinstance(path, str) and path.strip():
            paths[kind] = path
    return paths


async def detail(identifier: str, *, decision: bool = False) -> PublicLawDetail:
    data = await detail_data(identifier, decision=decision)
    law = law_item(data)
    statuses: dict[int, LegalStatus] = {
        1: "REPEALED",
        2: "AMENDED",
        3: "EFFECTIVE",
        4: "NOT_YET_EFFECTIVE",
    }

    def source_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    snapshot = SourceMetadata(
        metadata=LegalMetadata(
            title=law.title,
            authority=law.authority,
            category=CATEGORY_VALUES.get(law.category, "UNCLASSIFIED"),
            promulgated_on=source_date(law.published_on),
            effective_on=source_date(law.effective_on),
        ),
        legal_status=statuses.get(law.status, "UNKNOWN") if law.status is not None else "UNKNOWN",
        source_url=law.source_url,
        fetched_at=datetime.now(UTC),
    )
    return PublicLawDetail(
        **law.model_dump(), preview_formats=list(preview_files(data)), source_metadata=snapshot
    )


async def preview(
    identifier: str, file_format: Literal["docx", "pdf"], *, decision: bool = False
) -> PreviewLink:
    files = preview_files(await detail_data(identifier, decision=decision))
    if file_format not in files:
        raise AppError("public_law_preview_missing", "该法规暂无此版本的预览文件", 404)
    result = await official_request(
        "GET", "/law-search/amazonFile/previewLink", params={"filePath": files[file_format]}
    )
    data = result.get("data")
    return PreviewLink(
        url=resource_url(data.get("url") if isinstance(data, dict) else None, preview=True)
    )


async def download_file(identifier: str, file_format: Literal["docx", "pdf"]) -> bytes:
    result = await official_request(
        "GET",
        "/law-search/download/pc",
        params={"bbbs": identifier, "format": file_format, "fileId": ""},
    )
    data = result.get("data")
    url = resource_url(data.get("url") if isinstance(data, dict) else None)
    response: httpx.Response | None = None
    started = perf_counter()
    received = 0
    error_body: bytes | None = None
    error_body_complete = True
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(45, connect=10), follow_redirects=False
        ) as client:
            async with client.stream("GET", url) as response:
                if not response.is_success:
                    chunks = bytearray()
                    try:
                        async with asyncio.timeout(3):
                            async for chunk in response.aiter_bytes():
                                chunks.extend(chunk[: max(0, ERROR_BODY_LIMIT + 1 - len(chunks))])
                                if len(chunks) > ERROR_BODY_LIMIT:
                                    error_body_complete = False
                                    break
                    except (httpx.HTTPError, TimeoutError) as exc:
                        error_body_complete = False
                        # 诊断正文读取失败不覆盖原来的 HTTP 错误。
                        logger.warning(
                            "公开法律库下载错误响应读取未完成 law_id=%s "
                            "status=%s captured_bytes=%s",
                            identifier,
                            response.status_code,
                            len(chunks),
                            exc_info=exc,
                        )
                    error_body = bytes(chunks)
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    received = len(content)
                    if len(content) > 50 * 1024 * 1024:
                        raise AppError("public_law_file_large", "文件较大，暂时无法下载", 502)
                if not content:
                    raise invalid_response()
                return bytes(content)
    except (httpx.HTTPError, AppError) as exc:
        logger.warning(
            "公开法律库文件下载失败 law_id=%s format=%s url=%s type=%s "
            "duration_ms=%.1f received_bytes=%s response=%s",
            identifier,
            file_format,
            redact_log_text(url),
            type(exc).__name__,
            (perf_counter() - started) * 1000,
            received,
            json.dumps(
                response_diagnostics(
                    response,
                    error_body,
                    body_complete=error_body_complete,
                ),
                ensure_ascii=False,
            ),
            exc_info=exc,
        )
        if isinstance(exc, AppError):
            raise
        if isinstance(exc, httpx.TimeoutException):
            raise AppError("public_law_timeout", "文件下载超时，请稍后重试", 504) from exc
        raise AppError("public_law_download_failed", "文件暂时无法下载，请稍后重试", 502) from exc
