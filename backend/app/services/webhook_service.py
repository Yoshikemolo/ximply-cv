"""
Webhook delivery.

Sends events to the clients that asked for them, signed so the receiver can
prove the request came from this instance and was not altered on the way.

Signing uses HMAC-SHA256 over the exact bytes of the body, with a secret unique
to each subscription. SHA-1 is not used: collisions against it have been
practical since 2017, and the cost of the stronger digest is nothing here.

Delivery never blocks detection. A frame that raises an event returns to the
camera immediately and the send happens afterwards, because a subscriber that
takes ten seconds to answer must not slow down the video.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import List, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.entities import EventEntity, WebhookSubscriptionEntity

logger = get_logger(__name__)

SIGNATURE_HEADER = "X-Ximply-Signature"
TIMESTAMP_HEADER = "X-Ximply-Timestamp"
EVENT_HEADER = "X-Ximply-Event"
DELIVERY_HEADER = "X-Ximply-Delivery"
ALGORITHM = "sha256"


def generate_secret() -> str:
    """
    Create a secret for a new subscription.

    Thirty two random bytes, hex encoded. Long enough that guessing is not a
    consideration, and printable so it can be pasted into a receiver's
    configuration.
    """
    return secrets.token_hex(32)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """
    Sign a delivery.

    The timestamp is inside the signed material, not merely sent alongside it.
    Signing the body alone lets an observer replay a valid request forever;
    binding the time to it means a receiver can reject anything stale.

    Args:
        secret: The subscription secret.
        timestamp: Unix seconds, as a string, as sent in the timestamp header.
        body: The exact bytes of the request body.

    Returns:
        The signature, prefixed with the algorithm that produced it so the
        format can change later without breaking existing receivers.
    """
    material = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return f"{ALGORITHM}={digest}"


def verify(secret: str, timestamp: str, body: bytes, signature: str, tolerance: int = 300) -> bool:
    """
    Check a delivery, the way a receiver would.

    Provided so the documented examples can be tested against the same code
    that produces the signature, rather than against a second implementation
    that might disagree with it.

    Args:
        secret: The subscription secret.
        timestamp: Value of the timestamp header.
        body: The exact bytes received.
        signature: Value of the signature header.
        tolerance: How many seconds of clock skew and delay to allow.

    Returns:
        bool: True when the signature is valid and recent.
    """
    try:
        age = abs(time.time() - float(timestamp))
    except (TypeError, ValueError):
        return False

    if age > tolerance:
        return False

    expected = sign(secret, timestamp, body)
    # Constant time, so a wrong signature cannot be discovered byte by byte
    # from how long the comparison took.
    return hmac.compare_digest(expected, signature)


def _delivery_payload(event: EventEntity) -> dict:
    """
    The JSON a subscriber receives.

    The whole log record, not just its body, so a receiver that already handles
    OpenTelemetry data can consume a delivery without a translation step, and
    one that does not can read the body and ignore the rest.
    """
    return {
        "id": str(event.id),
        "eventName": event.event_name,
        "timeUnixNano": str(event.timestamp_nanos),
        "observedTimeUnixNano": str(event.observed_timestamp_nanos),
        "severityNumber": event.severity_number,
        "severityText": event.severity_text,
        "traceId": event.trace_id,
        "spanId": event.span_id,
        "body": event.body,
        "attributes": event.attributes,
        "resource": event.resource,
        "scope": {"name": event.scope_name, "version": event.scope_version},
        "occurredAt": event.occurred_at.isoformat() if event.occurred_at else None,
    }


class WebhookService:
    """Delivers events to subscriptions and records how that went."""

    def _wants(self, subscription: WebhookSubscriptionEntity, event_type: str) -> bool:
        """
        Whether a subscription asked for this event type.

        An empty filter means everything. A filter entry matches either the
        whole type or its family, so subscribing to "person" delivers
        "person.enrolled" and anything added to that family later.
        """
        wanted = subscription.event_types or []
        if not wanted:
            return True
        family = event_type.split(".")[0]
        return any(entry == event_type or entry == family for entry in wanted)

    async def _deliver_one(
        self,
        subscription: WebhookSubscriptionEntity,
        event_id: UUID,
        event_type: str,
        payload: dict,
    ) -> tuple:
        """
        Send one event to one subscription, retrying on failure.

        Returns:
            Tuple of (status code or None, error message or None).
        """
        import httpx

        # Serialised once and sent byte for byte, because the signature is over
        # these exact bytes. Re-encoding before sending would invalidate it.
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        timestamp = str(int(time.time()))

        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(subscription.secret, timestamp, body),
            TIMESTAMP_HEADER: timestamp,
            EVENT_HEADER: event_type,
            DELIVERY_HEADER: str(event_id),
            "User-Agent": "XimplyVision-Webhook/1.0",
        }

        last_error: Optional[str] = None
        status: Optional[int] = None

        for attempt in range(settings.webhook_max_attempts):
            try:
                async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
                    response = await client.post(subscription.url, content=body, headers=headers)
                status = response.status_code
                if 200 <= status < 300:
                    return status, None
                last_error = f"HTTP {status}"
            except Exception as e:
                last_error = str(e)

            # Back off between attempts so a receiver that is briefly down is
            # given room to recover rather than being hammered.
            if attempt + 1 < settings.webhook_max_attempts:
                await asyncio.sleep(2 ** attempt)

        return status, last_error

    async def dispatch(
        self,
        db: AsyncSession,
        owner_id: UUID,
        events: Sequence[EventEntity],
    ) -> int:
        """
        Deliver a batch of events to every matching subscription.

        Args:
            db: Database session, used for the subscription list and the health
                fields. The caller owns the transaction.
            owner_id: Whose subscriptions to consider.
            events: Events to deliver.

        Returns:
            int: Number of successful deliveries.
        """
        if not settings.webhooks_enabled or not events:
            return 0

        result = await db.execute(
            select(WebhookSubscriptionEntity).where(
                WebhookSubscriptionEntity.owner_id == owner_id,
                WebhookSubscriptionEntity.is_active.is_(True),
            )
        )
        subscriptions: List[WebhookSubscriptionEntity] = list(result.scalars().all())
        if not subscriptions:
            return 0

        delivered = 0

        for subscription in subscriptions:
            for event in events:
                if not self._wants(subscription, event.event_name):
                    continue

                status, error = await self._deliver_one(
                    subscription, event.id, event.event_name, _delivery_payload(event)
                )

                subscription.last_delivery_at = datetime.now(timezone.utc)
                subscription.last_status = status
                subscription.last_error = error

                if error is None:
                    subscription.failure_count = 0
                    delivered += 1
                else:
                    subscription.failure_count += 1
                    logger.warning(
                        f"Webhook delivery to {subscription.name} failed: {error}"
                    )
                    # A permanently broken endpoint is switched off rather than
                    # retried forever, and says so in the interface.
                    if subscription.failure_count >= settings.webhook_disable_after_failures:
                        subscription.is_active = False
                        logger.warning(
                            f"Webhook {subscription.name} disabled after "
                            f"{subscription.failure_count} consecutive failures"
                        )

        return delivered


_webhook_service: Optional[WebhookService] = None


def get_webhook_service() -> WebhookService:
    """Get the webhook service singleton."""
    global _webhook_service
    if _webhook_service is None:
        _webhook_service = WebhookService()
    return _webhook_service
