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
from app.modules.public_laws.diagnostics import EVIDENCE_BODY_LIMIT, preserve_evidence
from app.modules.public_laws.http_client import (
    FILE_HOST,
    OFFICIAL_ORIGIN,
    OfficialLawClient,
    OfficialLawRedirectError,
)
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


def log_excerpt(value: str, size: int) -> str:
    return redact_log_text(value).encode("utf-8")[:size].decode("utf-8", errors="ignore")


def diagnostic_headers(headers: httpx.Headers) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, value in list(headers.multi_items())[:32]:
        if re.search(
            r"authorization|cookie|token|secret|api[-_]?key|signature|credential", name, re.I
        ):
            values[name] = "[REDACTED]"
        else:
            values[name] = log_excerpt(value, 256)
    return values


def response_diagnostics(
    response: httpx.Response | None, body: bytes | None = None, *, body_complete: bool = True
) -> dict[str, object]:
    if response is None:
        return {"response_received": False}
    details: dict[str, object] = {
        "host": response.url.host,
        "path": response.url.path,
        "request_method": response.request.method,
        "request_url": redact_log_text(str(response.request.url)),
        "request_headers": diagnostic_headers(response.request.headers),
        "response_headers": diagnostic_headers(response.headers),
        "response_header_count": len(response.headers.multi_items()),
        "request_header_count": len(response.request.headers.multi_items()),
        "headers_truncated": (
            len(response.headers.multi_items()) > 32
            or len(response.request.headers.multi_items()) > 32
        ),
        "http_version": response.http_version,
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "content_encoding": response.headers.get("content-encoding"),
        "charset_encoding": response.charset_encoding,
        "text_encoding": response.encoding,
        "content_length": response.headers.get("content-length"),
        "server": response.headers.get("server"),
        "upstream_request_id": response.headers.get("x-request-id")
        or response.headers.get("x-amz-request-id"),
        "retry_after": response.headers.get("retry-after"),
        "location": redact_log_text(response.headers.get("location", "")),
        "set_cookie_names": [
            value.partition("=")[0].strip()[:100]
            for value in response.headers.get_list("set-cookie")[:16]
        ],
    }
    if body is None:
        return details
    details["captured_bytes"] = len(body)
    details["body_prefix_hex"] = body[:16].hex()
    signatures = (
        (b"\x1f\x8b", "gzip"),
        (b"PK\x03\x04", "zip"),
        (b"\xff\xfe", "utf16_le_bom"),
        (b"\xfe\xff", "utf16_be_bom"),
        (b"\xef\xbb\xbf", "utf8_bom"),
    )
    details["body_signature"] = next(
        (name for prefix, name in signatures if body.startswith(prefix)), "unrecognized"
    )
    details["body_sha256" if body_complete else "body_excerpt_sha256"] = hashlib.sha256(
        body
    ).hexdigest()
    # 同时保留脱敏原文和可见文字；完整原文另行加密保存，不再因过滤脚本丢失证据。
    try:
        value = body[: 64 * 1024].decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        value = body[: 64 * 1024].decode("utf-8", errors="replace")
    details["decode_replacement_count"] = value.count("\ufffd")
    details["decoded_nul_count"] = value.count("\x00")
    details["inspected_body_bytes"] = min(len(body), 64 * 1024)
    details["raw_tail_excerpt_source"] = "end_of_inspected_prefix"
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
    raw_redacted = re.sub(
        r"(?is)(<input\b[^>]*?\bvalue\s*=\s*)([\"'])(.*?)\2",
        r"\1\2[REDACTED]\2",
        redact_log_text(value),
    )
    # 过长的混淆字面量只保留代码形状；加密证据中仍保存原始字节。
    raw_redacted = re.sub(
        r"([\"'])[^\"'\r\n]{160,}\1", r"\1[LONG_LITERAL_IN_ENCRYPTED_EVIDENCE]\1", raw_redacted
    )
    details["raw_excerpt"] = log_excerpt(raw_redacted, 4096)
    details["raw_tail_excerpt"] = log_excerpt(raw_redacted[-2048:], 2048)
    details["raw_excerpt_truncated"] = len(raw_redacted.encode("utf-8")) > 4096
    details["first_non_whitespace_character"] = value.lstrip()[:1]
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
            "document.cookie",
            "window.location",
            "location.href",
            "string.fromcharcode",
            "eval(",
            "atob(",
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
        script_count = len(re.findall(r"<script\b", value, flags=re.I))
        details["script_count"] = script_count
        details["inline_script_count"] = max(0, script_count - len(scripts))
        value = re.sub(r"<!--.*?-->", " ", value, flags=re.S)
        value = re.sub(
            r"<(script|style|noscript)\b[^>]*>.*?(?:</\1\s*>|$)",
            " ",
            value,
            flags=re.I | re.S,
        )
        value = text(value)
    value = redact_log_text(" ".join(value.split()))
    details["body_excerpt"] = log_excerpt(value, ERROR_BODY_LIMIT)
    details["visible_text_empty"] = not bool(value)
    if is_html:
        details["page_kind"] = (
            "script_only_html" if not value and details["script_count"] else "html"
        )
    details["body_truncated"] = (
        not body_complete or len(body) > 64 * 1024 or len(value.encode("utf-8")) > ERROR_BODY_LIMIT
    )
    return details


