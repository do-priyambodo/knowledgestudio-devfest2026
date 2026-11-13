"""FastAPI entry point for `knowledgestudio-devfest2026` (BigQuery + Knowledge Catalog layer).

When `ENABLE_ADK_WEB_UI=true` (used inside the IAM-protected Cloud Run service accessed
via `gcloud run services proxy`), mounts the interactive Google ADK Web Playground (`/dev-ui/`)
hosting all 3 dropdown agents (`agent_1_without_kc`, `agent_2_with_kc`, `app`) alongside
`/health` and `/api/v1/agent/{run,compare}`.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.features.agent.router import router as agent_router
from api.features.health.router import router as health_router
from api.platform.config import settings
from api.platform.logger import logger, setup_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Validate BigQuery + Knowledge Catalog project configuration on startup."""
    setup_logging()
    logger.info(
        "Application starting up...",
        app=settings.APP_NAME,
        env=settings.APP_ENV,
        gcp_project=settings.GCP_PROJECT_ID,
        bq_dataset=settings.BQ_DATASET_ID,
    )
    if not settings.GCP_PROJECT_ID.strip():
        raise RuntimeError("FATAL: GCP_PROJECT_ID must be configured for BigQuery and Knowledge Catalog.")
    yield
    logger.info("Application shutting down...", app=settings.APP_NAME)


def build_fastapi_app() -> FastAPI:
    """Create the FastAPI app, optionally mounting the stateless ADK Web Playground."""
    if settings.ENABLE_ADK_WEB_UI and Path(settings.ADK_AGENTS_DIR).is_dir():
        from google.adk.cli.fast_api import get_fast_api_app

        adk_app: FastAPI = get_fast_api_app(
            agents_dir=settings.ADK_AGENTS_DIR,
            use_local_storage=False,
            web=True,
            lifespan=lifespan,
            auto_create_session=True,
        )
        adk_app.include_router(health_router)
        adk_app.include_router(agent_router)
        return adk_app

    api_app = FastAPI(
        title=settings.APP_NAME,
        version="0.2.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )
    api_app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    api_app.include_router(health_router)
    api_app.include_router(agent_router)

    @api_app.get("/")
    async def root() -> dict[str, str]:
        return {
            "status": "success",
            "message": (
                f"Welcome to {settings.APP_NAME}. Use `make playground` locally or set "
                "ENABLE_ADK_WEB_UI=true behind Cloud Run IAM proxy to open /dev-ui/."
            ),
        }

    return api_app


app = build_fastapi_app()
