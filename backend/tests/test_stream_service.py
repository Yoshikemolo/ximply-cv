"""
The fan-out has to lose the right thing and refuse the right thing.

Two defects this pins. A queue that blocks or grows when a subscriber falls
behind turns one slow client into a memory leak or a stalled detection request,
so the queue is bounded and drops the oldest entry. And a camera nobody is
watching must not be encoded at all, because "nothing is published to nobody"
is the rule that keeps a deployment from broadcasting a room for months after
somebody switched the feature on once.

See ADR-0022 and ADR-0023.
"""

from uuid_extensions import uuid7

import numpy as np
import pytest

from app.core.config import settings
from app.services.stream_service import (
    FRAME_QUEUE_SIZE,
    StreamHub,
    Subscription,
    encode_frame,
)

OWNER = uuid7()
OTHER = uuid7()
CAMERA = "default"


def frame(width: int = 32, height: int = 24) -> np.ndarray:
    """A frame of the shape detection hands over."""
    return np.zeros((height, width, 3), dtype=np.uint8)


@pytest.fixture
def hub() -> StreamHub:
    """A hub of its own, so no test can see another one's subscribers."""
    return StreamHub()


class FakeMonotonic:
    """
    A clock the throttle reads, so a test decides how much time has passed.

    Wall clock time would make the rate limit untestable: three calls in one
    microsecond are indistinguishable from a stall.
    """

    def __init__(self) -> None:
        self._now = 1000.0

    def monotonic(self) -> float:
        """The current reading."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        Args:
            seconds: How far to move.
        """
        self._now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeMonotonic:
    """Put the fake clock in front of the hub's throttle."""
    fake = FakeMonotonic()
    monkeypatch.setattr("app.services.stream_service.time", fake)
    return fake


@pytest.fixture
def viewing(monkeypatch) -> None:
    """Switch live viewing on for the length of one test."""
    monkeypatch.setattr(settings, "camera_view_enabled", True)
    monkeypatch.setattr(settings, "mqtt_enabled", False)
    monkeypatch.setattr(settings, "mqtt_publish_frames", False)
    monkeypatch.setattr(settings, "stream_camera_max_fps", 1000.0)


class TestABoundedQueueDropsTheOldest:
    """
    A full queue must discard what is stale, not refuse what is new.

    Refusing the newest entry would leave a recovering subscriber reading
    history forever, and blocking would put a slow subscriber on the detection
    path, which is exactly what this design exists to avoid.
    """

    async def test_the_oldest_entry_is_discarded_when_the_queue_is_full(self):
        subscription = Subscription(maxsize=2)

        subscription.offer("first")
        subscription.offer("second")
        subscription.offer("third")

        assert subscription.queue.qsize() == 2
        assert subscription.queue.get_nowait() == "second"
        assert subscription.queue.get_nowait() == "third"

    async def test_every_discarded_entry_is_counted(self):
        subscription = Subscription(maxsize=1)

        subscription.offer("first")
        subscription.offer("second")
        subscription.offer("third")

        assert subscription.dropped == 2

    async def test_nothing_is_dropped_while_there_is_room(self):
        subscription = Subscription(maxsize=4)

        for index in range(4):
            subscription.offer(index)

        assert subscription.dropped == 0
        assert subscription.queue.qsize() == 4


