import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID

import anyio
from psycopg import AsyncConnection, sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.tools.mcp import MCPConnection, validated_url
from app.ai.tools.types import TOOL_NAME
from app.common.exceptions import AppError
from app.core.config import Settings
from app.core.logging import log_context
from app.core.secrets import decrypt, encrypt
from app.modules.document_analysis.models import (
    AnalysisDocument,
    AnalysisMCPServer,
    AnalysisRun,
    AnalysisWorkspace,
)
from app.modules.document_analysis.repository import AnalysisRepository
from app.modules.document_analysis.schemas import (
    ROLE_LABELS,
    AnalysisConfig,
    AnalysisRole,
    DocumentDetail,
    DocumentKind,
    DocumentUpdate,
    DocumentView,
    MCPServerInput,
    MCPServerView,
    PromptSnapshot,
    RunInput,
    RunView,
    StepView,
    ToolCallView,
    WorkspaceInput,
    WorkspaceView,
)
from app.modules.files.repository import FileRepository
from app.modules.files.schemas import GeneratedFileView
from app.modules.knowledge.extraction import MEDIA_TYPES, extract
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.system_config.repository import ConfigRepository
from app.modules.system_config.schemas import Policy

logger = logging.getLogger(__name__)


def infer_kind(text: str, filename: str) -> DocumentKind:
    sample = filename + "\n" + text[:5000]
    if any(word in sample for word in ("判决书", "裁定书", "本院认为", "判决如下")):
        return "judgment"
    if any(
        word in sample for word in ("起诉状", "答辩状", "上诉状", "代理词", "诉讼请求", "证据目录")
    ):
        return "litigation"
    if any(word in sample for word in ("合同", "协议", "甲方", "乙方")):
        return "contract"
    return "other"


