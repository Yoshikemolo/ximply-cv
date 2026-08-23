"""
Model Context Protocol server.

Lets an external agent ask what the camera has seen: which people and objects
are known, what happened recently, and the events themselves as structured JSON.

The reading tools are a view over the same event layer the webhooks deliver, so
an agent and a subscriber see exactly the same records. Nothing here can change
the catalog, enrol a person or delete anything. An agent that can be persuaded
by the text it reads should not be able to alter what a camera remembers about
people, and that boundary is what makes it impossible rather than merely
discouraged.

The one thing an agent may change is whether a camera is running, and only
because that is useful enough to be worth its own key. It is not part of the
read only surface and is not covered by the reasoning above: switching on a
camera in somebody's room is a privacy decision, not a query. So it is gated
differently from everything else here. A token with no scopes carries whatever
its owner carries, which is the convenient default for reading; for control
that default does not apply, because every token written before this existed
has an empty scope list and reading consent into silence would hand a camera
switch to integrations created to watch events. Control is granted only where
somebody wrote camera:control on the token, and a deployment can remove the
ability altogether.

Even then an agent does not open a camera. The device belongs to the browser.
What is stored is the state the camera is wanted in, which an open interface
honours; nothing happens when none is open, and the reply says so rather than
claiming a camera that never started.

Authentication is an integration token presented as a bearer credential. The
token carries its own scopes, so an agent can be given the ability to read
events without the ability to read the catalog.
"""

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.models.entities import CategoryEntity, EventEntity, IntegrationTokenEntity, ObjectEntity
from app.models.enums import Permission
from app.services import camera_control_service as camera_control
from app.services.integration_token_service import resolve_token, token_allows

logger = get_logger(__name__)

# Set per request by the transport, so a tool knows who is asking. Held in a
# context variable rather than a global because several agents may be connected
# at once and must not see each other's identity.
import contextvars

current_token: contextvars.ContextVar[Optional[IntegrationTokenEntity]] = contextvars.ContextVar(
    "current_token", default=None
)


class NotAuthorised(Exception):
    """Raised when a tool is called without the permission it needs."""


# Whether the protocol is currently answering. Distinct from settings.mcp_enabled,
# which decides whether it is built and mounted at all: this is the switch on the
# wall, thrown while the application runs and starting from whatever the setting
# said. Held in memory, like the acceleration preference and for the same reason,
# which means a deployment running several workers throws it per worker.
_runtime_enabled: bool = settings.mcp_enabled


def is_enabled() -> bool:
    """Whether the protocol is currently accepting requests."""
    return _runtime_enabled


def set_enabled(enabled: bool) -> bool:
    """
    Open or close the protocol without restarting anything.

    Closing it leaves the endpoints mounted and refuses them, rather than
    unmounting: a connected agent gets a clear answer instead of a hole where
    the server used to be, and reopening costs nothing.

    Args:
        enabled: True to answer requests, False to refuse them.

    Returns:
        bool: The state after the change.
    """
    global _runtime_enabled
    if _runtime_enabled != enabled:
        _runtime_enabled = enabled
        logger.info(f"Model Context Protocol {'opened' if enabled else 'closed'}")
    return _runtime_enabled


def describe() -> Dict[str, Any]:
    """Report the state of the protocol for the status endpoint."""
    return {
        "available": settings.mcp_enabled,
        "enabled": _runtime_enabled,
        "path": settings.mcp_path,
        "ssePath": settings.mcp_sse_path,
    }


def _require(permission: Permission) -> IntegrationTokenEntity:
    """
    Check the caller may exercise a permission, and return their token.

    Raises:
        NotAuthorised: When there is no token, or its scopes exclude this.
    """
    token = current_token.get()
    if token is None:
        raise NotAuthorised("This server requires an integration token")
    if not token_allows(token, permission.value):
        raise NotAuthorised(f"This token does not carry {permission.value}")
    return token


