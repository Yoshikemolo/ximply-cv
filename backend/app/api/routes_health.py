"""
Health check API routes.

Provides endpoints for monitoring application health and dependencies.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.core.logging import get_logger
from app.core.minio_client import check_connection as check_minio
from app.core.security import TokenData
from app.models.enums import Permission
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


class AccelerationPreference(BaseModel):
    """A request to move one backend on or off the accelerator."""

    backend: str
    enabled: bool


@router.put("/acceleration")
async def set_acceleration(
    preference: AccelerationPreference,
    current_user: TokenData = Depends(
        require_permissions([Permission.DETECTION_CONFIGURE])
    ),
) -> dict:
    """
    Move one inference backend between the processor and the accelerator.

    Not public, unlike the status it changes: this decides what every viewer's
    frames run on, not just the caller's, so it sits behind the same permission
    as the rest of the detection configuration.

    The models affected are dropped rather than moved, and rebuild on the next
    frame that needs them. That costs a second or two once, against carrying a
    second copy of every model on the other device for a switch that is thrown
    rarely.

    Args:
        preference: Which backend to change and what to set it to.

    Returns:
        dict: The full status after the change, so the client does not have to
            ask again and cannot draw a state the server does not hold.

    Raises:
        HTTPException: If the backend is not one this server knows.
    """
    from app.services.acceleration_service import get_acceleration_service

    acceleration = get_acceleration_service()

    try:
        changed = acceleration.set_preference(preference.backend, preference.enabled)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e

    if changed:
        _reload_for(preference.backend)

    return acceleration.report().to_dict()


def _reload_for(backend: str) -> None:
    """
    Rebuild whatever the changed backend owns.

    Object detection needs nothing rebuilt: the segmentation and detection
    models are handed a device on every call, so the next frame already uses the
    new one. The body descriptor is the exception, because it is moved onto its
    device once at load.

    Failures here are logged and swallowed. A model that will not rebuild has
    already been dropped, and the next frame retries; raising would report the
    preference as rejected when it was in fact applied.
    """
    try:
        if backend in ("detection", "face"):
            from app.services.person_recognition_service import (
                get_person_recognition_service,
            )

            get_person_recognition_service().reload_models()

        if backend == "landmarks":
            from app.services.pose_service import get_pose_service

            get_pose_service().reload_models()
    except Exception as e:
        logger.warning(f"Could not rebuild models after changing {backend}: {e}")


@router.get("/mcp")
async def mcp_status() -> dict:
    """
    Report whether the Model Context Protocol is answering.

    Public, like the acceleration status it sits beside, because it describes
    the server rather than any user data and the interface shows it in the
    footer on every page.

    Returns:
        dict: Whether the protocol is built into this deployment, whether it is
            currently open, and the paths it is served on.
    """
    from app.services import mcp_server

    return mcp_server.describe()


class McpPreference(BaseModel):
    """A request to open or close the protocol."""

    enabled: bool


@router.put("/mcp")
async def set_mcp(
    preference: McpPreference,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
) -> dict:
    """
    Open or close the Model Context Protocol while the application runs.

    Not public, unlike the status it changes: closing it cuts off every
    connected agent, not just the caller's, so it sits behind the same
    permission as the rest of the integration configuration.

    A deployment that was started with the protocol switched off has nothing to
    open, and says so rather than reporting a state it cannot reach.

    Args:
        preference: Whether the protocol should answer requests.

    Returns:
        dict: The protocol status after the change.

    Raises:
        HTTPException: When the protocol is not built into this deployment.
    """
    from app.services import mcp_server

    if not settings.mcp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This deployment was started without the protocol. It is enabled "
                "with MCP_ENABLED, which is read at startup."
            ),
        )

    mcp_server.set_enabled(preference.enabled)
    logger.info(
        f"Protocol {'opened' if preference.enabled else 'closed'} by {current_user.sub}"
    )
    return mcp_server.describe()
