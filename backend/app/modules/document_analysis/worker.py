import asyncio
import logging
from datetime import UTC, datetime, timedelta
from time import monotonic, perf_counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.exceptions import AppError
from app.core.config import Settings
from app.core.logging import log_context
from app.modules.document_analysis.repository import AnalysisRepository
from app.modules.document_analysis.schemas import AnalysisConfig
from app.modules.document_analysis.tools import AnalysisStopped
from app.modules.document_analysis.workflow import AnalysisWorkflow

logger = logging.getLogger(__name__)


class AnalysisWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings

    async def heartbeat(self, run_id: UUID, token: UUID, task: asyncio.Task[None]) -> None:
        try:
            while not task.done():
                await asyncio.sleep(15)
                async with self.sessions.begin() as session:
                    row = await AnalysisRepository(session).owned(run_id, token)
                    if row is None or row.cancel_requested:
                        task.cancel()
                        return
                    row.lease_until = datetime.now(UTC) + timedelta(seconds=90)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("分析任务续租失败 run_id=%s stage=heartbeat", run_id, exc_info=exc)
            task.cancel()

    async def process(
        self, run_id: UUID, token: UUID, config: AnalysisConfig, elapsed: int, request_id: str
    ) -> None:
        started = perf_counter()
        with log_context(request_id=request_id, analysis_run_id=str(run_id)):
            task = asyncio.create_task(
                AnalysisWorkflow(self.sessions, self.settings, run_id, token).run()
            )
        heartbeat = asyncio.create_task(self.heartbeat(run_id, token, task))
        try:
            with log_context(
                request_id=request_id, analysis_run_id=str(run_id), processing_stage="analysis"
            ):
                async with asyncio.timeout(max(1, config.timeout_seconds - elapsed)):
                    await task
        except AnalysisStopped:
            pass
        except asyncio.CancelledError:
            # 服务关闭时释放租约，允许其他进程恢复；用户取消已清空token。
            async with self.sessions.begin() as session:
                row = await AnalysisRepository(session).owned(run_id, token)
                if row:
                    row.status, row.stage = "queued", "queued"
                    row.lease_token, row.lease_until = None, None
                    row.elapsed_seconds += int(perf_counter() - started)
                    row.active_started_at = None
                    await AnalysisRepository(session).notify_run(run_id)
            if asyncio.current_task() and asyncio.current_task().cancelling():
                raise
        except Exception as exc:
            logger.error(
                "法律文书分析失败 run_id=%s request_id=%s stage=workflow duration_ms=%.1f",
                run_id,
                request_id,
                (perf_counter() - started) * 1000,
                exc_info=exc,
            )
            async with self.sessions.begin() as session:
                row = await AnalysisRepository(session).owned(run_id, token)
                if row:
                    row.status, row.stage = "failed", "failed"
                    row.lease_token, row.lease_until = None, None
                    row.elapsed_seconds += int(perf_counter() - started)
                    row.active_started_at = None
                    row.updated_at = datetime.now(UTC)
                    # 用户提示独立于页面正文，通过事件接口或前端状态变化弹出。
                    row.checkpoint = {
                        **row.checkpoint,
                        "failure_message": (
                            exc.message
                            if isinstance(exc, AppError)
                            else "分析耗时已达上限，请缩小分析范围后重试"
                            if isinstance(exc, TimeoutError)
                            else "文书分析未完成，请稍后重试"
                        ),
                    }
                    await AnalysisRepository(session).notify_run(run_id)
        finally:
            task.cancel()
            heartbeat.cancel()
            await asyncio.gather(task, heartbeat, return_exceptions=True)

    async def run(self) -> None:
        last_failure_log = -60.0
        while True:
            try:
                async with self.sessions.begin() as session:
                    repo = AnalysisRepository(session)
                    row = await repo.claim()
                    if row:
                        run_id, token = row.id, row.lease_token
                        config = AnalysisConfig.model_validate(
                            row.config_snapshot.get("config", {})
                        )
                        elapsed, request_id = row.elapsed_seconds, str(row.request_id)
                        if row.attempts > 3:
                            row.status, row.stage = "failed", "failed"
                            row.lease_token, row.lease_until = None, None
                            row.active_started_at = None
                            row.checkpoint = {
                                **row.checkpoint,
                                "failure_message": "任务恢复次数已达上限，请手动重试",
                            }
                            token = None
                        await repo.interrupt_old_steps(row.id)
                        await repo.notify_run(row.id)
                    else:
                        token = None
                if token:
                    await self.process(run_id, token, config, elapsed, request_id)
                else:
                    await asyncio.sleep(3)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if monotonic() - last_failure_log >= 60:
                    logger.error("文书分析队列处理失败 stage=claim", exc_info=exc)
                    last_failure_log = monotonic()
                await asyncio.sleep(10)
