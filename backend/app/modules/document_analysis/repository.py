from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.modules.document_analysis.models import (
    AnalysisDocument,
    AnalysisMCPServer,
    AnalysisRun,
    AnalysisSettings,
    AnalysisStep,
    AnalysisToolCall,
    AnalysisWorkspace,
)


class AnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def event_channel(run_id: UUID) -> str:
        return f"analysis_run_{run_id.hex}"

    async def notify_run(self, run_id: UUID) -> None:
        # 与状态写入同一事务，提交后才通知其他进程；回滚不会发送。
        await self.session.flush()
        await self.session.execute(
            text("SELECT pg_notify(:channel, '')"), {"channel": self.event_channel(run_id)}
        )

    async def workspaces(self) -> list[AnalysisWorkspace]:
        return list(
            await self.session.scalars(
                select(AnalysisWorkspace).order_by(AnalysisWorkspace.updated_at.desc()).limit(200)
            )
        )

    async def workspace(
        self, workspace_id: UUID, *, lock: bool = False
    ) -> AnalysisWorkspace | None:
        return await self.session.get(AnalysisWorkspace, workspace_id, with_for_update=lock)

    async def documents(
        self, workspace_id: UUID, *, include_deleted: bool = False, content: bool = False
    ) -> list[AnalysisDocument]:
        query = select(AnalysisDocument).where(AnalysisDocument.workspace_id == workspace_id)
        if not include_deleted:
            query = query.where(AnalysisDocument.deleted.is_(False))
        if content:
            query = query.options(undefer(AnalysisDocument.text), undefer(AnalysisDocument.spans))
        return list(await self.session.scalars(query.order_by(AnalysisDocument.created_at)))

    async def document(
        self, workspace_id: UUID, document_id: UUID, *, original: bool = False
    ) -> AnalysisDocument | None:
        query = select(AnalysisDocument).where(
            AnalysisDocument.workspace_id == workspace_id, AnalysisDocument.id == document_id
        )
        query = query.options(undefer(AnalysisDocument.text), undefer(AnalysisDocument.spans))
        if original:
            query = query.options(undefer(AnalysisDocument.original))
        return await self.session.scalar(query)

    async def runs(self, workspace_id: UUID) -> list[AnalysisRun]:
        return list(
            await self.session.scalars(
                select(AnalysisRun)
                .where(AnalysisRun.workspace_id == workspace_id)
                .order_by(AnalysisRun.created_at.desc())
                .limit(100)
            )
        )

    async def first_run_id(self, workspace_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(AnalysisRun.id)
            .where(AnalysisRun.workspace_id == workspace_id)
            .order_by(AnalysisRun.created_at, AnalysisRun.id)
            .limit(1)
        )

    async def active(self, workspace_id: UUID, *, exclude: UUID | None = None) -> bool:
        query = select(AnalysisRun.id).where(
            AnalysisRun.workspace_id == workspace_id, AnalysisRun.status.in_(("queued", "running"))
        )
        if exclude:
            query = query.where(AnalysisRun.id != exclude)
        return await self.session.scalar(query.limit(1)) is not None

    async def run(
        self, workspace_id: UUID, run_id: UUID, *, lock: bool = False
    ) -> AnalysisRun | None:
        query = select(AnalysisRun).where(
            AnalysisRun.id == run_id, AnalysisRun.workspace_id == workspace_id
        )
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def request(self, workspace_id: UUID, request_id: UUID) -> AnalysisRun | None:
        return await self.session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.workspace_id == workspace_id, AnalysisRun.request_id == request_id
            )
        )

    async def steps(self, run_id: UUID) -> list[AnalysisStep]:
        return list(
            await self.session.scalars(
                select(AnalysisStep)
                .where(AnalysisStep.run_id == run_id)
                .order_by(AnalysisStep.started_at, AnalysisStep.id)
            )
        )

    async def calls(self, run_id: UUID) -> list[AnalysisToolCall]:
        return list(
            await self.session.scalars(
                select(AnalysisToolCall)
                .where(AnalysisToolCall.run_id == run_id)
                .order_by(AnalysisToolCall.created_at, AnalysisToolCall.id)
            )
        )

    async def servers(self) -> list[AnalysisMCPServer]:
        return list(
            await self.session.scalars(select(AnalysisMCPServer).order_by(AnalysisMCPServer.name))
        )

    async def server(self, server_id: UUID, *, lock: bool = False) -> AnalysisMCPServer | None:
        return await self.session.get(AnalysisMCPServer, server_id, with_for_update=lock)

    async def settings(self, *, lock: bool = False) -> AnalysisSettings:
        row = await self.session.get(AnalysisSettings, 1, with_for_update=lock)
        if row is None:
            raise RuntimeError("document analysis migration 0014 is required")
        return row

    async def claim(self) -> AnalysisRun | None:
        now = datetime.now(UTC)
        row = await self.session.scalar(
            select(AnalysisRun)
            .where(
                or_(
                    AnalysisRun.status == "queued",
                    (AnalysisRun.status == "running") & (AnalysisRun.lease_until < now),
                )
            )
            .order_by(AnalysisRun.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        if row.active_started_at is not None:
            row.elapsed_seconds += max(0, int((now - row.active_started_at).total_seconds()))
        row.active_started_at = now
        row.checkpoint = {
            key: value
            for key, value in row.checkpoint.items()
            if key not in {"review", "review_final"} and not key.startswith("revision:")
        }
        row.status, row.lease_token = "running", uuid4()
        row.lease_until, row.updated_at = now + timedelta(seconds=90), now
        row.attempts += 1
        return row

    async def owned(self, run_id: UUID, token: UUID) -> AnalysisRun | None:
        return await self.session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.id == run_id,
                AnalysisRun.lease_token == token,
                AnalysisRun.status == "running",
            )
            .with_for_update()
        )

    async def interrupt_old_steps(self, run_id: UUID) -> None:
        await self.session.execute(
            update(AnalysisStep)
            .where(AnalysisStep.run_id == run_id, AnalysisStep.status == "running")
            .values(
                status="interrupted", summary="执行中断，等待恢复", finished_at=datetime.now(UTC)
            )
        )
        await self.session.execute(
            update(AnalysisToolCall)
            .where(AnalysisToolCall.run_id == run_id, AnalysisToolCall.status == "running")
            .values(status="interrupted")
        )
