"""
In-process fan-out for the live stream.

Events and frames are handed here by the detection route and picked up by
whatever is subscribed over HTTP. Nothing is stored anywhere else: the hub
holds one frame per camera, overwritten by the next, and one bounded queue per
subscriber that drops its oldest entry when the subscriber cannot keep up.

A slow subscriber therefore degrades itself and nothing else, and a camera that
nobody is watching is never encoded at all.

See ADR-0022 for the transports and ADR-0023 for what a live frame is allowed
to do.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple
from uuid import UUID

import cv2
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)

# One frame in flight per subscriber. A viewer that falls behind wants the
# newest frame, never a backlog of stale ones.
FRAME_QUEUE_SIZE = 1


class Subscription:
    """
    One subscriber's queue.

    The queue is bounded. When it is full the oldest entry is discarded rather
    than the newest, so a subscriber that recovers sees what is happening now
    instead of replaying what it missed.
    """

    def __init__(self, maxsize: int) -> None:
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, item: Any) -> None:
        """
        Add an item, discarding the oldest if there is no room.

        Args:
            item: The payload to deliver to this subscriber.
        """
        while True:
            try:
                self.queue.put_nowait(item)
                return
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()
                    self.dropped += 1
                except asyncio.QueueEmpty:
                    return


class StreamHub:
    """
    Fan-out for one process.

    Per worker and in memory, like the protocol switch and the acceleration
    preference. Frames arrive from one browser to one worker at a time, and the
    alternative would mean putting images through a shared store, which is
    exactly what ADR-0023 forbids.
    """

    def __init__(self) -> None:
        self._events: Dict[str, List[Subscription]] = {}
        self._frames: Dict[Tuple[str, str], List[Subscription]] = {}
        # The one frame per camera the next frame overwrites. Never persisted.
        self._latest: Dict[Tuple[str, str], np.ndarray] = {}
        self._last_encoded_at: Dict[Tuple[str, str], float] = {}
        self._dropped = 0

    # Events

    def subscribe_events(self, owner_id: UUID) -> Subscription:
        """
        Register a subscriber for this owner's events.

        Args:
            owner_id: The account whose events are wanted.

        Returns:
            The subscription to read from.
        """
        subscription = Subscription(settings.stream_queue_size)
        self._events.setdefault(str(owner_id), []).append(subscription)
        return subscription

    def unsubscribe_events(self, owner_id: UUID, subscription: Subscription) -> None:
        """
        Remove a subscriber and forget the owner when it was the last one.

        Args:
            owner_id: The account the subscription belongs to.
            subscription: The subscription to drop.
        """
        key = str(owner_id)
        holders = self._events.get(key)
        if not holders:
            return
        if subscription in holders:
            holders.remove(subscription)
        if not holders:
            self._events.pop(key, None)

    def publish_event(self, owner_id: UUID, payload: Dict[str, Any]) -> None:
        """
        Hand one record to every subscriber of this owner.

        Returns immediately. Nothing here awaits and nothing here raises, so
        the detection path cannot be delayed or failed by a subscriber.

        Args:
            owner_id: The account the event belongs to.
            payload: The full log record, as delivered to a webhook.
        """
        for subscription in self._events.get(str(owner_id), []):
            before = subscription.dropped
            subscription.offer(payload)
            self._dropped += subscription.dropped - before

    def event_subscribers(self, owner_id: UUID) -> int:
        """
        How many subscribers are reading this owner's events.

        Args:
            owner_id: The account to count for.

        Returns:
            The number of open event subscriptions.
        """
        return len(self._events.get(str(owner_id), []))

    # Frames

    def subscribe_frames(self, owner_id: UUID, camera_id: str) -> Subscription:
        """
        Register a viewer for one camera.

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera to watch.

        Returns:
            The subscription to read encoded frames from.
        """
        subscription = Subscription(FRAME_QUEUE_SIZE)
        self._frames.setdefault((str(owner_id), camera_id), []).append(subscription)
        return subscription

    def unsubscribe_frames(
        self, owner_id: UUID, camera_id: str, subscription: Subscription
    ) -> None:
        """
        Remove a viewer, and drop the encoding throttle with the last one.

        The frame slot itself is left alone: it is overwritten by the next
        frame and cleared when the camera is asked to stop.

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera was being watched.
            subscription: The subscription to drop.
        """
        key = (str(owner_id), camera_id)
        holders = self._frames.get(key)
        if not holders:
            return
        if subscription in holders:
            holders.remove(subscription)
        if not holders:
            self._frames.pop(key, None)
            self._last_encoded_at.pop(key, None)

    def frame_viewers(self, owner_id: UUID, camera_id: str) -> int:
        """
        How many viewers are watching one camera over HTTP.

        The broker is not counted and cannot be: MQTT does not tell a publisher
        who is subscribed. That gap is recorded in SEC-0011.

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera to count for.

        Returns:
            The number of open frame subscriptions.
        """
        return len(self._frames.get((str(owner_id), camera_id), []))

    def offer_frame(self, owner_id: UUID, camera_id: str, frame: np.ndarray) -> None:
        """
        Take the frame detection just used, and publish it if anyone is watching.

        Returns without encoding when the feature is off or nobody is
        subscribed, which is what makes "nothing is published to nobody" cheap
        rather than aspirational.

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera the frame came from.
            frame: The BGR image detection was run on.
        """
        if not settings.camera_view_enabled:
            return

        key = (str(owner_id), camera_id)
        # Held so a one-shot read has something to answer with. Overwritten by
        # the next frame and never written anywhere else.
        self._latest[key] = frame

        holders = self._frames.get(key, [])
        # The broker cannot report subscribers, so publishing to it is opt in
        # on its own and is the one path that sends without knowing whether
        # anybody is listening. See SEC-0011.
        to_broker = settings.mqtt_enabled and settings.mqtt_publish_frames
        if not holders and not to_broker:
            return

        now = time.monotonic()
        interval = 1.0 / max(settings.stream_camera_max_fps, 0.1)
        if now - self._last_encoded_at.get(key, 0.0) < interval:
            return
        self._last_encoded_at[key] = now

        encoded = encode_frame(frame)
        if encoded is None:
            return

        for subscription in holders:
            before = subscription.dropped
            subscription.offer(encoded)
            self._dropped += subscription.dropped - before

        if to_broker:
            from app.services.mqtt_service import get_mqtt_publisher

            get_mqtt_publisher().publish_frame(owner_id, camera_id, encoded)

    def latest_frame(self, owner_id: UUID, camera_id: str) -> Optional[bytes]:
        """
        Encode the most recent frame for a one-shot read.

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera to read.

        Returns:
            The JPEG bytes, or None when no frame has arrived or the feature
            is off.
        """
        if not settings.camera_view_enabled:
            return None
        frame = self._latest.get((str(owner_id), camera_id))
        if frame is None:
            return None
        return encode_frame(frame)

    def forget_camera(self, owner_id: UUID, camera_id: str) -> None:
        """
        Drop the frame held for a camera.

        Called when a camera is asked to stop, so a stopped camera does not
        leave its last frame readable.

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera to forget.
        """
        self._latest.pop((str(owner_id), camera_id), None)

    # State

    @property
    def dropped(self) -> int:
        """
        How many records have been discarded because a subscriber fell behind.

        Returns:
            The count since this process started.
        """
        return self._dropped


def encode_frame(frame: np.ndarray) -> Optional[bytes]:
    """
    Downscale and JPEG encode one frame for the stream.

    The size and quality are the stream's own, not detection's, so a viewer
    cannot pull a larger image than the browser is already sending and cannot
    make the camera work harder.

    Args:
        frame: The BGR image to encode.

    Returns:
        The JPEG bytes, or None when the frame could not be encoded.
    """
    try:
        height, width = frame.shape[:2]
        longest = max(height, width)
        limit = settings.stream_camera_max_side
        if longest > limit:
            scale = limit / float(longest)
            frame = cv2.resize(
                frame,
                (max(int(width * scale), 1), max(int(height * scale), 1)),
                interpolation=cv2.INTER_AREA,
            )
        ok, buffer = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), settings.stream_camera_quality]
        )
        if not ok:
            return None
        return buffer.tobytes()
    except Exception as e:
        logger.warning(f"Frame encoding failed: {e}")
        return None


_hub: Optional[StreamHub] = None


def get_stream_hub() -> StreamHub:
    """
    The hub for this process.

    Returns:
        The singleton stream hub.
    """
    global _hub
    if _hub is None:
        _hub = StreamHub()
    return _hub


def iter_subscription(subscription: Subscription) -> Iterator[Any]:
    """
    Read everything queued without waiting, oldest first.

    Args:
        subscription: The subscription to drain.

    Yields:
        Each queued item.
    """
    while True:
        try:
            yield subscription.queue.get_nowait()
        except asyncio.QueueEmpty:
            return