async def failure_diagnostics(
    response: httpx.Response | None, body: bytes | None = None, *, body_complete: bool = True
) -> dict[str, object]:
    try:
        details = response_diagnostics(response, body, body_complete=body_complete)
    except Exception as exc:
        logger.warning("公开法律库响应诊断字段提取失败 type=%s", type(exc).__name__, exc_info=exc)
        details = {
            "status": response.status_code if response is not None else None,
            "diagnostic_error": type(exc).__name__,
        }
    details.update(await preserve_evidence(body, details, body_complete=body_complete))
    return details


def invalid_response(reason: str = "unexpected_structure") -> AppError:
    logger.warning("公开法律库返回数据校验失败 reason=%s", reason)
    return AppError("public_law_response", "公开法律库数据暂时无法读取，请稍后重试", 502)


async def official_request(
    method: Literal["GET", "POST"],
    path: str,
    payload: object = None,
    *,
    client: OfficialLawClient,
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    response: httpx.Response | None = None
    started = perf_counter()
    safe_params = {
        key: value for key, value in (params or {}).items() if key in {"bbbs", "format", "fileId"}
    }
    try:
        response = await client.request(method, path, payload, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
        duration_ms = (perf_counter() - started) * 1000
        diagnostics = await failure_diagnostics(
            response,
            exc.body
            if isinstance(exc, OfficialLawRedirectError)
            else response.content
            if response is not None
            else None,
            body_complete=exc.body_complete if isinstance(exc, OfficialLawRedirectError) else True,
        )
        logger.warning(
            "公开法律库请求失败 method=%s path=%s params=%s type=%s duration_ms=%.1f response=%s",
            method,
            path,
            json.dumps(safe_params, ensure_ascii=False),
            type(exc).__name__,
            duration_ms,
            json.dumps(diagnostics, ensure_ascii=False),
            exc_info=exc,
        )
        if isinstance(exc, httpx.TimeoutException):
            raise AppError("public_law_timeout", "公开法律库响应超时，请稍后重试", 504) from exc
        raise AppError("public_law_unavailable", "公开法律库暂时不可用，请稍后重试", 502) from exc
    if not isinstance(data, dict) or data.get("code") != 200:
        duration_ms = (perf_counter() - started) * 1000
        diagnostics = await failure_diagnostics(response, response.content)
        logger.warning(
            "公开法律库接口返回异常 method=%s path=%s params=%s code=%s "
            "duration_ms=%.1f response=%s",
            method,
            path,
            json.dumps(safe_params, ensure_ascii=False),
            data.get("code")
            if isinstance(data, dict) and isinstance(data.get("code"), int)
            else None,
            duration_ms,
            json.dumps(diagnostics, ensure_ascii=False),
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
    allowed_hosts = {FILE_HOST}
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


async def options(*, client: OfficialLawClient) -> PublicLawOptions:
    result = await official_request("GET", "/law-search/search/enumData", client=client)
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


async def search(query: PublicLawSearch, *, client: OfficialLawClient) -> PublicLawPage:
    result = await official_request(
        "POST",
        "/law-search/search/list",
        query.model_dump(mode="json", by_alias=True, exclude={"vectorization", "cursor"}),
        client=client,
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


async def downloads(query: DownloadRequest, *, client: OfficialLawClient) -> list[DownloadLink]:
    result = await official_request(
        "POST",
        "/law-search/download/batch",
        [{"bbbs": identifier, "format": "docx"} for identifier in dict.fromkeys(query.ids)],
        client=client,
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


async def detail_data(
    identifier: str, *, client: OfficialLawClient, decision: bool = False
) -> dict[str, object]:
    result = await official_request(
        "GET",
        "/law-search/search/xgwjDetails" if decision else "/law-search/search/flfgDetails",
        params={"bbbs": identifier},
        client=client,
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


async def detail(
    identifier: str, *, client: OfficialLawClient, decision: bool = False
) -> PublicLawDetail:
    data = await detail_data(identifier, client=client, decision=decision)
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
    identifier: str,
    file_format: Literal["docx", "pdf"],
    *,
    client: OfficialLawClient,
    decision: bool = False,
) -> PreviewLink:
    files = preview_files(await detail_data(identifier, client=client, decision=decision))
    if file_format not in files:
        raise AppError("public_law_preview_missing", "该法规暂无此版本的预览文件", 404)
    result = await official_request(
        "GET",
        "/law-search/amazonFile/previewLink",
        params={"filePath": files[file_format]},
        client=client,
    )
    data = result.get("data")
    return PreviewLink(
        url=resource_url(data.get("url") if isinstance(data, dict) else None, preview=True)
    )


async def download_file(
    identifier: str, file_format: Literal["docx", "pdf"], *, client: OfficialLawClient
) -> bytes:
    result = await official_request(
        "GET",
        "/law-search/download/pc",
        params={"bbbs": identifier, "format": file_format, "fileId": ""},
        client=client,
    )
    data = result.get("data")
    url = resource_url(data.get("url") if isinstance(data, dict) else None)
    response: httpx.Response | None = None
    started = perf_counter()
    received = 0
    error_body: bytes | None = None
    error_body_complete = True
    try:
        async with client.stream("GET", url, download=True) as response:
            if not response.is_success:
                chunks = bytearray()
                try:
                    async with asyncio.timeout(3):
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk[: max(0, EVIDENCE_BODY_LIMIT + 1 - len(chunks))])
                            if len(chunks) > EVIDENCE_BODY_LIMIT:
                                error_body_complete = False
                                break
                except (httpx.HTTPError, TimeoutError) as exc:
                    error_body_complete = False
                    # 诊断正文读取失败不覆盖原来的 HTTP 错误。
                    logger.warning(
                        "公开法律库下载错误响应读取未完成 law_id=%s status=%s captured_bytes=%s",
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
    except (httpx.HTTPError, httpx.InvalidURL, AppError) as exc:
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
        if isinstance(exc, OfficialLawRedirectError):
            error_body = exc.body
            error_body_complete = exc.body_complete
        duration_ms = (perf_counter() - started) * 1000
        diagnostics = await failure_diagnostics(
            response, error_body, body_complete=error_body_complete
        )
        logger.warning(
            "公开法律库文件下载失败 law_id=%s format=%s url=%s type=%s "
            "duration_ms=%.1f received_bytes=%s response=%s",
            identifier,
            file_format,
            redact_log_text(url),
            type(exc).__name__,
            duration_ms,
            received,
            json.dumps(diagnostics, ensure_ascii=False),
            exc_info=exc,
        )
        if isinstance(exc, AppError):
            raise
        if isinstance(exc, httpx.TimeoutException):
            raise AppError("public_law_timeout", "文件下载超时，请稍后重试", 504) from exc
        raise AppError("public_law_download_failed", "文件暂时无法下载，请稍后重试", 502) from exc