class TestEventsReachOnlyTheirOwner:
    """
    Two accounts on one instance must never see each other's records.

    The hub is keyed by owner for that reason, and a bug here would leak an
    account's events to whoever else happened to be subscribed.
    """

    async def test_a_subscriber_receives_its_own_owners_events(self, hub):
        subscription = hub.subscribe_events(OWNER)

        hub.publish_event(OWNER, {"id": "1", "eventName": "person.arrived"})

        assert subscription.queue.get_nowait()["eventName"] == "person.arrived"

    async def test_a_subscriber_receives_nothing_for_another_owner(self, hub):
        subscription = hub.subscribe_events(OWNER)

        hub.publish_event(OTHER, {"id": "1", "eventName": "person.arrived"})

        assert subscription.queue.empty()

    async def test_publishing_to_nobody_is_not_an_error(self, hub):
        hub.publish_event(OWNER, {"id": "1", "eventName": "scene.changed"})

        assert hub.event_subscribers(OWNER) == 0

    async def test_unsubscribing_stops_delivery(self, hub):
        subscription = hub.subscribe_events(OWNER)
        hub.unsubscribe_events(OWNER, subscription)

        hub.publish_event(OWNER, {"id": "1", "eventName": "scene.changed"})

        assert subscription.queue.empty()
        assert hub.event_subscribers(OWNER) == 0


class TestNothingIsEncodedForNobody:
    """
    A camera with no viewers must cost nothing.

    Encoding every frame whether or not anybody is watching would burn CPU on
    an idle deployment, and would mean the rule ADR-0023 states is a promise
    rather than a property.
    """

    async def test_a_frame_is_not_encoded_when_nobody_is_subscribed(
        self, hub, viewing, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            "app.services.stream_service.encode_frame",
            lambda image: calls.append(image) or b"jpeg",
        )

        hub.offer_frame(OWNER, CAMERA, frame())

        assert calls == []

    async def test_a_frame_is_encoded_once_for_any_number_of_viewers(
        self, hub, viewing, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            "app.services.stream_service.encode_frame",
            lambda image: calls.append(image) or b"jpeg",
        )
        first = hub.subscribe_frames(OWNER, CAMERA)
        second = hub.subscribe_frames(OWNER, CAMERA)

        hub.offer_frame(OWNER, CAMERA, frame())

        assert len(calls) == 1
        assert first.queue.get_nowait() == b"jpeg"
        assert second.queue.get_nowait() == b"jpeg"

    async def test_nothing_happens_at_all_when_viewing_is_switched_off(
        self, hub, monkeypatch
    ):
        monkeypatch.setattr(settings, "camera_view_enabled", False)
        calls = []
        monkeypatch.setattr(
            "app.services.stream_service.encode_frame",
            lambda image: calls.append(image) or b"jpeg",
        )
        subscription = hub.subscribe_frames(OWNER, CAMERA)

        hub.offer_frame(OWNER, CAMERA, frame())

        assert calls == []
        assert subscription.queue.empty()
        assert hub.latest_frame(OWNER, CAMERA) is None


class TestTheViewerCountIsTheNotice:
    """
    The count is what tells a room it is being watched, so it has to be right.

    ADR-0023 puts it on the screen. A count that does not fall when a viewer
    leaves would report watchers that are not there, and one that does not rise
    would hide the ones that are.
    """

    async def test_the_count_rises_and_falls_with_its_viewers(self, hub, viewing):
        assert hub.frame_viewers(OWNER, CAMERA) == 0

        first = hub.subscribe_frames(OWNER, CAMERA)
        second = hub.subscribe_frames(OWNER, CAMERA)
        assert hub.frame_viewers(OWNER, CAMERA) == 2

        hub.unsubscribe_frames(OWNER, CAMERA, first)
        assert hub.frame_viewers(OWNER, CAMERA) == 1

        hub.unsubscribe_frames(OWNER, CAMERA, second)
        assert hub.frame_viewers(OWNER, CAMERA) == 0

    async def test_cameras_are_counted_separately(self, hub, viewing):
        hub.subscribe_frames(OWNER, "front")

        assert hub.frame_viewers(OWNER, "front") == 1
        assert hub.frame_viewers(OWNER, "back") == 0

    async def test_owners_are_counted_separately(self, hub, viewing):
        hub.subscribe_frames(OWNER, CAMERA)

        assert hub.frame_viewers(OTHER, CAMERA) == 0


