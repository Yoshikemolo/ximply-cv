"""
Model Context Protocol server.

Lets an external agent ask what the camera has seen: which people and objects
are known, what happened recently, and the events themselves as structured JSON.

The tools are a read only view over the same event layer the webhooks deliver,
so an agent and a subscriber see exactly the same records. Nothing here can
change the catalog, enrol a person or delete anything. An agent that can be
persuaded by the text it reads should not be able to alter what a camera
remembers about people, and read only is the boundary that makes that
impossible rather than merely discouraged.

Authentication is an integration token presented as a bearer credential. The
token carries its own scopes, so an agent can be given the ability to read
events without the ability to read the catalog.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.models.entities import CategoryEntity, EventEntity, IntegrationTokenEntity, ObjectEntity
from app.models.enums import Permission
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
            "Read only access to what a XIMPLY Vision camera has observed. "
            "Events follow the OpenTelemetry logs data model. Use list_events "
            "to see what happened, get_current_scene for what is in view now, "
            "and export_events_otlp when the caller wants the raw envelope."
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
