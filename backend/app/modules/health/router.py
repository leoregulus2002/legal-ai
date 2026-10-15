from fastapi import APIRouter, Request, Response

from app.modules.health.schemas import HealthResponse, ReadinessResponse
from app.modules.health.service import check_readiness

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, summary="进程存活检查")
async def liveness() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
    summary="依赖就绪检查",
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    result = await check_readiness(request.app.state.database, request.app.state.redis)
    if result.status != "ok":
        response.status_code = 503
    return result
