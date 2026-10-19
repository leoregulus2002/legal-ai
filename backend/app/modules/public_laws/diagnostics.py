import base64
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import time
from uuid import uuid4

import anyio

from app.core.config import get_settings
from app.core.logging import current_log_context
from app.core.secrets import cipher

logger = logging.getLogger(__name__)
EVIDENCE_BODY_LIMIT = 256 * 1024
EVIDENCE_MAX_FILES = 200
EVIDENCE_RETENTION_SECONDS = 7 * 24 * 60 * 60


def write_evidence(
    body: bytes, metadata: dict[str, object], body_complete: bool
) -> dict[str, object]:
    settings = get_settings()
    identifier = uuid4().hex
    captured = body[:EVIDENCE_BODY_LIMIT]
    payload = {
        "version": 1,
        "evidence_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "metadata": metadata,
        "body_base64": base64.b64encode(captured).decode("ascii"),
        "body_bytes": len(body),
        "captured_bytes": len(captured),
        "body_complete": body_complete and len(body) <= EVIDENCE_BODY_LIMIT,
        "body_source": "httpx.content_after_http_content_decoding",
    }
    # 使用已有配置主密钥加密，原始脚本和响应正文均不进入明文日志或公共下载接口。
    encrypted = cipher(settings).encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    directory = Path(settings.diagnostic_directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    destination = directory / f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{identifier}.fernet"
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".evidence-", dir=directory)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encrypted)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)

    cleanup_failed = False
    try:
        snapshots: list[tuple[float, Path]] = []
        cutoff = time() - EVIDENCE_RETENTION_SECONDS
        for path in directory.glob(".evidence-*"):
            try:
                if path.stat().st_mtime < time() - 24 * 60 * 60:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
        for path in directory.glob("*.fernet"):
            try:
                modified = path.stat().st_mtime
                if modified < cutoff:
                    path.unlink(missing_ok=True)
                else:
                    snapshots.append((modified, path))
            except FileNotFoundError:
                continue
        for _, path in sorted(snapshots, reverse=True)[EVIDENCE_MAX_FILES:]:
            path.unlink(missing_ok=True)
    except OSError:
        cleanup_failed = True
        logger.warning("公开法律库异常证据清理失败 directory=%s", directory, exc_info=True)
    return {
        "evidence_id": identifier,
        "evidence_path": str(destination),
        "evidence_encrypted": True,
        "evidence_captured_bytes": len(captured),
        "evidence_complete": payload["body_complete"],
        "evidence_cleanup_failed": cleanup_failed,
    }


async def preserve_evidence(
    body: bytes | None, metadata: dict[str, object], *, body_complete: bool = True
) -> dict[str, object]:
    if body is None:
        return {"evidence_saved": False, "evidence_reason": "no_response_body"}
    try:
        return {
            "evidence_saved": True,
            **await anyio.to_thread.run_sync(
                write_evidence,
                body,
                {**metadata, "context": current_log_context()},
                body_complete,
            ),
        }
    except Exception as exc:
        # 诊断存储失败不能掩盖原有请求失败，也不能影响已完成业务数据。
        logger.warning("公开法律库异常证据保存失败 type=%s", type(exc).__name__, exc_info=exc)
        return {"evidence_saved": False, "evidence_error": type(exc).__name__}
