from fastapi import APIRouter

from app.modules.consultation.router import router as consultation_router
from app.modules.health.router import router as health_router
from app.modules.system_config.router import router as config_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(config_router)
api_router.include_router(consultation_router)
