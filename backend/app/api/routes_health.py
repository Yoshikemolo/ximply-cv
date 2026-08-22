"""
Health check API routes.

Provides endpoints for monitoring application health and dependencies.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.minio_client import check_connection as check_minio
from app.models.schemas import HealthCheckResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthCheckResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthCheckResponse:
    """
    Check application health status.

    Verifies connectivity to database and MinIO storage.

    Returns:
        HealthCheckResponse: Current health status of all services.
    """
    # Check database
    db_status = "healthy"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"

    # Check MinIO
    minio_status = "healthy" if check_minio() else "unhealthy"

    # Overall status
    overall_status = "healthy"
    if db_status == "unhealthy" or minio_status == "unhealthy":
        overall_status = "degraded"

    return HealthCheckResponse(
        status=overall_status,
        version=settings.app_version,
        database=db_status,
        minio=minio_status,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/live")
async def liveness_probe() -> dict:
    """
    Kubernetes liveness probe endpoint.

    Returns:
        dict: Simple alive status.
    """
    return {"status": "alive"}


@router.get("/ready")
async def readiness_probe(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Kubernetes readiness probe endpoint.

    Checks if the application is ready to receive traffic.

    Returns:
        dict: Ready status.

    Raises:
        HTTPException: If application is not ready.
    """
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return {"status": "not_ready", "reason": str(e)}


@router.get("/acceleration")
async def acceleration_status() -> dict:
    """
    Report whether inference is running on dedicated hardware.

    Public because it describes the server itself rather than any user data, and
    because the client shows it before the first frame is ever sent.

    Returns:
        dict: Device details and the state of each inference backend.
    """
    from app.services.acceleration_service import get_acceleration_service

    return get_acceleration_service().report().to_dict()
