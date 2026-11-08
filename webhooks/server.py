from fastapi import FastAPI
from contextlib import asynccontextmanager
from core.config import settings
from core.logger import logger
from core.database import engine
from core.redis_client import redis_service
from webhooks.youtube import router as youtube_router
from webhooks.escrow_gateway import router as escrow_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI Webhook Server starting up...")
    yield
    logger.info("FastAPI Webhook Server shutting down...")
    await redis_service.close()
    await engine.dispose()


app = FastAPI(
    title="Dual-Engine Social Bot Webhook Gateway",
    version="1.0.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(youtube_router)
app.include_router(escrow_router)


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "mode": "production" if not settings.DEBUG else "debug",
    }