def _require_explicit(permission: Permission) -> IntegrationTokenEntity:
    """
    Check the caller was granted a permission by name, and return their token.

    An empty scope list means a token carries whatever its owner carries, which
    is the convenient default for reading. It must not be a way to acquire an
    ability that did not exist when the token was written: every token issued
    before camera control existed has an empty scope list, and taking that as
    consent would hand a camera switch to integrations created to read events.

    So control is granted only where somebody named it.

    Raises:
        NotAuthorised: When the permission is not listed on the token.
    """
    token = current_token.get()
    if token is None:
        raise NotAuthorised("This server requires an integration token")
    if permission.value not in (token.scopes or []):
        raise NotAuthorised(
            f"This token does not carry {permission.value}. It has to be granted "
            "by name: a token with no scopes reads, it does not control."
        )
    return token


def _event_json(event: EventEntity) -> Dict[str, Any]:
    """
    One event as the same OpenTelemetry shaped record a subscriber receives.

    Identical to the webhook payload on purpose: an agent and a subscriber
    should never have to reconcile two descriptions of the same occurrence.
    """
    return {
        "id": str(event.id),
        "eventName": event.event_name,
        "timeUnixNano": str(event.timestamp_nanos),
        "observedTimeUnixNano": str(event.observed_timestamp_nanos),
        "severityNumber": event.severity_number,
        "severityText": event.severity_text,
        "body": event.body,
        "attributes": event.attributes,
        "resource": event.resource,
        "scope": {"name": event.scope_name, "version": event.scope_version},
        "occurredAt": event.occurred_at.isoformat() if event.occurred_at else None,
        "captureAvailable": bool(event.capture_path),
    }


