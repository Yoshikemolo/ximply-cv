"""
Streaming endpoints.

A subscriber connects here instead of running a server of its own. Events go
out as server sent events and frames as a multipart JPEG stream, both chosen
because a program that is already installed can read them: `curl -N` for the
first, any browser or player for the second.

See ADR-0022 for why there are two transports, ADR-0023 for what a live frame
is allowed to do, and SEC-0011 for what this exposes.
"""

import asyncio
import json
from typing import Any, AsyncGenerator, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.core.logging import get_logger
from app.core.stream_auth import StreamPrincipal, require_stream_scope
from app.models.enums import Permission
from app.services.mqtt_service import get_mqtt_publisher
from app.services.stream_service import get_stream_hub

logger = get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["Streaming"])

# The separator between frames of a multipart stream. Any token works as long
# as it cannot appear in the payload; JPEG bytes never contain this one.
FRAME_BOUNDARY = "ximplyframe"

# How long a generator waits for something to send before looking at whether
# the client is still there. Short enough that a closed connection is noticed
# quickly, long enough not to spin.
IDLE_TICK_SECONDS = 1.0


def _require_streaming() -> None:
    """
    Refuse everything when the deployment did not ask for streaming.

    Raises:
        HTTPException: 404 when STREAM_ENABLED is false.
    """
    if not settings.stream_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Streaming is not enabled on this deployment",
        )


@router.get("/info")
async def stream_info(
    principal: StreamPrincipal = Depends(
        require_stream_scope(Permission.EVENTS_READ)
    ),
) -> Dict[str, Any]:
    """
    What can be subscribed to, and how.

    The interface builds its topic table and its examples from this rather than
    hard coding them, so a topic added here appears there with no frontend
    change.

    Args:
        principal: Whoever is asking.

    Returns:
        The broker state and topics, the endpoint paths, and the scopes each
        one needs.
    """
    _require_streaming()
    hub = get_stream_hub()
    prefix = settings.api_prefix
    return {
        "enabled": True,
        "owner": str(principal.owner_id),
        "broker": get_mqtt_publisher().describe(),
        "endpoints": {
            "events": {
                "path": f"{prefix}/stream/events",
                "mediaType": "text/event-stream",
                "scope": Permission.EVENTS_READ.value,
            },
            "camera": {
                "path": f"{prefix}/stream/camera/{{cameraId}}",
                "mediaType": f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
                "scope": Permission.CAMERA_VIEW.value,
                "enabled": settings.camera_view_enabled,
                "maxFps": settings.stream_camera_max_fps,
                "maxSide": settings.stream_camera_max_side,
            },
        },
        "keepaliveSeconds": settings.stream_keepalive_seconds,
        "subscribers": hub.event_subscribers(principal.owner_id),
        "dropped": hub.dropped,
    }


async def _event_stream(
    request: Request, principal: StreamPrincipal
) -> AsyncGenerator[Dict[str, str], None]:
    """
    Yield one server sent event per record until the client goes away.

    The disconnect check is the loop condition for the reason the detection
    stream already documents: an endless generator and a graceful shutdown that
    waits on open connections leaves the port bound.

    Args:
        request: The open request, used to notice a client leaving.
        principal: Whoever is subscribed.

    Yields:
        The SSE fields for one record.
    """
    hub = get_stream_hub()
    subscription = hub.subscribe_events(principal.owner_id)
    logger.info(f"Event stream opened for {principal.kind} {principal.label}")
    try:
        while not await request.is_disconnected():
            try:
                payload = await asyncio.wait_for(
                    subscription.queue.get(), timeout=IDLE_TICK_SECONDS
                )
            except asyncio.TimeoutError:
                continue
            yield {
                "event": payload.get("eventName", "event"),
                "id": str(payload.get("id", "")),
                "data": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            }
    finally:
        hub.unsubscribe_events(principal.owner_id, subscription)
        logger.info(f"Event stream closed for {principal.kind} {principal.label}")


@router.get("/events")
async def stream_events(
    request: Request,
    principal: StreamPrincipal = Depends(
        require_stream_scope(Permission.EVENTS_READ)
    ),
) -> EventSourceResponse:
    """
    Subscribe to this account's events as they are raised.

    Each message carries the full log record, the same JSON a webhook delivery
    carries, with the event type in the SSE event field so a browser can listen
    per type.

    Args:
        request: The open request.
        principal: Whoever is subscribed.

    Returns:
        The event stream.
    """
    _require_streaming()
    return EventSourceResponse(
        _event_stream(request, principal),
        ping=int(settings.stream_keepalive_seconds),
    )


async def _frame_stream(
    request: Request, principal: StreamPrincipal, camera_id: str
) -> AsyncGenerator[bytes, None]:
    """
    Yield multipart JPEG parts until the client goes away.

    Args:
        request: The open request, used to notice a client leaving.
        principal: Whoever is watching.
        camera_id: Which camera to watch.

    Yields:
        One multipart part per frame.
    """
    hub = get_stream_hub()
    subscription = hub.subscribe_frames(principal.owner_id, camera_id)
    logger.info(
        f"Camera {camera_id} watched by {principal.kind} {principal.label}, "
        f"viewers now {hub.frame_viewers(principal.owner_id, camera_id)}"
    )
    try:
        while not await request.is_disconnected():
            try:
                frame = await asyncio.wait_for(
                    subscription.queue.get(), timeout=IDLE_TICK_SECONDS
                )
            except asyncio.TimeoutError:
                # No frame means no browser is capturing. The connection stays
                # open and silent, which is the truthful answer rather than a
                # broken one.
                continue
            yield (
                f"--{FRAME_BOUNDARY}\r\n"
                f"Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(frame)}\r\n\r\n"
            ).encode("ascii") + frame + b"\r\n"
    finally:
        hub.unsubscribe_frames(principal.owner_id, camera_id, subscription)
        logger.info(f"Camera {camera_id} released by {principal.label}")


@router.get("/camera/{camera_id}")
async def stream_camera(
    request: Request,
    camera_id: str,
    principal: StreamPrincipal = Depends(
        require_stream_scope(Permission.CAMERA_VIEW, explicit=True)
    ),
) -> StreamingResponse:
    """
    Watch one camera live.

    The scope has to be written on the token by name: an empty scope list means
    "whatever the owner holds" for reading and never means this (ADR-0023).

    Args:
        request: The open request.
        camera_id: Which camera to watch.
        principal: Whoever is watching.

    Returns:
        A multipart JPEG stream.

    Raises:
        HTTPException: 404 when the deployment has live viewing switched off.
    """
    _require_streaming()
    if not settings.camera_view_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live camera viewing is not enabled on this deployment",
        )

    return StreamingResponse(
        _frame_stream(request, principal, camera_id),
        media_type=f"multipart/x-mixed-replace; boundary={FRAME_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
