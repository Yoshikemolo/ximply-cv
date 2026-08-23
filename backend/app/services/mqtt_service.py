"""
Publishes what this instance observes to an MQTT broker.

The topic builders are plain functions so they can be tested without a broker.
The payload is the one the webhook path already builds, so the two transports
cannot drift apart.

Publishing happens on a background task fed by a bounded queue. A broker that
is down, slow or gone costs a bounded amount of memory and no detection
latency, which is the property that matters: the camera keeps working when the
thing listening to it does not. See ADR-0022.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import settings
from app.models.entities import EventEntity
from app.services.webhook_service import delivery_payload

logger = logging.getLogger(__name__)

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"

# How long to wait before reconnecting, and the ceiling that backoff climbs to.
RECONNECT_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 30.0


def event_topic(prefix: str, instance: str, owner_id: UUID, event_type: str) -> str:
    """
    Where one event record is published.

    The owner is in the path so a broker ACL can be written per account. This
    application does not enforce that separation; see SEC-0011.

    Args:
        prefix: The topic root, from MQTT_TOPIC_PREFIX.
        instance: This deployment's name, from MQTT_INSTANCE.
        owner_id: The account the event belongs to.
        event_type: The event name, such as person.arrived.

    Returns:
        The topic to publish on.
    """
    return f"{prefix}/{instance}/events/{owner_id}/{event_type}"


def capture_topic(prefix: str, instance: str, owner_id: UUID, event_id: UUID) -> str:
    """
    Where the image belonging to one event is published.

    Args:
        prefix: The topic root, from MQTT_TOPIC_PREFIX.
        instance: This deployment's name, from MQTT_INSTANCE.
        owner_id: The account the event belongs to.
        event_id: The event the capture was taken for.

    Returns:
        The topic to publish on.
    """
    return f"{prefix}/{instance}/captures/{owner_id}/{event_id}"


def frame_topic(prefix: str, instance: str, owner_id: UUID, camera_id: str) -> str:
    """
    Where the live frames of one camera are published.

    Args:
        prefix: The topic root, from MQTT_TOPIC_PREFIX.
        instance: This deployment's name, from MQTT_INSTANCE.
        owner_id: The account that owns the camera.
        camera_id: Which camera the frames come from.

    Returns:
        The topic to publish on.
    """
    return f"{prefix}/{instance}/camera/{owner_id}/{camera_id}/frame"


def status_topic(prefix: str, instance: str) -> str:
    """
    Where this instance says whether it is running.

    Args:
        prefix: The topic root, from MQTT_TOPIC_PREFIX.
        instance: This deployment's name, from MQTT_INSTANCE.

    Returns:
        The topic to publish on.
    """
    return f"{prefix}/{instance}/status"


@dataclass
class Message:
    """
    One thing waiting to be published.

    A capture carries a path rather than bytes: fetching the image from object
    storage is I/O, and doing it here would put that I/O on the detection
    request the way ADR-0022 says publishing must not.
    """

    topic: str
    payload: Optional[bytes] = None
    qos: int = 0
    retain: bool = False
    capture_path: Optional[str] = None


class MqttPublisher:
    """
    Owns the broker connection and the outbound queue.

    One task rather than several, because ordering within a topic is worth more
    here than throughput: frames are already lossy by design and events are
    already rare.
    """

    def __init__(self) -> None:
        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._connected = False
        self._dropped = 0
        self._published = 0

    @property
    def connected(self) -> bool:
        """
        Whether the broker connection is currently up.

        Returns:
            True when the last connection attempt succeeded and still holds.
        """
        return self._connected

    @property
    def dropped(self) -> int:
        """
        How many messages were discarded because the queue was full.

        Returns:
            The count since this process started.
        """
        return self._dropped

    @property
    def published(self) -> int:
        """
        How many messages reached the broker.

        Returns:
            The count since this process started.
        """
        return self._published

    async def start(self) -> None:
        """
        Begin publishing, if the deployment asked for a broker.

        Never raises. A broker that cannot be reached is a warning in the log
        and a disconnected publisher, not a failed startup.
        """
        if not settings.mqtt_enabled or self._task is not None:
            return
        self._queue = asyncio.Queue(maxsize=settings.mqtt_queue_size)
        self._task = asyncio.create_task(self._run(), name="mqtt-publisher")
        logger.info(
            f"Broker publishing enabled: {settings.mqtt_host}:{settings.mqtt_port}"
        )

    async def stop(self) -> None:
        """
        Stop publishing and let the connection close.

        The status topic is a last will, so a connection that ends without a
        goodbye still leaves the broker holding the right answer.
        """
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Broker publisher stopped with an error: {e}")
        self._connected = False

    def enqueue(self, message: Message) -> None:
        """
        Hand one message to the publisher without waiting for it.

        Drops the oldest entry when the queue is full and counts the loss. The
        stream is a live view, not a second record: what was observed is in the
        database whatever happens here.

        Args:
            message: What to publish.
        """
        queue = self._queue
        if queue is None:
            return
        while True:
            try:
                queue.put_nowait(message)
                return
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    self._dropped += 1
                except asyncio.QueueEmpty:
                    return

    def dispatch(self, owner_id: UUID, events: List[EventEntity]) -> int:
        """
        Queue every event, and the captures belonging to them.

        Returns immediately. Called from the detection route inside the guard
        that keeps the event layer from ever failing a frame.

        Args:
            owner_id: The account the events belong to.
            events: The events this frame raised.

        Returns:
            How many messages were queued.
        """
        if not settings.mqtt_enabled or self._queue is None or not events:
            return 0

        prefix = settings.mqtt_topic_prefix
        instance = settings.mqtt_instance
        queued = 0
        for event in events:
            payload = json.dumps(
                delivery_payload(event), separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            self.enqueue(
                Message(
                    topic=event_topic(prefix, instance, owner_id, event.event_name),
                    payload=payload,
                    qos=1,
                )
            )
            queued += 1

            if settings.mqtt_publish_captures and event.capture_path:
                self.enqueue(
                    Message(
                        topic=capture_topic(prefix, instance, owner_id, event.id),
                        capture_path=event.capture_path,
                        qos=0,
                    )
                )
                queued += 1
        return queued

    def publish_frame(self, owner_id: UUID, camera_id: str, jpeg: bytes) -> None:
        """
        Queue one live frame.

        Off unless MQTT_PUBLISH_FRAMES is set, because a broker cannot say
        whether anybody is watching and this is the one path that publishes
        without knowing (SEC-0011).

        Args:
            owner_id: The account that owns the camera.
            camera_id: Which camera the frame came from.
            jpeg: The encoded frame.
        """
        if not settings.mqtt_enabled or not settings.mqtt_publish_frames:
            return
        self.enqueue(
            Message(
                topic=frame_topic(
                    settings.mqtt_topic_prefix,
                    settings.mqtt_instance,
                    owner_id,
                    camera_id,
                ),
                payload=jpeg,
                qos=0,
            )
        )

    def describe(self) -> Dict[str, Any]:
        """
        What the interface shows about the broker.

        Returns:
            Whether it is enabled and connected, where it is, and the topic
            templates a subscriber needs.
        """
        prefix = settings.mqtt_topic_prefix
        instance = settings.mqtt_instance
        return {
            "enabled": settings.mqtt_enabled,
            "connected": self._connected,
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
            "instance": instance,
            "publishesCaptures": settings.mqtt_publish_captures,
            "publishesFrames": settings.mqtt_publish_frames,
            "published": self._published,
            "dropped": self._dropped,
            "topics": {
                "events": f"{prefix}/{instance}/events/{{owner}}/{{type}}",
                "captures": f"{prefix}/{instance}/captures/{{owner}}/{{event}}",
                "camera": f"{prefix}/{instance}/camera/{{owner}}/{{camera}}/frame",
                "status": status_topic(prefix, instance),
            },
        }

    async def _run(self) -> None:
        """
        Connect, publish what is queued, and reconnect when the broker goes.
        """
        import aiomqtt

        prefix = settings.mqtt_topic_prefix
        instance = settings.mqtt_instance
        status = status_topic(prefix, instance)
        delay = RECONNECT_SECONDS

        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    username=settings.mqtt_username or None,
                    password=settings.mqtt_password or None,
                    identifier=f"{settings.mqtt_client_id}-{instance}",
                    keepalive=settings.mqtt_keepalive,
                    will=aiomqtt.Will(
                        topic=status,
                        payload=STATUS_OFFLINE.encode("utf-8"),
                        qos=1,
                        retain=True,
                    ),
                ) as client:
                    self._connected = True
                    delay = RECONNECT_SECONDS
                    logger.info(f"Broker connected: {settings.mqtt_host}")
                    await client.publish(
                        status, STATUS_ONLINE.encode("utf-8"), qos=1, retain=True
                    )
                    await self._drain(client)
            except asyncio.CancelledError:
                self._connected = False
                raise
            except Exception as e:
                self._connected = False
                logger.warning(f"Broker connection lost: {e}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    async def _drain(self, client: Any) -> None:
        """
        Publish queued messages until the connection fails.

        Args:
            client: The connected broker client.
        """
        queue = self._queue
        if queue is None:
            return
        while True:
            message = await queue.get()
            payload = message.payload
            if payload is None and message.capture_path:
                payload = await self._read_capture(message.capture_path)
            if payload is None:
                continue
            await client.publish(
                message.topic, payload, qos=message.qos, retain=message.retain
            )
            self._published += 1

    async def _read_capture(self, path: str) -> Optional[bytes]:
        """
        Fetch a stored capture, off the event loop.

        Args:
            path: The object storage path recorded on the event.

        Returns:
            The image bytes, or None when it could not be read.
        """
        from app.core.minio_client import download_file

        try:
            return await asyncio.to_thread(download_file, path)
        except Exception as e:
            logger.warning(f"Capture could not be read for the broker: {e}")
            return None


_publisher: Optional[MqttPublisher] = None


def get_mqtt_publisher() -> MqttPublisher:
    """
    The publisher for this process.

    Returns:
        The singleton broker publisher.
    """
    global _publisher
    if _publisher is None:
        _publisher = MqttPublisher()
    return _publisher