def build_server():
    """
    Build the server and register its tools.

    Constructed lazily so a deployment with the protocol switched off does not
    import the library at all.
    """
    from mcp.server import MCPServer

    server = MCPServer(
        name="ximply-vision",
        title="XIMPLY Vision",
        version=settings.app_version,
        instructions=(
            "Access to what a XIMPLY Vision camera has observed, and to whether "
            "it is running. Events follow the OpenTelemetry logs data model. "
            "Use list_events to see what happened, get_current_scene for what is "
            "in view now, and export_events_otlp when the caller wants the raw "
            "envelope. Reading never changes anything. The camera can be asked "
            "to start or stop with start_camera and stop_camera, which need "
            "camera:control on the token and are honoured by an open interface: "
            "check get_camera to see whether the camera actually started."
        ),
    )

    @server.tool(
        name="list_events",
        description=(
            "Recent events, newest first. Filter by type, which accepts either a "
            "whole type such as person.enrolled or a family such as person. "
            "Events mark transitions, not frames: a person who stays in view "
            "produces one event, not one per frame."
        ),
    )
    async def list_events(
        event_type: Optional[str] = None,
        since_minutes: Optional[int] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        token = _require(Permission.EVENTS_READ)
        limit = max(1, min(limit, 200))

        async with async_session_factory() as db:
            conditions = [EventEntity.owner_id == token.owner_id]
            if event_type:
                if "." in event_type:
                    conditions.append(EventEntity.event_name == event_type)
                else:
                    conditions.append(EventEntity.event_name.like(f"{event_type}.%"))
            if since_minutes:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
                conditions.append(EventEntity.occurred_at > cutoff)

            result = await db.execute(
                select(EventEntity)
                .where(*conditions)
                .order_by(EventEntity.occurred_at.desc())
                .limit(limit)
            )
            events = list(result.scalars().all())

        return {"count": len(events), "events": [_event_json(e) for e in events]}

    @server.tool(
        name="get_current_scene",
        description=(
            "What the camera is looking at now, taken from the most recent scene "
            "change. Includes the written description when one was produced. "
            "Returns nothing when no camera has been running."
        ),
    )
    async def get_current_scene() -> Dict[str, Any]:
        token = _require(Permission.EVENTS_READ)

        async with async_session_factory() as db:
            result = await db.execute(
                select(EventEntity)
                .where(
                    EventEntity.owner_id == token.owner_id,
                    EventEntity.event_name == "scene.changed",
                )
                .order_by(EventEntity.occurred_at.desc())
                .limit(1)
            )
            event = result.scalar_one_or_none()

        if event is None:
            return {"scene": None, "note": "No scene has been observed yet"}

        body = event.body or {}
        # The age matters: a scene from yesterday is not what is in view, and an
        # agent has no other way to tell.
        age = (
            (datetime.now(timezone.utc) - event.occurred_at).total_seconds()
            if event.occurred_at
            else None
        )
        return {
            "observedAt": event.occurred_at.isoformat() if event.occurred_at else None,
            "ageSeconds": round(age) if age is not None else None,
            "present": body.get("present", []),
            "description": body.get("description"),
            "camera": body.get("camera"),
        }

    @server.tool(
        name="list_known_subjects",
        description=(
            "The catalog: objects that have been taught and people who have been "
            "recognised. People are listed separately from objects."
        ),
    )
    async def list_known_subjects(include_people: bool = True) -> Dict[str, Any]:
        token = _require(Permission.OBJECTS_READ)

        async with async_session_factory() as db:
            people_category = await db.execute(
                select(CategoryEntity.id).where(
                    CategoryEntity.owner_id == token.owner_id,
                    func.lower(CategoryEntity.name) == settings.person_category_name.lower(),
                )
            )
            people_id = people_category.scalar_one_or_none()

            result = await db.execute(
                select(ObjectEntity)
                .where(ObjectEntity.owner_id == token.owner_id)
                .order_by(ObjectEntity.name)
            )
            entries = list(result.scalars().all())

        people: List[dict] = []
        objects: List[dict] = []
        for entry in entries:
            record = {
                "id": str(entry.id),
                "name": entry.name,
                "description": entry.description,
                "sightings": entry.training_samples,
                "status": entry.status,
            }
            if people_id is not None and entry.category_id == people_id:
                if include_people:
                    people.append(record)
            else:
                objects.append(record)

        return {"objects": objects, "people": people}

    @server.tool(
        name="export_events_otlp",
        description=(
            "Events in the OpenTelemetry OTLP logs envelope, grouped by resource "
            "and instrumentation scope. Use this when the caller wants the raw "
            "structured form to forward to a collector or a tracing backend."
        ),
    )
    async def export_events_otlp(
        since_minutes: int = 60, limit: int = 200
    ) -> Dict[str, Any]:
        token = _require(Permission.EVENTS_READ)
        limit = max(1, min(limit, 1000))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        async with async_session_factory() as db:
            result = await db.execute(
                select(EventEntity)
                .where(
                    EventEntity.owner_id == token.owner_id,
                    EventEntity.occurred_at > cutoff,
                )
                .order_by(EventEntity.occurred_at.desc())
                .limit(limit)
            )
            events = list(result.scalars().all())

        from app.api.routes_events import build_otlp_envelope

        return build_otlp_envelope(events)

    @server.tool(
        name="get_camera",
        description=(
            "Whether a camera is wanted on and whether it is actually running. "
            "Running is decided by frames arriving, not by what was asked for, "
            "so a camera requested with no interface open reports itself as "
            "pending rather than as on."
        ),
    )
    async def get_camera(camera_id: str = camera_control.DEFAULT_CAMERA) -> Dict[str, Any]:
        token = _require(Permission.EVENTS_READ)

        async with async_session_factory() as db:
            state = await camera_control.get_state(db, token.owner_id, camera_id)

        return state.to_dict()

    @server.tool(
        name="start_camera",
        description=(
            "Ask a camera to start. The camera belongs to the interface, so this "
            "records the request and the interface honours it when one is open. "
            "The reply says whether it actually started: pending means nothing "
            "was listening. Requires camera:control on the token."
        ),
    )
    async def start_camera(camera_id: str = camera_control.DEFAULT_CAMERA) -> Dict[str, Any]:
        return await _switch_camera(camera_id, on=True)

    @server.tool(
        name="stop_camera",
        description=(
            "Ask a camera to stop. Requires camera:control on the token."
        ),
    )
    async def stop_camera(camera_id: str = camera_control.DEFAULT_CAMERA) -> Dict[str, Any]:
        return await _switch_camera(camera_id, on=False)

    async def _switch_camera(camera_id: str, on: bool) -> Dict[str, Any]:
        """Record a camera request on behalf of the calling token."""
        if not settings.camera_control_enabled:
            raise NotAuthorised("Camera control is switched off in this deployment")

        token = _require_explicit(Permission.CAMERA_CONTROL)

        async with async_session_factory() as db:
            state = await camera_control.request_state(
                db,
                token.owner_id,
                on=on,
                camera_id=camera_id,
                requested_by=f"token:{token.name}",
            )
            await db.commit()

        result = state.to_dict()
        if state.pending:
            result["note"] = (
                "Requested. No interface is sending frames, so the camera is not "
                "running yet. It starts when one is open on this account."
            )
        return result

    @server.tool(
        name="get_camera_frame",
        description=(
            "The most recent frame from a camera, as a JPEG encoded in base64. "
            "Shows the room rather than reporting on it, so it needs camera:view "
            "written on the token by name; an empty scope list never implies it. "
            "Returns nothing when no interface is sending frames."
        ),
    )
    async def get_camera_frame(
        camera_id: str = camera_control.DEFAULT_CAMERA,
    ) -> Dict[str, Any]:
        if not settings.camera_view_enabled:
            raise NotAuthorised("Live camera viewing is switched off in this deployment")

        token = _require_explicit(Permission.CAMERA_VIEW)

        from app.services.stream_service import get_stream_hub

        frame = get_stream_hub().latest_frame(token.owner_id, camera_id)
        if frame is None:
            async with async_session_factory() as db:
                state = await camera_control.get_state(db, token.owner_id, camera_id)
            result = state.to_dict()
            result["note"] = (
                "No frame is available. The camera belongs to the interface, so "
                "there is nothing to see unless one is open and sending."
            )
            return result

        return {
            "cameraId": camera_id,
            "mediaType": "image/jpeg",
            "bytes": len(frame),
            "base64": base64.b64encode(frame).decode("ascii"),
        }

    @server.tool(
        name="get_stream_info",
        description=(
            "Where to subscribe to this instance: the broker address and topics "
            "when one is configured, and the streaming endpoints with the scope "
            "each of them needs. Requires events:read."
        ),
    )
    async def get_stream_info() -> Dict[str, Any]:
        _require(Permission.EVENTS_READ)

        from app.services.mqtt_service import get_mqtt_publisher

        return {
            "streamEnabled": settings.stream_enabled,
            "cameraViewEnabled": settings.camera_view_enabled,
            "broker": get_mqtt_publisher().describe(),
            "endpoints": {
                "events": f"{settings.api_prefix}/stream/events",
                "camera": f"{settings.api_prefix}/stream/camera/{{cameraId}}",
            },
        }

    @server.tool(
        name="get_status",
        description=(
            "Whether the models are loaded and whether inference is running on "
            "dedicated hardware."
        ),
    )
    async def get_status() -> Dict[str, Any]:
        _require(Permission.EVENTS_READ)

        from app.services.acceleration_service import get_acceleration_service
        from app.services.description_service import get_description_service
        from app.services.segmentation_service import get_segmentation_service

        return {
            "acceleration": get_acceleration_service().report().to_dict(),
            "description": get_description_service().describe_status(),
            "segmentation": get_segmentation_service().describe(),
        }

    return server


_server = None


def get_mcp_server():
    """Get the server singleton, building it on first use."""
    global _server
    if _server is None:
        _server = build_server()
    return _server


async def authenticate(authorization: Optional[str]) -> Optional[IntegrationTokenEntity]:
    """
    Resolve the integration token behind an Authorization header.

    Args:
        authorization: The raw header value, or None.

    Returns:
        The token record, or None when absent or unusable.
    """
    if not authorization:
        return None

    value = authorization
    if value.lower().startswith("bearer "):
        value = value[7:].strip()

    async with async_session_factory() as db:
        token = await resolve_token(db, value)
        if token is not None:
            # Detached from the session so it can outlive it, since the tools
            # each open their own.
            await db.commit()
            db.expunge(token)
        return token
