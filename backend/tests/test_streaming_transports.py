"""
What goes on the broker, and who is allowed to watch.

Three defects this pins. A topic that changes shape silently breaks every
subscriber that was written against the documented tree. A queue that grows
when the broker is unreachable turns an outage into a memory leak. And a scope
list that is empty must never be read as consent to look through a camera,
which is the rule ADR-0021 set for control and ADR-0023 extends to viewing:
every token issued before the capability existed has an empty list.

See ADR-0022, ADR-0023 and SEC-0011.
"""

from uuid_extensions import uuid7

import json
import pytest

from app.core.config import settings
from app.core.stream_auth import token_scope_allows
from app.models.enums import Permission
from app.services.mqtt_service import (
    Message,
    MqttPublisher,
    capture_topic,
    event_topic,
    frame_topic,
    status_topic,
)

OWNER = uuid7()
PREFIX = "ximply"
INSTANCE = "default"


class FakeEvent:
    """
    The parts of an event the delivery payload reads.

    A stand-in rather than a real entity, because the payload builder is plain
    Python and reaching for a database would only test the container.
    """

    def __init__(self, event_name: str = "person.arrived", capture_path=None) -> None:
        self.id = uuid7()
        self.event_name = event_name
        self.timestamp_nanos = 1_700_000_000_000_000_000
        self.observed_timestamp_nanos = 1_700_000_000_000_000_001
        self.severity_number = 9
        self.severity_text = "INFO"
        self.trace_id = None
        self.span_id = None
        self.body = {"subject": "Dani"}
        self.attributes = {"event.name": event_name}
        self.resource = {"service.name": "ximply-vision"}
        self.scope_name = "ximply.vision"
        self.scope_version = "1.0.0"
        self.occurred_at = None
        self.capture_path = capture_path


def queued_messages(publisher: MqttPublisher) -> list:
    """
    Everything waiting to be published, oldest first.

    The queue is reached in one place rather than in every test, so what the
    publisher exposes and what the suite pokes at stay easy to tell apart.

    Args:
        publisher: The publisher to drain.

    Returns:
        The queued messages.
    """
    queue = publisher._ensure_queue()
    drained = []
    while not queue.empty():
        drained.append(queue.get_nowait())
    return drained


@pytest.fixture
def broker(monkeypatch) -> MqttPublisher:
    """A publisher with the broker switched on and nothing connected to it."""
    monkeypatch.setattr(settings, "mqtt_enabled", True)
    monkeypatch.setattr(settings, "mqtt_topic_prefix", PREFIX)
    monkeypatch.setattr(settings, "mqtt_instance", INSTANCE)
    monkeypatch.setattr(settings, "mqtt_publish_captures", True)
    monkeypatch.setattr(settings, "mqtt_publish_frames", True)
    monkeypatch.setattr(settings, "mqtt_queue_size", 8)
    return MqttPublisher()


class TestTheTopicTreeIsTheDocumentedOne:
    """
    Every subscriber is written against these strings.

    They are documented in FEAT-0015 and in the API reference, and a change
    here breaks a `mosquitto_sub` line somebody pasted into a script months
    ago. The owner segment matters on its own: it is what a broker ACL is
    written against.
    """

    async def test_an_event_goes_to_its_owner_and_type(self):
        topic = event_topic(PREFIX, INSTANCE, OWNER, "person.arrived")

        assert topic == f"ximply/default/events/{OWNER}/person.arrived"

    async def test_a_capture_goes_to_its_owner_and_event(self):
        event_id = uuid7()

        topic = capture_topic(PREFIX, INSTANCE, OWNER, event_id)

        assert topic == f"ximply/default/captures/{OWNER}/{event_id}"

    async def test_a_frame_goes_to_its_owner_and_camera(self):
        topic = frame_topic(PREFIX, INSTANCE, OWNER, "front")

        assert topic == f"ximply/default/camera/{OWNER}/front/frame"

    async def test_the_status_topic_is_shared_by_the_instance(self):
        assert status_topic(PREFIX, INSTANCE) == "ximply/default/status"

    async def test_two_instances_do_not_collide(self):
        first = event_topic(PREFIX, "kitchen", OWNER, "scene.changed")
        second = event_topic(PREFIX, "garage", OWNER, "scene.changed")

        assert first != second


