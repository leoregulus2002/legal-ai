from fastapi import APIRouter

from app.modules.consultation.router import router as consultation_router
from app.modules.document_analysis.router import router as document_analysis_router
from app.modules.files.router import router as files_router
from app.modules.health.router import router as health_router
from app.modules.knowledge.regulation_router import router as regulation_router
from app.modules.knowledge.router import router as knowledge_router
from app.modules.public_laws.router import router as public_law_router
from app.modules.system_config.router import router as config_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(config_router)
api_router.include_router(consultation_router)
api_router.include_router(document_analysis_router)
api_router.include_router(files_router)

api_router.include_router(regulation_router)
api_router.include_router(knowledge_router)
api_router.include_router(public_law_router)
