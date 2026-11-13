from fastapi import APIRouter

from api.features.health.schemas import HealthResponse
from api.features.health.service import HealthService

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def check_health() -> HealthResponse:
    return HealthService.get_status()