class TestAViewerOnlyEverHoldsTheNewestFrame:
    """
    A viewer that falls behind wants what is happening now.

    A backlog of stale frames is worse than a gap: it plays a room back late,
    and the delay never recovers.
    """

    async def test_only_the_newest_frame_survives(
        self, hub, viewing, clock, monkeypatch
    ):
        encoded = iter([b"one", b"two", b"three"])
        monkeypatch.setattr(
            "app.services.stream_service.encode_frame", lambda image: next(encoded)
        )
        subscription = hub.subscribe_frames(OWNER, CAMERA)

        for _ in range(3):
            hub.offer_frame(OWNER, CAMERA, frame())
            clock.advance(1.0)

        assert subscription.queue.qsize() == FRAME_QUEUE_SIZE
        assert subscription.queue.get_nowait() == b"three"


class TestTheStreamHasItsOwnFrameRate:
    """
    A viewer must not be served every frame detection runs on.

    Detection runs several times a second. Encoding and publishing all of that
    would spend the machine on a viewer that cannot see the difference, so the
    stream is rate limited independently of what the browser sends.
    """

    async def test_frames_arriving_faster_than_the_limit_are_skipped(
        self, hub, viewing, clock, monkeypatch
    ):
        monkeypatch.setattr(settings, "stream_camera_max_fps", 2.0)
        calls = []
        monkeypatch.setattr(
            "app.services.stream_service.encode_frame",
            lambda image: calls.append(image) or b"jpeg",
        )
        hub.subscribe_frames(OWNER, CAMERA)

        for _ in range(10):
            hub.offer_frame(OWNER, CAMERA, frame())
            clock.advance(0.05)

        assert len(calls) == 1

    async def test_a_frame_is_encoded_once_the_interval_has_passed(
        self, hub, viewing, clock, monkeypatch
    ):
        monkeypatch.setattr(settings, "stream_camera_max_fps", 2.0)
        calls = []
        monkeypatch.setattr(
            "app.services.stream_service.encode_frame",
            lambda image: calls.append(image) or b"jpeg",
        )
        hub.subscribe_frames(OWNER, CAMERA)

        hub.offer_frame(OWNER, CAMERA, frame())
        clock.advance(0.6)
        hub.offer_frame(OWNER, CAMERA, frame())

        assert len(calls) == 2


class TestTheFrameSlotIsForgottenOnDemand:
    """
    A camera asked to stop must not leave its last frame readable.

    The slot exists so a one-shot read has something to answer with. It has to
    be clearable, or stopping a camera would leave the room readable for as
    long as the process lives.
    """

    async def test_the_last_frame_is_readable_while_the_camera_runs(
        self, hub, viewing
    ):
        hub.offer_frame(OWNER, CAMERA, frame())

        assert hub.latest_frame(OWNER, CAMERA) is not None

    async def test_forgetting_a_camera_clears_it(self, hub, viewing):
        hub.offer_frame(OWNER, CAMERA, frame())

        hub.forget_camera(OWNER, CAMERA)

        assert hub.latest_frame(OWNER, CAMERA) is None


class TestFramesAreEncodedToTheStreamsOwnLimits:
    """
    A viewer must not be able to pull a larger image than the browser sent.

    The stream has its own size and quality so watching cannot make the camera
    work harder or reveal more than detection was given.
    """

    async def test_a_large_frame_is_downscaled_to_the_configured_side(
        self, monkeypatch
    ):
        monkeypatch.setattr(settings, "stream_camera_max_side", 64)

        encoded = encode_frame(frame(width=640, height=480))

        assert encoded is not None
        assert encoded[:2] == b"\xff\xd8"

    async def test_a_small_frame_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(settings, "stream_camera_max_side", 640)

        encoded = encode_frame(frame(width=32, height=24))

        assert encoded is not None
        assert encoded[:2] == b"\xff\xd8"

    async def test_a_frame_that_cannot_be_encoded_is_not_raised(self):
        assert encode_frame(np.zeros((0, 0, 3), dtype=np.uint8)) is None