class AnalysisService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings

    @staticmethod
    async def resolve_prompts(
        config: AnalysisConfig, repository: ConfigRepository
    ) -> dict[AnalysisRole, PromptSnapshot]:
        snapshots: dict[AnalysisRole, PromptSnapshot] = {}
        for role, label in ROLE_LABELS.items():
            agent = config.agent_configs.get(role)
            if agent is None or agent.prompt_id is None:
                raise AppError("analysis_prompt_unconfigured", f"请为{label}选择系统提示词")
            prompt = await repository.prompt(agent.prompt_id)
            if prompt is None or not prompt.enabled or not prompt.content.strip():
                raise AppError("invalid_analysis_prompt", f"请为{label}选择已启用的有效系统提示词")
            snapshots[role] = PromptSnapshot(
                id=prompt.id, name=prompt.name, version=prompt.version, content=prompt.content
            )
        return snapshots

    @staticmethod
    async def require_workspace(
        repo: AnalysisRepository, workspace_id: UUID, *, lock: bool = False
    ) -> AnalysisWorkspace:
        row = await repo.workspace(workspace_id, lock=lock)
        if row is None:
            raise AppError("workspace_not_found", "分析工作区不存在", 404)
        return row

    @staticmethod
    async def require_run(
        repo: AnalysisRepository, workspace_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AnalysisRun:
        row = await repo.run(workspace_id, run_id, lock=lock)
        if row is None:
            raise AppError("analysis_not_found", "分析任务不存在", 404)
        return row

    async def options(self) -> dict[str, object]:
        async with self.sessions() as session:
            models = await ConfigRepository(session).models()
            bases, _ = await KnowledgeRepository(session).bases("", 1, 1000)
            repo = AnalysisRepository(session)
            return {
                "models": [
                    {"id": str(row.id), "name": row.name, "supports_tools": row.supports_tools}
                    for row in models
                    if row.enabled and row.model_type == "chat"
                ],
                "knowledge_bases": [{"id": str(row.id), "name": row.name} for row in bases],
                "mcp_servers": [
                    self.server_view(row).model_dump(mode="json") for row in await repo.servers()
                ],
                "config": AnalysisConfig.model_validate(
                    (await repo.settings()).settings
                ).model_dump(mode="json"),
            }

    async def workspaces(self) -> list[WorkspaceView]:
        async with self.sessions() as session:
            return [
                WorkspaceView.model_validate(row)
                for row in await AnalysisRepository(session).workspaces()
            ]

    async def save_workspace(
        self, data: WorkspaceInput, workspace_id: UUID | None = None
    ) -> WorkspaceView:
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            row = (
                await self.require_workspace(repo, workspace_id, lock=True)
                if workspace_id
                else AnalysisWorkspace()
            )
            row.name, row.updated_at = data.name, datetime.now(UTC)
            session.add(row)
            await session.flush()
            return WorkspaceView.model_validate(row)

    async def delete_workspace(self, workspace_id: UUID) -> None:
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            row = await self.require_workspace(repo, workspace_id, lock=True)
            if await repo.active(workspace_id):
                raise AppError("analysis_busy", "请先停止正在进行的分析", 409)
            await session.delete(row)

    async def documents(self, workspace_id: UUID) -> list[DocumentView]:
        async with self.sessions() as session:
            repo = AnalysisRepository(session)
            await self.require_workspace(repo, workspace_id)
            return [DocumentView.model_validate(row) for row in await repo.documents(workspace_id)]

    async def upload(
        self, workspace_id: UUID, filename: str, content: bytes, request_id: str | None
    ) -> DocumentView:
        safe_name = Path(filename).name[:200]
        suffix = Path(safe_name).suffix.lower()
        if suffix not in MEDIA_TYPES:
            raise AppError("unsupported_document", "请上传 PDF、Word 或文本格式文书")
        async with self.sessions() as session:
            await self.require_workspace(AnalysisRepository(session), workspace_id)
        started = perf_counter()
        try:
            with log_context(analysis_workspace_id=str(workspace_id), stage="document_extract"):
                async with asyncio.timeout(120):
                    extracted = await anyio.to_thread.run_sync(
                        extract,
                        safe_name,
                        content,
                        self.settings.word_extractor_path,
                        self.settings.word_converter_path,
                        abandon_on_cancel=True,
                    )
        except Exception as exc:
            logger.error(
                "文书提取失败 workspace_id=%s request_id=%s stage=extract "
                "bytes=%s suffix=%s duration_ms=%.1f",
                workspace_id,
                request_id,
                len(content),
                suffix,
                (perf_counter() - started) * 1000,
                exc_info=exc,
            )
            if isinstance(exc, AppError):
                raise
            raise AppError("document_parse_failed", "文书无法解析，请确认文件完整且未加密") from exc
        spans: list[dict[str, object]] = []
        # 长页拆分为稳定的原文片段，避免单页超出模型和工具预算。
        for span in extracted.spans:
            for start in range(span.start, span.end, 1000):
                spans.append(
                    {
                        "id": f"s{len(spans) + 1}",
                        "kind": span.kind,
                        "index": span.index,
                        "start": start,
                        "end": min(start + 1000, span.end),
                    }
                )
        needs_ocr = (
            any(
                issue.code in {"ocr_required", "page_failed", "docx_embedded"}
                for issue in extracted.issues
            )
            or not extracted.text.strip()
        )
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            workspace = await self.require_workspace(repo, workspace_id, lock=True)
            if len(await repo.documents(workspace_id)) >= 100:
                raise AppError("too_many_documents", "每个工作区最多保存 100 份文书")
            row = AnalysisDocument(
                workspace_id=workspace_id,
                filename=safe_name,
                mime_type=MEDIA_TYPES[suffix],
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                revision=1,
                kind=infer_kind(extracted.text, safe_name),
                status="needs_ocr" if needs_ocr else "ready",
                character_count=len(extracted.text),
                original=content,
                text=extracted.text,
                spans=spans,
                deleted=False,
            )
            session.add(row)
            workspace.updated_at = datetime.now(UTC)
            await session.flush()
            return DocumentView.model_validate(row)

    async def document(self, workspace_id: UUID, document_id: UUID) -> DocumentDetail:
        async with self.sessions() as session:
            row = await AnalysisRepository(session).document(workspace_id, document_id)
            if row is None:
                raise AppError("document_not_found", "文书不存在", 404)
            return DocumentDetail.model_validate(row)

    async def original(self, workspace_id: UUID, document_id: UUID) -> tuple[bytes, str, str]:
        async with self.sessions() as session:
            row = await AnalysisRepository(session).document(
                workspace_id, document_id, original=True
            )
            if row is None:
                raise AppError("document_not_found", "文书不存在", 404)
            return row.original, row.mime_type, row.filename

    async def update_document(
        self, workspace_id: UUID, document_id: UUID, data: DocumentUpdate | None
    ) -> DocumentView:
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            await self.require_workspace(repo, workspace_id, lock=True)
            row = await repo.document(workspace_id, document_id)
            if row is None or row.deleted:
                raise AppError("document_not_found", "文书不存在", 404)
            if data:
                row.kind = data.kind
            else:
                # 保留历史分析引用的原件，工作区整体删除时统一级联清理。
                row.deleted = True
            return DocumentView.model_validate(row)

    async def run_view(
        self, repo: AnalysisRepository, row: AnalysisRun, *, details: bool = False
    ) -> RunView:
        view = RunView.model_validate(row)
        workspace = await repo.workspace(row.workspace_id)
        view.workspace_name = workspace.name if workspace else None
        if row.status in {"completed", "partial"}:
            view.files = [
                GeneratedFileView.model_validate(file)
                for file in await FileRepository(repo.session).analysis(row.id)
            ]
        saved_input = RunInput.model_validate(row.input)
        view.document_ids = saved_input.document_ids
        history = row.checkpoint.get("clarification_history", [])
        if isinstance(history, list):
            view.clarification_history = [
                {"question": item["question"], "answer": item["answer"]}
                for item in history
                if isinstance(item, dict)
                and isinstance(item.get("question"), str)
                and isinstance(item.get("answer"), str)
            ]
        failure = row.checkpoint.get("failure_message")
        view.failure_message = (
            failure[:300] if row.status == "failed" and isinstance(failure, str) else None
        )
        if details:
            view.steps = [StepView.model_validate(step) for step in await repo.steps(row.id)]
            view.tool_calls = [
                ToolCallView.model_validate(call) for call in await repo.calls(row.id)
            ]
        return view

    async def runs(self, workspace_id: UUID) -> list[RunView]:
        async with self.sessions() as session:
            repo = AnalysisRepository(session)
            await self.require_workspace(repo, workspace_id)
            return [await self.run_view(repo, row) for row in await repo.runs(workspace_id)]

    async def run(self, workspace_id: UUID, run_id: UUID) -> RunView:
        async with self.sessions() as session:
            repo = AnalysisRepository(session)
            return await self.run_view(
                repo, await self.require_run(repo, workspace_id, run_id), details=True
            )

    async def run_events(self, workspace_id: UUID, run_id: UUID) -> AsyncIterator[str]:
        started = perf_counter()
        connection: AsyncConnection | None = None
        try:
            url = make_url(self.settings.database_url.get_secret_value()).set(
                drivername="postgresql"
            )
            connection = await AsyncConnection.connect(
                url.render_as_string(hide_password=False), autocommit=True, connect_timeout=3
            )
            await connection.execute(
                sql.SQL("LISTEN {}").format(
                    sql.Identifier(AnalysisRepository.event_channel(run_id))
                )
            )
            # 先监听再读快照，覆盖建连期间的提交；重连直接读取最新持久化状态。
            previous = ""
            while True:
                item = await self.run(workspace_id, run_id)
                payload = item.model_dump_json()
                if payload != previous:
                    yield f"event: snapshot\ndata: {payload}\n\n"
                    previous = payload
                if item.status not in {"queued", "running"}:
                    return
                while True:
                    notified = False
                    async for _ in connection.notifies(timeout=15, stop_after=1):
                        notified = True
                    if notified:
                        break
                    # 心跳仅保持连接，不按心跳频率查询数据库。
                    yield ": heartbeat\n\n"
        except Exception as exc:
            logger.error(
                "文书分析事件推送失败 workspace_id=%s run_id=%s "
                "stage=event_stream duration_ms=%.1f",
                workspace_id,
                run_id,
                (perf_counter() - started) * 1000,
                exc_info=exc,
            )
            retryable = not isinstance(exc, AppError) or exc.status_code >= 500
            yield (
                'event: stream_error\ndata: {"retryable": '
                + ("true" if retryable else "false")
                + "}\n\n"
            )
        finally:
            if connection is not None:
                with anyio.CancelScope(shield=True):
                    try:
                        await connection.close()
                    except Exception as exc:
                        logger.error(
                            "文书分析事件连接关闭失败 workspace_id=%s run_id=%s "
                            "stage=event_stream_cleanup duration_ms=%.1f",
                            workspace_id,
                            run_id,
                            (perf_counter() - started) * 1000,
                            exc_info=exc,
                        )

    async def create_run(self, workspace_id: UUID, data: RunInput) -> RunView:
        request_input = data.model_dump(mode="json")
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            workspace = await self.require_workspace(repo, workspace_id, lock=True)
            existing = await repo.request(workspace_id, data.request_id)
            if existing:
                if existing.config_snapshot.get("request_input", existing.input) != request_input:
                    raise AppError("request_conflict", "请求标识已用于另一项分析，请重新提交", 409)
                return await self.run_view(repo, existing)
            if await repo.active(workspace_id):
                raise AppError("analysis_busy", "请等待当前工作区分析完成，或先停止任务", 409)
            docs = {row.id: row for row in await repo.documents(workspace_id)}
            config = AnalysisConfig.model_validate((await repo.settings()).settings)
            config_repo = ConfigRepository(session)
            prompt_snapshots = await self.resolve_prompts(config, config_repo)
            if data.automatic:
                if not data.document_ids:
                    data = data.model_copy(
                        update={
                            "document_ids": [
                                doc.id for doc in docs.values() if doc.status == "ready"
                            ][-30:]
                        }
                    )
                policy = Policy.model_validate((await config_repo.policy()).settings)
                if data.model_id is None:
                    available_models = [
                        model
                        for model in await config_repo.models()
                        if model.enabled and model.model_type == "chat" and model.supports_tools
                    ]
                    configured_id = config.default_model_id or policy.default_model_id
                    selected_model = next(
                        (model for model in available_models if model.id == configured_id), None
                    )
                    selected_model = selected_model or next(iter(available_models), None)
                    if selected_model is None:
                        raise AppError(
                            "analysis_model_unconfigured",
                            "请先在模型配置中启用支持工具调用的对话模型",
                        )
                    data = data.model_copy(update={"model_id": selected_model.id})
                data = data.model_copy(
                    update={
                        "knowledge_base_ids": list(
                            dict.fromkeys(config.knowledge_base_ids or policy.knowledge_base_ids)
                        ),
                        "mcp_server_ids": [
                            server.id
                            for server in await repo.servers()
                            if server.enabled
                            and server.allowed_tools
                            and server.allow_document_content
                        ][:10],
                    }
                )
            if data.model_id is None:
                raise AppError("analysis_model_unconfigured", "请先配置文书分析模型")
            if len(set(data.document_ids)) != len(data.document_ids) or any(
                doc_id not in docs for doc_id in data.document_ids
            ):
                raise AppError("invalid_documents", "请选择当前工作区的有效文书")
            if any(docs[doc_id].status != "ready" for doc_id in data.document_ids):
                raise AppError("ocr_required", "所选材料包含未提取内容，请完成 OCR 后重新上传")
            if data.intent == "compare" and len(data.document_ids) != 2:
                raise AppError("compare_requires_two", "版本比较请选择两份文书")
            if data.parent_run_id:
                parent = await self.require_run(repo, workspace_id, data.parent_run_id)
                if parent.status not in {"completed", "partial"}:
                    raise AppError("invalid_parent_analysis", "请在已形成报告的分析中继续追问")
            if await KnowledgeRepository(session).existing_base_ids(data.knowledge_base_ids) != set(
                data.knowledge_base_ids
            ):
                raise AppError("invalid_knowledge_base", "所选知识库已不存在")
            connections: dict[str, object] = {}
            model_ids = {
                data.model_id,
                *(item.model_id for item in config.agent_configs.values() if item.model_id),
            }
            for model_id in model_ids:
                model = await ConfigRepository(session).model(model_id)
                if (
                    model is None
                    or not model.enabled
                    or model.model_type != "chat"
                    or not model.supports_tools
                ):
                    raise AppError(
                        "invalid_analysis_model", "请选择已启用并声明支持工具调用的对话模型"
                    )
                connections[str(model_id)] = {
                    key: getattr(model, key)
                    for key in (
                        "protocol",
                        "base_url",
                        "model_name",
                        "api_key_encrypted",
                        "context_tokens",
                        "max_output_tokens",
                        "temperature",
                        "token_parameter",
                        "supports_json_mode",
                    )
                }
            servers: list[dict[str, object]] = []
            for server_id in dict.fromkeys(data.mcp_server_ids):
                server = await repo.server(server_id)
                if server is None or not server.enabled or not server.allowed_tools:
                    raise AppError("invalid_mcp_server", "请选择已启用且已授权工具的 MCP 服务")
                servers.append(
                    {
                        key: getattr(server, key)
                        for key in (
                            "id",
                            "name",
                            "url",
                            "token_encrypted",
                            "allowed_tools",
                            "timeout",
                            "allow_document_content",
                        )
                    }
                )
                servers[-1]["id"] = str(server_id)
            snapshot: dict[str, object] = {
                "request_input": request_input,
                "config": config.model_dump(mode="json"),
                "prompt_snapshots": {
                    role: prompt.model_dump(mode="json")
                    for role, prompt in prompt_snapshots.items()
                },
                "models": connections,
                "servers": servers,
                "documents": {
                    str(doc_id): {
                        "sha256": docs[doc_id].sha256,
                        "revision": docs[doc_id].revision,
                        "kind": docs[doc_id].kind,
                    }
                    for doc_id in data.document_ids
                },
                "request_id": str(data.request_id),
                "knowledge_bases": [
                    {"id": str(base.id), "name": base.name}
                    for base_id in data.knowledge_base_ids
                    if (base := await KnowledgeRepository(session).base(base_id)) is not None
                ],
                "unreadable_documents": [
                    doc.filename for doc in docs.values() if doc.status != "ready"
                ],
            }
            row = AnalysisRun(
                workspace_id=workspace_id,
                request_id=data.request_id,
                parent_run_id=data.parent_run_id,
                instruction=data.instruction,
                input=data.model_dump(mode="json"),
                config_snapshot=snapshot,
                checkpoint={},
                status="queued",
                stage="queued",
                intent=None,
                report=None,
                clarification=None,
            )
            session.add(row)
            workspace.updated_at = datetime.now(UTC)
            await session.flush()
            await repo.notify_run(row.id)
            return await self.run_view(repo, row)

    async def action(
        self, workspace_id: UUID, run_id: UUID, action: str, answer: str = ""
    ) -> RunView:
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            await self.require_workspace(repo, workspace_id, lock=True)
            row = await self.require_run(repo, workspace_id, run_id, lock=True)
            if action == "cancel":
                if row.status in {"queued", "running", "needs_input"}:
                    if row.active_started_at:
                        row.elapsed_seconds += max(
                            0, int((datetime.now(UTC) - row.active_started_at).total_seconds())
                        )
                        row.active_started_at = None
                    row.cancel_requested = True
                    row.status, row.stage = "cancelled", "cancelled"
                    row.lease_token, row.lease_until = None, None
            else:
                expected = (
                    {"needs_input"} if action == "resume" else {"failed", "cancelled", "partial"}
                )
                if row.status not in expected:
                    raise AppError("invalid_analysis_state", "当前任务状态不支持此操作", 409)
                if await repo.active(workspace_id, exclude=run_id):
                    raise AppError("analysis_busy", "请先完成或停止当前分析", 409)
                if action == "resume":
                    if not answer.strip():
                        raise AppError("answer_required", "请输入补充信息")
                    checkpoint = {
                        key: value
                        for key, value in row.checkpoint.items()
                        if key not in {"intent", "report"}
                    }
                    previous = checkpoint.get("clarification_answers", [])
                    answers = (
                        [item for item in previous if isinstance(item, str)]
                        if isinstance(previous, list)
                        else []
                    )
                    if len(answers) >= 3:
                        raise AppError(
                            "too_many_clarifications", "补充次数已达上限，请整理信息后新建分析"
                        )
                    row.checkpoint = {
                        **checkpoint,
                        "clarification_answers": [*answers, answer.strip()],
                        "clarification_history": [
                            *(
                                checkpoint.get("clarification_history", [])
                                if isinstance(checkpoint.get("clarification_history"), list)
                                else []
                            ),
                            {
                                "question": row.clarification or "请补充分析信息",
                                "answer": answer.strip(),
                            },
                        ],
                    }
                    saved_input = RunInput.model_validate(row.input)
                    if saved_input.automatic:
                        all_documents = await repo.documents(workspace_id)
                        documents = [doc for doc in all_documents if doc.status == "ready"][-30:]
                        saved_input.document_ids = [doc.id for doc in documents]
                        row.input = saved_input.model_dump(mode="json")
                        row.config_snapshot = {
                            **row.config_snapshot,
                            "documents": {
                                str(doc.id): {
                                    "sha256": doc.sha256,
                                    "revision": doc.revision,
                                    "kind": doc.kind,
                                }
                                for doc in documents
                            },
                            "unreadable_documents": [
                                doc.filename for doc in all_documents if doc.status != "ready"
                            ],
                        }
                    row.intent, row.clarification = None, None
                row.status, row.stage = "queued", "queued"
                # 复核及修订依赖专家成果，重试后不能复用旧结论。
                row.checkpoint = {
                    key: value
                    for key, value in row.checkpoint.items()
                    if key not in {"review", "review_final", "failure_message"}
                    and not key.startswith("revision:")
                }
                row.report = None
                row.cancel_requested = False
                row.active_started_at = None
                row.lease_token, row.lease_until = None, None
                # 用户重试开启新的预算；已完成步骤通过检查点复用。
                row.attempts, row.model_calls, row.tool_calls_count, row.elapsed_seconds = (
                    0,
                    0,
                    0,
                    0,
                )
            row.updated_at = datetime.now(UTC)
            await repo.notify_run(row.id)
            return await self.run_view(repo, row, details=True)

    async def config(self, data: AnalysisConfig | None = None) -> AnalysisConfig:
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            row = await repo.settings(lock=data is not None)
            if data:
                await self.resolve_prompts(data, ConfigRepository(session))
                if await KnowledgeRepository(session).existing_base_ids(
                    data.knowledge_base_ids
                ) != set(data.knowledge_base_ids):
                    raise AppError("invalid_analysis_knowledge", "请选择有效的分析知识库")
                if data.default_model_id:
                    model = await ConfigRepository(session).model(data.default_model_id)
                    if (
                        model is None
                        or not model.enabled
                        or model.model_type != "chat"
                        or not model.supports_tools
                    ):
                        raise AppError(
                            "invalid_analysis_model", "默认模型需为支持工具调用的已启用对话模型"
                        )
                for item in data.agent_configs.values():
                    if item.model_id:
                        model = await ConfigRepository(session).model(item.model_id)
                        if (
                            model is None
                            or not model.enabled
                            or model.model_type != "chat"
                            or not model.supports_tools
                        ):
                            raise AppError(
                                "invalid_agent_model", "Agent 请选择支持工具调用的已启用对话模型"
                            )
                row.settings = data.model_dump(mode="json")
            return AnalysisConfig.model_validate(row.settings)

    @staticmethod
    def server_view(row: AnalysisMCPServer) -> MCPServerView:
        return MCPServerView(
            id=row.id,
            name=row.name,
            url=row.url,
            enabled=row.enabled,
            allowed_tools=row.allowed_tools,
            timeout=row.timeout,
            allow_document_content=row.allow_document_content,
            has_token=bool(row.token_encrypted),
        )

    async def servers(self) -> list[MCPServerView]:
        async with self.sessions() as session:
            return [self.server_view(row) for row in await AnalysisRepository(session).servers()]

    async def save_server(
        self, data: MCPServerInput, server_id: UUID | None = None
    ) -> MCPServerView:
        try:
            validated_url(data.url)
            if data.token and data.clear_token:
                raise ValueError("conflicting credentials")
            if any(not TOOL_NAME.fullmatch(name) for name in data.allowed_tools):
                raise ValueError("invalid tool name")
        except ValueError as exc:
            raise AppError(
                "invalid_mcp_config", "请填写不含凭据或查询参数的 MCP 地址，并检查工具及密钥设置"
            ) from exc
        async with self.sessions.begin() as session:
            repo = AnalysisRepository(session)
            row = await repo.server(server_id, lock=True) if server_id else AnalysisMCPServer()
            if row is None:
                raise AppError("mcp_not_found", "MCP 服务不存在", 404)
            for key, value in data.model_dump(exclude={"token", "clear_token"}).items():
                setattr(row, key, value)
            row.allowed_tools = list(dict.fromkeys(data.allowed_tools))
            if data.token:
                row.token_encrypted = encrypt(data.token.get_secret_value(), self.settings)
            elif data.clear_token:
                row.token_encrypted = None
            session.add(row)
            await session.flush()
            return self.server_view(row)

    async def delete_server(self, server_id: UUID) -> None:
        async with self.sessions.begin() as session:
            row = await AnalysisRepository(session).server(server_id, lock=True)
            if row is None:
                raise AppError("mcp_not_found", "MCP 服务不存在", 404)
            await session.delete(row)

    async def discover(self, server_id: UUID) -> list[dict[str, object]]:
        async with self.sessions() as session:
            row = await AnalysisRepository(session).server(server_id)
            if row is None:
                raise AppError("mcp_not_found", "MCP 服务不存在", 404)
            connection = MCPConnection(
                url=row.url,
                token=decrypt(row.token_encrypted, self.settings),
                allowed_tools=None,
                timeout=row.timeout,
                allow_private=self.settings.mcp_allow_private,
            )
        tools = await connection.discover()
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in tools
        ]
