"""
The event layer.

Turns what the camera observes into records another system can subscribe to.

Records follow the OpenTelemetry logs data model rather than a shape invented
here, so an event can be exported to any collector or backend that speaks OTLP
and correlated with traces from the rest of a system. Severity numbers follow
the specified bands: 9 to 12 is informational, which is what an observation is.

The single rule that shapes everything here is that an event marks a
**transition**, never a frame. Detection runs several times a second. Emitting
per frame would produce tens of thousands of identical records an hour, drown
any subscriber, and make the word "event" meaningless. A person who walks in and
stays for ten minutes produces one recognition event, not three thousand.

Transitions are tracked per owner and camera in memory. The state is
deliberately not persisted: after a restart the first frame re-announces what is
in view, which is the behaviour a subscriber wants anyway, since it has no way
of knowing what happened while the service was down.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.logging import get_logger
from app.core.minio_client import upload_file
from app.models.entities import EventEntity

# Instrumentation scope, as the specification names it: what produced the record.
SCOPE_NAME = "app.services.event_service"
SCOPE_VERSION = "1.0.0"

# An observation is informational. The band is 9 to 12; 9 is its floor.
SEVERITY_INFO = 9
SEVERITY_INFO_TEXT = "INFO"

# Nanoseconds are the unit the specification requires, and a timestamp column
# holds microseconds. Converting through this rather than through a float keeps
# the two consistent instead of rounding them apart.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# The last microsecond handed out, so no two records can share one.
_last_stamp_us = 0
_stamp_lock = threading.Lock()


def _distinct_stamp(now_ns: int) -> datetime:
    """
    The storable timestamp for a record, never equal to the one before it.

    The column readers sort by holds microseconds, and the records raised by one
    frame are built a few microseconds apart at most. Two of them landing in the
    same microsecond would leave them unorderable against each other, which is
    the defect this column was fixed to remove, so a collision is pushed forward
    by the smallest amount the column can represent.

    The nanosecond fields the specification requires are not touched. They carry
    the clock as it was read; this is the projection of it that has to be unique
    to be useful.

    Args:
        now_ns: Nanoseconds since the epoch, as read from the clock.

    Returns:
        datetime: The instant to store, at microsecond resolution.
    """
    global _last_stamp_us

    micros = now_ns // 1000
    with _stamp_lock:
        if micros <= _last_stamp_us:
            micros = _last_stamp_us + 1
        _last_stamp_us = micros

    return _EPOCH + timedelta(microseconds=micros)


def _resource() -> dict:
    """
    Attributes describing what emitted the record.

    Uses the standard service attribute names so a collector groups these with
    everything else the same deployment sends.
    """
    return {
        "service.name": settings.app_name,
        "service.version": settings.app_version,
        "service.namespace": "ximply",
    }

logger = get_logger(__name__)


# Event types. The first segment is the family, which is what a subscriber
# filters on, so a new type in an existing family needs no subscriber change.
PERSON_ENROLLED = "person.enrolled"
PERSON_RECOGNISED = "person.recognised"
PERSON_DEPARTED = "person.departed"
OBJECT_RECOGNISED = "object.recognised"
SCENE_CHANGED = "scene.changed"

EVENT_TYPES = [
    PERSON_ENROLLED,
    PERSON_RECOGNISED,
    PERSON_DEPARTED,
    OBJECT_RECOGNISED,
    SCENE_CHANGED,
]


@dataclass
class SceneState:
    """What was in view the last time a frame was processed."""

    present: Set[str] = field(default_factory=set)
    signature: str = ""
    last_seen: Dict[str, float] = field(default_factory=dict)
    # The last known description of each subject, so a departure event can name
    # who left rather than reporting an opaque identity key.
    subjects: Dict[str, dict] = field(default_factory=dict)
    last_scene_event: float = 0.0


class EventService:
    """
    Emits events on transitions and persists them.

    Delivery to subscribers is a separate concern and lives in the webhook
    service, which reads what this writes.
    """

    def __init__(self) -> None:
        self._scenes: Dict[Tuple[str, str], SceneState] = {}
        self._lock = threading.Lock()

    def _state(self, owner_id: UUID, camera_id: Optional[str]) -> SceneState:
        """State for one owner and camera, created on first use."""
        key = (str(owner_id), camera_id or "default")
        with self._lock:
            if key not in self._scenes:
                self._scenes[key] = SceneState()
            return self._scenes[key]

    def reset(self, owner_id: UUID, camera_id: Optional[str] = None) -> None:
        """
        Forget what was in view, so the next frame re-announces everything.

        Called when a stream stops, since a subscriber should hear about the
        room again when the camera is pointed at it a second time.
        """
        key = (str(owner_id), camera_id or "default")
        with self._lock:
            self._scenes.pop(key, None)

    async def _record(
        self,
        db: AsyncSession,
        owner_id: UUID,
        event_type: str,
        body: dict,
        subject_id: Optional[UUID] = None,
        subject_name: Optional[str] = None,
        confidence: Optional[float] = None,
        camera_id: Optional[str] = None,
        capture_path: Optional[str] = None,
        extra_attributes: Optional[dict] = None,
    ) -> EventEntity:
        """
        Persist one event as an OpenTelemetry log record.

        Attributes are flat and dotted, as the semantic conventions require, and
        are the form anything downstream reads. The domain columns carry the
        same values only so the database can index them.

        Every timestamp on the record comes from one instant, taken here. The
        column is filled explicitly rather than left to the database default,
        because that default is now(), which in PostgreSQL is the start of the
        transaction: every event raised by one frame would share it, leaving
        them unorderable, and it would sit before the moment being recorded.
        Readers sort and age events by this column, so it has to be the time of
        the observation.
        """
        now_ns = time.time_ns()
        occurred_at = _distinct_stamp(now_ns)
        body = {**body, "occurredAt": occurred_at.isoformat()}

        attributes = {
            "event.name": event_type,
            "ximply.owner.id": str(owner_id),
        }
        if subject_id is not None:
            attributes["ximply.subject.id"] = str(subject_id)
        if subject_name is not None:
            attributes["ximply.subject.name"] = subject_name
        if confidence is not None:
            attributes["ximply.subject.confidence"] = round(float(confidence), 4)
        if camera_id is not None:
            attributes["ximply.camera.id"] = camera_id
        if capture_path is not None:
            attributes["ximply.capture.path"] = capture_path
        if extra_attributes:
            attributes.update(extra_attributes)

        event = EventEntity(
            id=uuid7(),
            event_name=event_type,
            timestamp_nanos=now_ns,
            observed_timestamp_nanos=now_ns,
            severity_number=SEVERITY_INFO,
            severity_text=SEVERITY_INFO_TEXT,
            body=body,
            attributes=attributes,
            resource=_resource(),
            scope_name=SCOPE_NAME,
            scope_version=SCOPE_VERSION,
            owner_id=owner_id,
            subject_id=subject_id,
            subject_name=subject_name,
            confidence=confidence,
            camera_id=camera_id,
            capture_path=capture_path,
            occurred_at=occurred_at,
        )
        db.add(event)
        return event

    def _store_capture(
        self,
        owner_id: UUID,
        event_id: UUID,
        frame: Optional[np.ndarray],
    ) -> Optional[str]:
        """
        Keep the frame that produced an event.

        An event that says a stranger appeared is worth far more with the
        picture attached, and a subscriber cannot ask for it afterwards because
        the frame is gone by then.

        Args:
            owner_id: Owner the capture belongs to.
            event_id: Event the capture is attached to.
            frame: Full BGR frame, or None to store nothing.

        Returns:
            The object store path, or None when nothing was stored.
        """
        if frame is None or not settings.events_store_captures:
            return None

        try:
            import cv2
            from PIL import Image

            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

            # A capture is evidence, not a source image. Full sensor resolution
            # would multiply the storage an active camera consumes for no gain.
            longest = max(image.size)
            if longest > settings.events_capture_max_side:
                ratio = settings.events_capture_max_side / longest
                image = image.resize(
                    (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))
                )

            buffer = BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=85)
            buffer.seek(0)

            path = f"events/{owner_id}/{event_id}.jpg"
            if upload_file(buffer, path, "image/jpeg"):
                return path
        except Exception as e:
            logger.warning(f"Could not store the capture for event {event_id}: {e}")

        return None

    async def observe(
        self,
        db: AsyncSession,
        owner_id: UUID,
        detections: Sequence,
        frame: Optional[np.ndarray] = None,
        camera_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> List[EventEntity]:
        """
        Compare this frame against the last one and emit what changed.

        Args:
            db: Database session. The caller owns the transaction.
            owner_id: Whose camera this is.
            detections: Detection results for the frame.
            frame: The frame itself, kept as the capture for any event raised.
            camera_id: Which camera, when the deployment has more than one.
            description: The scene description, when one is available.

        Returns:
            The events raised by this frame, which is usually none.
        """
        if not settings.events_enabled:
            return []

        state = self._state(owner_id, camera_id)
        now = time.time()

        # A detection identifies a subject by its catalog entry when recognised,
        # and by its class otherwise. An unrecognised bottle is "a bottle", and a
        # second bottle does not raise a second event.
        current: Dict[str, dict] = {}
        for detection in detections:
            identity = detection.object_id or f"class:{detection.label.lower()}"
            entry = current.get(identity)
            confidence = (
                detection.match_confidence
                if detection.object_id and detection.match_confidence is not None
                else detection.confidence
            )
            if entry is None or confidence > entry["confidence"]:
                current[identity] = {
                    "identity": identity,
                    "objectId": str(detection.object_id) if detection.object_id else None,
                    "name": detection.object_name or detection.label,
                    "label": detection.label,
                    "confidence": float(confidence),
                    "isPerson": detection.label.lower() == "person",
                }

        present = set(current)
        appeared = present - state.present
        # A subject is only gone once it has been missing for a grace period, or
        # a single dropped frame would raise a departure and an arrival.
        departed = {
            identity
            for identity in state.present - present
            if now - state.last_seen.get(identity, now) > settings.events_absence_seconds
        }

        events: List[EventEntity] = []
        capture_path: Optional[str] = None
        capture_event_id: Optional[UUID] = None

        for identity in sorted(appeared):
            subject = current[identity]
            if subject["isPerson"]:
                # A brand new person is reported with certainty by the
                # recogniser, since they are whoever this sighting is. That is
                # what distinguishes an enrolment from a recognition here.
                event_type = (
                    PERSON_ENROLLED
                    if subject["objectId"] and subject["confidence"] >= 0.999
                    else PERSON_RECOGNISED
                )
            elif subject["objectId"]:
                event_type = OBJECT_RECOGNISED
            else:
                # An unrecognised class is not news on its own. It shows up in
                # the scene change instead.
                continue

            event = await self._record(
                db,
                owner_id=owner_id,
                event_type=event_type,
                subject_id=UUID(subject["objectId"]) if subject["objectId"] else None,
                subject_name=subject["name"],
                confidence=subject["confidence"],
                camera_id=camera_id,
                body={
                    "type": event_type,
                    "subject": {
                        "id": subject["objectId"],
                        "name": subject["name"],
                        "class": subject["label"],
                        "confidence": round(subject["confidence"], 4),
                    },
                    "camera": camera_id,
                },
            )
            events.append(event)
            if capture_event_id is None:
                capture_event_id = event.id

        for identity in sorted(departed):
            state.last_seen.pop(identity, None)
            subject = state.subjects.pop(identity, None)

            # Only a subject worth announcing on arrival is worth announcing on
            # departure. An unrecognised class never raised an arrival, so it
            # must not raise a departure either.
            if subject is None or not (subject["isPerson"] or subject["objectId"]):
                continue

            event = await self._record(
                db,
                owner_id=owner_id,
                event_type=PERSON_DEPARTED,
                subject_id=UUID(subject["objectId"]) if subject["objectId"] else None,
                subject_name=subject["name"],
                camera_id=camera_id,
                body={
                    "type": PERSON_DEPARTED,
                    "subject": {
                        "id": subject["objectId"],
                        "name": subject["name"],
                        "class": subject["label"],
                    },
                    "camera": camera_id,
                },
            )
            events.append(event)

        # The floor between scene events delays an announcement, it never
        # cancels one. The remembered signature therefore advances only when the
        # event is actually raised: advancing it here as well would mark the
        # change as told while nothing was told, and since the scene then stays
        # as it is, no later frame would differ from it and the transition would
        # be lost for good. That is what leaves a reader looking at an empty
        # room while somebody stands in front of the camera.
        signature = "|".join(sorted(subject["name"] for subject in current.values()))
        scene_differs = signature != state.signature
        within_floor = now - state.last_scene_event < settings.events_scene_min_interval

        if scene_differs and not within_floor:
            event = await self._record(
                db,
                owner_id=owner_id,
                event_type=SCENE_CHANGED,
                camera_id=camera_id,
                body={
                    "type": SCENE_CHANGED,
                    "present": [
                        {
                            "id": subject["objectId"],
                            "name": subject["name"],
                            "class": subject["label"],
                            "confidence": round(subject["confidence"], 4),
                        }
                        for subject in sorted(current.values(), key=lambda s: s["name"])
                    ],
                    "description": description,
                    "camera": camera_id,
                },
            )
            events.append(event)
            state.last_scene_event = now
            state.signature = signature
            if capture_event_id is None:
                capture_event_id = event.id

        if events and capture_event_id is not None:
            capture_path = self._store_capture(owner_id, capture_event_id, frame)
            if capture_path:
                for event in events:
                    if event.id == capture_event_id:
                        event.capture_path = capture_path
                        event.body = {**event.body, "capture": capture_path}
                        event.attributes = {
                            **event.attributes,
                            "ximply.capture.path": capture_path,
                        }

        state.present = present
        for identity, subject in current.items():
            state.last_seen[identity] = now
            state.subjects[identity] = subject

        if events:
            logger.info(
                f"Raised {len(events)} event(s): {', '.join(e.event_name for e in events)}"
            )

        return events


_event_service: Optional[EventService] = None


def get_event_service() -> EventService:
    """Get the event service singleton."""
    global _event_service
    if _event_service is None:
        _event_service = EventService()
    return _event_service