class TestAnEventCarriesTheSameRecordAsAWebhook:
    """
    A receiver written for one transport must read the other.

    Both are built by delivery_payload for that reason. If the broker grew its
    own serialisation the two would drift, and the promise made in ADR-0022
    would quietly stop being true.
    """

    async def test_the_queued_payload_is_the_full_log_record(self, broker):
        event = FakeEvent()

        broker.dispatch(OWNER, [event])

        payload = json.loads(queued_messages(broker)[0].payload.decode("utf-8"))
        assert payload["id"] == str(event.id)
        assert payload["eventName"] == "person.arrived"
        assert payload["body"] == {"subject": "Dani"}
        assert payload["severityText"] == "INFO"

    async def test_an_event_is_published_at_least_once(self, broker):
        broker.dispatch(OWNER, [FakeEvent()])

        assert queued_messages(broker)[0].qos == 1

    async def test_a_capture_is_queued_by_path_not_by_value(self, broker):
        event = FakeEvent(capture_path="events/owner/id.jpg")

        queued = broker.dispatch(OWNER, [event])

        assert queued == 2
        capture = queued_messages(broker)[1]
        assert capture.capture_path == "events/owner/id.jpg"
        assert capture.payload is None
        assert capture.qos == 0

    async def test_captures_can_be_left_off(self, broker, monkeypatch):
        monkeypatch.setattr(settings, "mqtt_publish_captures", False)

        queued = broker.dispatch(OWNER, [FakeEvent(capture_path="events/x.jpg")])

        assert queued == 1

    async def test_nothing_is_queued_when_the_broker_is_off(self, broker, monkeypatch):
        monkeypatch.setattr(settings, "mqtt_enabled", False)

        assert broker.dispatch(OWNER, [FakeEvent()]) == 0
        assert broker.queued == 0


class TestAnUnreachableBrokerCostsABoundedAmount:
    """
    An outage must not become a memory leak.

    Nothing drains the queue while the broker is gone, so the queue is what
    absorbs the outage. It is bounded, it drops the oldest entry, and it counts
    what it lost so the interface can say a subscriber is missing data.
    """

    async def test_the_queue_never_grows_past_its_bound(self, broker):
        for index in range(50):
            broker.enqueue(Message(topic=f"t/{index}", payload=b"x"))

        assert broker.queued == settings.mqtt_queue_size

    async def test_what_was_lost_is_counted(self, broker):
        for index in range(12):
            broker.enqueue(Message(topic=f"t/{index}", payload=b"x"))

        assert broker.dropped == 12 - settings.mqtt_queue_size

    async def test_the_newest_message_survives(self, broker):
        for index in range(12):
            broker.enqueue(Message(topic=f"t/{index}", payload=b"x"))

        topics = [message.topic for message in queued_messages(broker)]

        assert topics[-1] == "t/11"

    async def test_frames_are_off_unless_asked_for(self, broker, monkeypatch):
        monkeypatch.setattr(settings, "mqtt_publish_frames", False)

        broker.publish_frame(OWNER, "default", b"jpeg")

        assert broker.queued == 0

    async def test_a_frame_is_published_without_redelivery(self, broker):
        broker.publish_frame(OWNER, "default", b"jpeg")

        message = queued_messages(broker)[0]
        assert message.qos == 0
        assert message.retain is False
        assert message.payload == b"jpeg"

    async def test_the_description_reports_what_was_lost(self, broker):
        for index in range(12):
            broker.enqueue(Message(topic=f"t/{index}", payload=b"x"))

        described = broker.describe()

        assert described["dropped"] == 4
        assert described["connected"] is False
        assert described["topics"]["status"] == "ximply/default/status"


class TestWatchingIsGrantedByNameOrNotAtAll:
    """
    An empty scope list must never imply permission to look through a camera.

    Every token issued before camera:view existed has an empty or narrower
    list. Reading consent into that silence would hand a live view of a room to
    integrations created to watch events, which is precisely the reasoning
    ADR-0021 wrote down for camera:control.
    """

    async def test_an_empty_list_inherits_reading(self):
        assert token_scope_allows([], Permission.EVENTS_READ, explicit=False) is True

    async def test_an_empty_list_never_inherits_watching(self):
        assert token_scope_allows([], Permission.CAMERA_VIEW, explicit=True) is False

    async def test_a_named_scope_is_granted(self):
        scopes = ["events:read", "camera:view"]

        assert token_scope_allows(scopes, Permission.CAMERA_VIEW, explicit=True) is True

    async def test_control_does_not_carry_viewing(self):
        scopes = ["camera:control"]

        assert token_scope_allows(scopes, Permission.CAMERA_VIEW, explicit=True) is False

    async def test_viewing_does_not_carry_control(self):
        scopes = ["camera:view"]

        assert (
            token_scope_allows(scopes, Permission.CAMERA_CONTROL, explicit=True) is False
        )

    async def test_a_narrow_list_refuses_what_it_does_not_name(self):
        scopes = ["objects:read"]

        assert token_scope_allows(scopes, Permission.EVENTS_READ, explicit=False) is False
