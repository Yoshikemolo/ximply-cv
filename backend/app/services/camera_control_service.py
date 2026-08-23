"""
Camera control.

The camera belongs to the browser. Frames are captured there with the device
APIs the browser exposes and posted here for detection, so nothing in this
process can open a camera, and no amount of API surface will change that.

What this module does is hold the state a camera is *wanted* in. The interface
reads it and obeys, which is what lets something other than the person sitting
in front of the screen ask for the camera to start or stop: an agent over the
protocol, a schedule, another service.

Two things are deliberately kept apart:

- The requested state, which is a wish. It is stored, it names who asked, and
  it is honoured only when an interface is open to honour it.
- Whether the camera is actually running, which is a fact. It is never taken on
  trust from whoever made the request: it is stamped by frames arriving for
  detection, so a camera that was asked to start but never did reports itself
  as requested and not running, rather than pretending.

The state lives in the database rather than in memory because the request and
the interface that has to honour it rarely reach the same worker, and a request
that landed on the wrong one would simply never be seen.
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.logging import get_logger
from app.models.entities import CameraControlEntity

logger = get_logger(__name__)

DEFAULT_CAMERA = "default"

# Frames arrive several times a second and each one would otherwise be a write.
# The heartbeat is throttled to the resolution the liveness answer actually
# needs, which is seconds, not frames.
_last_heartbeat: Dict[Tuple[str, str], float] = {}
_heartbeat_lock = threading.Lock()


@dataclass
class CameraState:
    """What a camera was asked to do, and what it is really doing."""

    camera_id: str
    desired_on: bool
    running: bool
    requested_by: Optional[str] = None
    requested_at: Optional[datetime] = None
    last_frame_at: Optional[datetime] = None

    @property
    def pending(self) -> bool:
        """
        Whether the camera was asked to start and has not started.

        True means nothing is listening: no interface is open, or the one that
        is open has not been given permission to the device. It is the honest
        answer to give a caller that has just asked for the camera and would
        otherwise assume it is on.
        """
        return self.desired_on and not self.running

    def to_dict(self) -> dict:
        """The state as it is returned over the API and the protocol."""
        return {
            "cameraId": self.camera_id,
            "desiredOn": self.desired_on,
            "running": self.running,
            "pending": self.pending,
            "requestedBy": self.requested_by,
            "requestedAt": self.requested_at.isoformat() if self.requested_at else None,
            "lastFrameAt": self.last_frame_at.isoformat() if self.last_frame_at else None,
        }


def _is_running(last_frame_at: Optional[datetime]) -> bool:
    """
    Whether frames are still arriving.

    A camera that stopped sending is off, whatever anybody asked for. The grace
    period covers the gap between frames and a slow round trip, and nothing
    more: stretching it would report a closed browser tab as a running camera.
    """
    if last_frame_at is None:
        return False
    age = (datetime.now(timezone.utc) - last_frame_at).total_seconds()
    return age <= settings.camera_live_grace_seconds


async def _row(
    db: AsyncSession,
    owner_id: UUID,
    camera_id: str,
) -> Optional[CameraControlEntity]:
    """The stored control row for one camera, or None when never touched."""
    result = await db.execute(
        select(CameraControlEntity).where(
            CameraControlEntity.owner_id == owner_id,
            CameraControlEntity.camera_id == camera_id,
        )
    )
    return result.scalar_one_or_none()


def _state_of(row: Optional[CameraControlEntity], camera_id: str) -> CameraState:
    """Turn a stored row, or its absence, into a state."""
    if row is None:
        return CameraState(camera_id=camera_id, desired_on=False, running=False)
    return CameraState(
        camera_id=row.camera_id,
        desired_on=bool(row.desired_on),
        running=_is_running(row.last_frame_at),
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        last_frame_at=row.last_frame_at,
    )


async def get_state(
    db: AsyncSession,
    owner_id: UUID,
    camera_id: str = DEFAULT_CAMERA,
) -> CameraState:
    """
    What a camera was asked to do and whether it is doing it.

    Args:
        db: Database session.
        owner_id: Owner of the camera.
        camera_id: Which camera, when the deployment has more than one.

    Returns:
        CameraState: The current state. A camera nobody has ever touched reads
        as off rather than as missing, because that is what it is.
    """
    return _state_of(await _row(db, owner_id, camera_id or DEFAULT_CAMERA), camera_id)


async def request_state(
    db: AsyncSession,
    owner_id: UUID,
    on: bool,
    camera_id: str = DEFAULT_CAMERA,
    requested_by: Optional[str] = None,
) -> CameraState:
    """
    Ask for a camera to be on or off.

    The request is recorded, not performed. Whether it is honoured depends on an
    interface being open, which is why the returned state reports what is
    actually running rather than what was asked for.

    Args:
        db: Database session. The caller owns the transaction.
        owner_id: Owner of the camera.
        on: True to ask for the camera to run, False to ask it to stop.
        camera_id: Which camera.
        requested_by: Who asked, kept so a camera that turned itself on can be
            traced back to the integration that asked for it.

    Returns:
        CameraState: The state after the request.
    """
    camera_id = camera_id or DEFAULT_CAMERA
    now = datetime.now(timezone.utc)

    row = await _row(db, owner_id, camera_id)
    if row is None:
        row = CameraControlEntity(
            id=uuid7(),
            owner_id=owner_id,
            camera_id=camera_id,
        )
        db.add(row)

    row.desired_on = bool(on)
    row.requested_by = requested_by
    row.requested_at = now

    await db.flush()

    logger.info(
        f"Camera {camera_id} requested {'on' if on else 'off'}"
        f"{f' by {requested_by}' if requested_by else ''}"
    )
    return _state_of(row, camera_id)


async def note_frame(
    db: AsyncSession,
    owner_id: UUID,
    camera_id: str = DEFAULT_CAMERA,
) -> None:
    """
    Record that a frame arrived, which is the only proof a camera is running.

    Called from the detection path, so it is on the hot loop and writes at most
    once per heartbeat interval. Failing to record a heartbeat must never cost a
    frame its detection, so errors are swallowed: the cost of losing one is that
    the camera reads as stopped a few seconds early.

    Args:
        db: Database session. The caller owns the transaction.
        owner_id: Owner of the camera.
        camera_id: Which camera the frame came from.
    """
    camera_id = camera_id or DEFAULT_CAMERA
    key = (str(owner_id), camera_id)
    now = time.time()

    with _heartbeat_lock:
        last = _last_heartbeat.get(key, 0.0)
        if now - last < settings.camera_heartbeat_seconds:
            return
        _last_heartbeat[key] = now

    try:
        row = await _row(db, owner_id, camera_id)
        if row is None:
            # Frames arriving from a camera nobody asked for is the normal case:
            # somebody pressed the button in the interface. The row is created
            # so the state is readable, and it records what is true, which is
            # that the camera is on.
            row = CameraControlEntity(
                id=uuid7(),
                owner_id=owner_id,
                camera_id=camera_id,
                desired_on=True,
            )
            db.add(row)

        row.last_frame_at = datetime.now(timezone.utc)
        await db.flush()
    except Exception as e:
        with _heartbeat_lock:
            _last_heartbeat.pop(key, None)
        logger.debug(f"Could not record the camera heartbeat: {e}")
