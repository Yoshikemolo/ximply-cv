"""
Events and webhook subscriptions.

The read side of the event layer, and the management of the clients that
receive it. Everything here is scoped to the authenticated owner: an event
belongs to whoever's camera raised it, and a subscription to whoever created it.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.core.logging import get_logger
from app.core.minio_client import download_file
from app.core.security import TokenData
from app.models.entities import EventEntity, WebhookSubscriptionEntity
from app.models.enums import Permission
from app.models.schemas import CamelCaseModel, MessageResponse, PaginatedResponse
from app.services.event_service import EVENT_TYPES, get_event_service
from app.services.webhook_service import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    generate_secret,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/events", tags=["Events"])


class EventResponse(CamelCaseModel):
    """
    One recorded event, as an OpenTelemetry log record.

    Field names follow the specification so a consumer that already speaks OTLP
    needs no mapping. The convenience fields at the end are projections of the
    attributes, offered because reading a dotted key out of a map is tedious
    for a client that only wants the subject.
    """

    id: UUID
    event_name: str
    timestamp_nanos: int
    observed_timestamp_nanos: int
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    severity_number: int
    severity_text: str
    body: dict
    attributes: dict
    resource: dict
    scope_name: str
    scope_version: Optional[str] = None

    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    confidence: Optional[float] = None
    camera_id: Optional[str] = None
    capture_path: Optional[str] = None
    capture_url: Optional[str] = None
    occurred_at: datetime


class WebhookCreate(BaseModel):
    """A new subscription."""

    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=1000)
    # Empty means every type. An entry may be a whole type or just its family,
    # so "person" delivers every person event including ones added later.
    event_types: List[str] = []


class WebhookUpdate(BaseModel):
    """Changes to an existing subscription."""

    name: Optional[str] = None
    url: Optional[str] = None
    event_types: Optional[List[str]] = None
    is_active: Optional[bool] = None


class WebhookResponse(CamelCaseModel):
    """A subscription, with its delivery health."""

    id: UUID
    name: str
    url: str
    event_types: List[str] = []
    is_active: bool
    last_delivery_at: Optional[datetime] = None
    last_status: Optional[int] = None
    last_error: Optional[str] = None
    failure_count: int
    created_at: datetime
    # Present only in the response that creates it or rotates it. The secret is
    # never returned again: a value that can be read back at any time is a value
    # that leaks through every screen it is displayed on.
    secret: Optional[str] = None


def _to_event(event: EventEntity) -> EventResponse:
    """Build the response for one event."""
    return EventResponse(
        id=event.id,
        event_name=event.event_name,
        timestamp_nanos=event.timestamp_nanos,
        observed_timestamp_nanos=event.observed_timestamp_nanos,
        trace_id=event.trace_id,
        span_id=event.span_id,
        severity_number=event.severity_number,
        severity_text=event.severity_text,
        body=event.body,
        attributes=event.attributes,
        resource=event.resource,
        scope_name=event.scope_name,
        scope_version=event.scope_version,
        subject_id=event.subject_id,
        subject_name=event.subject_name,
        confidence=event.confidence,
        camera_id=event.camera_id,
        capture_path=event.capture_path,
        capture_url=(
            f"/api/v1/events/{event.id}/capture" if event.capture_path else None
        ),
        occurred_at=event.occurred_at,
    )


@router.get("", response_model=PaginatedResponse[EventResponse])
async def list_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    event_type: Optional[str] = Query(None, alias="type"),
    since: Optional[datetime] = None,
    subject_id: Optional[UUID] = None,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EventResponse]:
    """
    List events, newest first.

    `type` accepts a whole type or a family, so `person` returns every person
    event. `since` is the usual way to poll: ask for everything after the last
    event already seen.
    """
    owner_id = UUID(current_user.sub)
    conditions = [EventEntity.owner_id == owner_id]

    if event_type:
        if "." in event_type:
            conditions.append(EventEntity.event_name == event_type)
        else:
            conditions.append(EventEntity.event_name.like(f"{event_type}.%"))
    if since:
        conditions.append(EventEntity.occurred_at > since)
    if subject_id:
        conditions.append(EventEntity.subject_id == subject_id)

    total = await db.scalar(select(func.count(EventEntity.id)).where(*conditions))

    result = await db.execute(
        select(EventEntity)
        .where(*conditions)
        .order_by(EventEntity.occurred_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    items = [_to_event(event) for event in result.scalars().all()]
    total = total or 0

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/otlp")
async def export_otlp(
    since: Optional[datetime] = None,
    limit: int = Query(500, ge=1, le=5000),
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Export events in the OTLP logs envelope.

    Grouped by resource and by instrumentation scope, which is the structure an
    OTLP consumer expects, so the result can be posted to a collector or read by
    any backend that already ingests logs without a translation step.
    """
    conditions = [EventEntity.owner_id == UUID(current_user.sub)]
    if since:
        conditions.append(EventEntity.occurred_at > since)

    result = await db.execute(
        select(EventEntity)
        .where(*conditions)
        .order_by(EventEntity.occurred_at.desc())
        .limit(limit)
    )
    events = list(result.scalars().all())

    def to_any_value(value):
        """Wrap a Python value in the OTLP AnyValue shape."""
        if isinstance(value, bool):
            return {"boolValue": value}
        if isinstance(value, int):
            return {"intValue": str(value)}
        if isinstance(value, float):
            return {"doubleValue": value}
        if isinstance(value, list):
            return {"arrayValue": {"values": [to_any_value(v) for v in value]}}
        if isinstance(value, dict):
            return {
                "kvlistValue": {
                    "values": [
                        {"key": k, "value": to_any_value(v)} for k, v in value.items()
                    ]
                }
            }
        return {"stringValue": str(value)}

    def to_attributes(mapping: dict) -> list:
        return [{"key": k, "value": to_any_value(v)} for k, v in (mapping or {}).items()]

    # Records sharing a resource and a scope belong in the same group, which is
    # what the envelope exists to express.
    groups: dict = {}
    for event in events:
        key = (
            tuple(sorted((event.resource or {}).items())),
            event.scope_name,
            event.scope_version,
        )
        groups.setdefault(key, []).append(event)

    resource_logs = []
    for (resource_items, scope_name, scope_version), grouped in groups.items():
        resource_logs.append(
            {
                "resource": {"attributes": to_attributes(dict(resource_items))},
                "scopeLogs": [
                    {
                        "scope": {"name": scope_name, "version": scope_version},
                        "logRecords": [
                            {
                                "timeUnixNano": str(e.timestamp_nanos),
                                "observedTimeUnixNano": str(e.observed_timestamp_nanos),
                                "severityNumber": e.severity_number,
                                "severityText": e.severity_text,
                                "eventName": e.event_name,
                                "body": to_any_value(e.body),
                                "attributes": to_attributes(e.attributes),
                                **({"traceId": e.trace_id} if e.trace_id else {}),
                                **({"spanId": e.span_id} if e.span_id else {}),
                            }
                            for e in grouped
                        ],
                    }
                ],
            }
        )

    return {"resourceLogs": resource_logs}


