from datetime import UTC, datetime

from api.features.health.schemas import HealthResponse
from api.platform.config import settings


class HealthService:
    @staticmethod
    def get_status() -> HealthResponse:
        return HealthResponse(
            status="healthy",
            app=settings.APP_NAME,
            environment=settings.APP_ENV,
            timestamp=datetime.now(UTC).isoformat(),
        )
