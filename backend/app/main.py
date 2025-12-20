"""
XIMPLY Vision API - Main Application Entry Point.

This module initializes the FastAPI application with all routes,
middleware, and lifecycle management.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes_auth import router as auth_router
from app.api.routes_detection import router as detection_router
from app.api.routes_health import router as health_router
from app.api.routes_objects import router as objects_router
from app.api.routes_users import router as users_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logging import get_logger, setup_logging
from app.core.minio_client import ensure_bucket_exists

# Initialize logging
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events for the application.
    """
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"API Version: {settings.api_version}")
    logger.info(f"Debug mode: {settings.debug}")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

    # Initialize MinIO bucket
    try:
        await ensure_bucket_exists()
        logger.info(f"MinIO bucket '{settings.minio_bucket}' ready")
    except Exception as e:
        logger.error(f"Failed to initialize MinIO: {e}")

    # Create storage directories
    settings.storage_base_path.mkdir(parents=True, exist_ok=True)
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    settings.models_path.mkdir(parents=True, exist_ok=True)

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down application")
    await close_db()
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="Computer Vision Object Detection and Recognition API",
    version=settings.app_version,
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle uncaught exceptions."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "api_version": settings.api_version,
        "docs": f"{settings.api_prefix}/docs",
    }


# Register API routers
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(objects_router, prefix=settings.api_prefix)
app.include_router(detection_router, prefix=settings.api_prefix)
app.include_router(users_router, prefix=settings.api_prefix)


# Log registered routes on startup
@app.on_event("startup")
async def log_routes():
    """Log all registered routes."""
    routes = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method not in ["HEAD", "OPTIONS"]:
                    routes.append(f"{method} {route.path}")

    logger.info(f"Registered {len(routes)} routes")
    if settings.debug:
        for route in sorted(routes):
            logger.debug(f"  {route}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=1 if settings.debug else settings.workers,
    )