@router.get("/types")
async def list_event_types(
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_READ])),
) -> dict:
    """The event types this instance can raise, for building a subscription."""
    return {
        "types": EVENT_TYPES,
        "families": sorted({t.split(".")[0] for t in EVENT_TYPES}),
    }


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    """One event by id."""
    result = await db.execute(
        select(EventEntity).where(
            EventEntity.id == event_id,
            EventEntity.owner_id == UUID(current_user.sub),
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return _to_event(event)


@router.get("/{event_id}/capture")
async def get_event_capture(
    event_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    The frame that produced an event.

    Unlike the catalog image proxy, this one requires the read permission: an
    event capture is a photograph of whoever happened to be in front of the
    camera, and there is no reason for it to be readable by anyone with the URL.
    """
    result = await db.execute(
        select(EventEntity).where(
            EventEntity.id == event_id,
            EventEntity.owner_id == UUID(current_user.sub),
        )
    )
    event = result.scalar_one_or_none()
    if event is None or not event.capture_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture not found")

    data = download_file(event.capture_path)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture not found")

    from io import BytesIO

    return StreamingResponse(BytesIO(data), media_type="image/jpeg")


@router.delete("/prune", response_model=MessageResponse)
async def prune_events(
    older_than_days: Optional[int] = Query(None, ge=0),
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Delete events older than a cutoff.

    The software has no retention policy of its own, so this is how a deployment
    with an obligation enforces one.
    """
    days = settings.events_retention_days if older_than_days is None else older_than_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        delete(EventEntity).where(
            EventEntity.owner_id == UUID(current_user.sub),
            EventEntity.occurred_at < cutoff,
        )
    )
    await db.commit()

    removed = result.rowcount or 0
    logger.info(f"Pruned {removed} events older than {days} days")
    return MessageResponse(message=f"Deleted {removed} events older than {days} days")


# ==============================================================================
# Webhook subscriptions
# ==============================================================================

webhooks = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _to_webhook(
    subscription: WebhookSubscriptionEntity, secret: Optional[str] = None
) -> WebhookResponse:
    """Build the response for one subscription, with the secret only when new."""
    return WebhookResponse(
        id=subscription.id,
        name=subscription.name,
        url=subscription.url,
        event_types=subscription.event_types or [],
        is_active=subscription.is_active,
        last_delivery_at=subscription.last_delivery_at,
        last_status=subscription.last_status,
        last_error=subscription.last_error,
        failure_count=subscription.failure_count,
        created_at=subscription.created_at,
        secret=secret,
    )


@webhooks.get("", response_model=List[WebhookResponse])
async def list_webhooks(
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> List[WebhookResponse]:
    """Every subscription belonging to the authenticated owner."""
    result = await db.execute(
        select(WebhookSubscriptionEntity)
        .where(WebhookSubscriptionEntity.owner_id == UUID(current_user.sub))
        .order_by(WebhookSubscriptionEntity.created_at)
    )
    return [_to_webhook(s) for s in result.scalars().all()]


@webhooks.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    data: WebhookCreate,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """
    Register a client and generate its secret.

    The secret is returned once, here. It is not readable afterwards, so it has
    to be copied now or rotated later.
    """
    unknown = [
        t
        for t in data.event_types
        if t not in EVENT_TYPES and t not in {e.split(".")[0] for e in EVENT_TYPES}
    ]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown event types: {', '.join(unknown)}",
        )

    secret = generate_secret()
    subscription = WebhookSubscriptionEntity(
        id=uuid7(),
        name=data.name.strip(),
        url=data.url.strip(),
        secret=secret,
        event_types=data.event_types or None,
        is_active=True,
        owner_id=UUID(current_user.sub),
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)

    logger.info(f"Webhook subscription created: {subscription.name}")
    return _to_webhook(subscription, secret=secret)


@webhooks.put("/{subscription_id}", response_model=WebhookResponse)
async def update_webhook(
    subscription_id: UUID,
    data: WebhookUpdate,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Change a subscription, including switching it on or off."""
    result = await db.execute(
        select(WebhookSubscriptionEntity).where(
            WebhookSubscriptionEntity.id == subscription_id,
            WebhookSubscriptionEntity.owner_id == UUID(current_user.sub),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    if data.name is not None:
        subscription.name = data.name.strip()
    if data.url is not None:
        subscription.url = data.url.strip()
    if data.event_types is not None:
        subscription.event_types = data.event_types or None
    if data.is_active is not None:
        subscription.is_active = data.is_active
        if data.is_active:
            # Re-enabling clears the failure count, or a subscription disabled
            # for failing would switch itself off again on the next error.
            subscription.failure_count = 0

    await db.commit()
    await db.refresh(subscription)
    return _to_webhook(subscription)


@webhooks.post("/{subscription_id}/rotate", response_model=WebhookResponse)
async def rotate_webhook_secret(
    subscription_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """
    Replace the secret and return the new one.

    Deliveries are signed with the new secret from the next event onwards, so
    the receiver must be updated before rotating or it will reject them.
    """
    result = await db.execute(
        select(WebhookSubscriptionEntity).where(
            WebhookSubscriptionEntity.id == subscription_id,
            WebhookSubscriptionEntity.owner_id == UUID(current_user.sub),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    secret = generate_secret()
    subscription.secret = secret
    await db.commit()
    await db.refresh(subscription)

    logger.info(f"Webhook secret rotated: {subscription.name}")
    return _to_webhook(subscription, secret=secret)


@webhooks.post("/{subscription_id}/test", response_model=MessageResponse)
async def test_webhook(
    subscription_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Send a signed test delivery, so a receiver can be verified before it matters.
    """
    from app.services.webhook_service import get_webhook_service

    result = await db.execute(
        select(WebhookSubscriptionEntity).where(
            WebhookSubscriptionEntity.id == subscription_id,
            WebhookSubscriptionEntity.owner_id == UUID(current_user.sub),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    service = get_webhook_service()
    event_id = uuid7()
    payload = {
        "type": "test",
        "message": "Test delivery from XIMPLY Vision",
        "occurredAt": datetime.now(timezone.utc).isoformat(),
    }
    status_code, error = await service._deliver_one(subscription, event_id, "test", payload)

    subscription.last_delivery_at = datetime.now(timezone.utc)
    subscription.last_status = status_code
    subscription.last_error = error
    await db.commit()

    if error:
        return MessageResponse(message=f"Test delivery failed: {error}")
    return MessageResponse(message=f"Test delivery accepted with HTTP {status_code}")


@webhooks.delete("/{subscription_id}", response_model=MessageResponse)
async def delete_webhook(
    subscription_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Remove a subscription."""
    result = await db.execute(
        select(WebhookSubscriptionEntity).where(
            WebhookSubscriptionEntity.id == subscription_id,
            WebhookSubscriptionEntity.owner_id == UUID(current_user.sub),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    await db.delete(subscription)
    await db.commit()
    return MessageResponse(message="Subscription deleted")


@webhooks.get("/headers")
async def delivery_headers(
    current_user: TokenData = Depends(require_permissions([Permission.EVENTS_MANAGE])),
) -> dict:
    """
    The headers a delivery carries, so a receiver can be written against them
    without reading this source.
    """
    return {
        "signature": SIGNATURE_HEADER,
        "timestamp": TIMESTAMP_HEADER,
        "event": EVENT_HEADER,
        "delivery": DELIVERY_HEADER,
        "algorithm": "HMAC-SHA256 over the timestamp, a full stop, and the raw body",
    }
