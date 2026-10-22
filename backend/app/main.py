import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api import api_router
from app.common.exceptions import register_exception_handlers
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.redis import RedisClient
from app.modules.consultation.memory import MemoryStore
from app.modules.consultation.service import ConsultationService
from app.modules.document_analysis.worker import AnalysisWorker
from app.modules.knowledge.worker import KnowledgeWorker
from app.modules.public_laws.http_client import OfficialLawClient
from app.modules.public_laws.worker import PublicLawVectorWorker


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        async with AsyncExitStack() as stack:
            database = Database(config)
            stack.push_async_callback(database.close)
            redis = RedisClient(config)
            stack.push_async_callback(redis.close)
            application.state.database = database
            application.state.redis = redis
            await redis.initialize()
            official_laws = OfficialLawClient(redis.client)
            stack.push_async_callback(official_laws.close)
            application.state.official_laws = official_laws
            consultation = ConsultationService(database.sessions, config, MemoryStore(redis.client))
            maintenance = asyncio.create_task(consultation.maintain_attachments())

            knowledge_worker = KnowledgeWorker(database.sessions, config)
            knowledge_tasks = [
                asyncio.create_task(knowledge_worker.run(kind)) for kind in ("PARSE", "EMBED")
            ]
            knowledge_tasks.append(asyncio.create_task(knowledge_worker.maintain_lexical_index()))
            knowledge_tasks.append(
                asyncio.create_task(
                    PublicLawVectorWorker(database.sessions, config, official_laws).run()
                )
            )
            knowledge_tasks.append(
                asyncio.create_task(AnalysisWorker(database.sessions, config).run())
            )

            async def stop_knowledge() -> None:
                for task in knowledge_tasks:
                    task.cancel()
                await asyncio.gather(*knowledge_tasks, return_exceptions=True)

            stack.push_async_callback(stop_knowledge)

            async def stop_maintenance() -> None:
                maintenance.cancel()
                try:
                    await maintenance
                except asyncio.CancelledError:
                    pass

            stack.push_async_callback(stop_maintenance)
            yield

    # debug 配置控制开发文档；不启用 Starlette 调试异常页面，避免绕过统一错误响应。
    application = FastAPI(
        title=config.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if config.debug else None,
        redoc_url="/redoc" if config.debug else None,
    )
    application.state.settings = config
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
