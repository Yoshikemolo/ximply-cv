"""
Tests for the event layer.

Both defects covered here were invisible from the application. Nothing crashed,
no request failed, and the interface looked correct. They were found by reading
the event stream back and noticing it described a room that did not exist.
That is exactly the kind of defect that returns, so it is pinned here.

See ADR-0014 and ADR-0020.
"""

from uuid_extensions import uuid7

import pytest

from app.core.config import settings
from app.services.event_service import EventService, SCENE_CHANGED

from .conftest import FakeDetection


OWNER = uuid7()


def scene_events(events):
    """Only the scene changes among what one frame raised."""
    return [e for e in events if e.event_name == SCENE_CHANGED]


def present_names(event):
    """The names a scene change reports as being in view."""
    return [subject["name"] for subject in event.body["present"]]


class TestSceneFloorDelaysRatherThanDrops:
    """
    The floor between scene events bounds how often a subscriber hears. It must
    not decide which changes a subscriber is told about.

    The defect: the remembered signature advanced even when the floor blocked
    the event, marking a change as announced when nothing had been. The scene
    then stayed as it was, so no later frame differed from the stored signature
    and the transition was never raised at all. A reader was left looking at an
    empty room while somebody stood in front of the camera.
    """

    async def test_a_change_blocked_by_the_floor_is_raised_afterwards(
        self, session, clock
    ):
        service = EventService()
        floor = settings.events_scene_min_interval

        occupied = await service.observe(session, OWNER, [FakeDetection("person")])
        assert present_names(scene_events(occupied)[0]) == ["person"]

        clock.advance(floor)
        emptied = await service.observe(session, OWNER, [])
        assert present_names(scene_events(emptied)[0]) == []

        # Inside the floor. Nothing may be raised, and nothing may be forgotten:
        # this is the frame whose change used to be swallowed.
        clock.advance(floor / 10)
        blocked = await service.observe(session, OWNER, [FakeDetection("person")])
        assert scene_events(blocked) == []

        # Past the floor, with the room unchanged since the blocked frame. The
        # change is still owed, because the last thing announced was an empty
        # room and the room is not empty.
        clock.advance(floor)
        raised = await service.observe(session, OWNER, [FakeDetection("person")])
        assert present_names(scene_events(raised)[0]) == ["person"]

    async def test_a_scene_already_announced_is_not_announced_again(
        self, session, clock
    ):
        service = EventService()

        first = await service.observe(session, OWNER, [FakeDetection("person")])
        assert len(scene_events(first)) == 1

        clock.advance(settings.events_scene_min_interval * 2)
        again = await service.observe(session, OWNER, [FakeDetection("person")])
        assert scene_events(again) == []

    async def test_the_floor_reports_the_scene_as_it_stands_when_it_lifts(
        self, session, clock
    ):
        """
        A scene that changed twice inside the floor is announced once, with what
        is there by the time it lifts rather than what was there first.
        """
        service = EventService()
        floor = settings.events_scene_min_interval

        await service.observe(session, OWNER, [FakeDetection("person")])

        clock.advance(floor)
        await service.observe(session, OWNER, [])

        clock.advance(floor / 10)
        await service.observe(session, OWNER, [FakeDetection("person")])

        clock.advance(floor / 10)
        await service.observe(session, OWNER, [FakeDetection("bottle")])

        clock.advance(floor)
        raised = await service.observe(session, OWNER, [FakeDetection("bottle")])
        assert present_names(scene_events(raised)[0]) == ["bottle"]


class TestRecordsCarryTheTimeTheyWereObserved:
    """
    occurred_at is what list_events and get_current_scene sort by, what since
    filters on, and what the reported scene age is measured from.

    The defect: it was left to server_default=func.now(), which in PostgreSQL is
    the start of the transaction. Every event written together shared a
    timestamp, so they could not be ordered against each other, and it preceded
    the work that produced them.
    """

    async def test_every_event_from_one_frame_is_stamped_distinctly(
        self, session, clock
    ):
        service = EventService()

        events = await service.observe(
            session,
            OWNER,
            [FakeDetection("person", object_id=uuid7(), object_name="Jorge")],
        )

        assert len(events) > 1, "this frame should raise an arrival and a scene change"
        stamps = [e.occurred_at for e in events]
        assert len(set(stamps)) == len(stamps)
        assert stamps == sorted(stamps)

    async def test_the_column_agrees_with_the_specified_fields(self, session, clock):
        service = EventService()

        events = await service.observe(session, OWNER, [FakeDetection("person")])

        for event in events:
            assert event.timestamp_nanos == event.observed_timestamp_nanos
            # The column holds microseconds and the field nanoseconds, so they
            # agree to the resolution the column can carry.
            assert event.occurred_at.timestamp() == pytest.approx(
                event.timestamp_nanos / 1_000_000_000, abs=1e-6
            )

    async def test_the_body_repeats_the_same_instant(self, session, clock):
        service = EventService()

        events = await service.observe(session, OWNER, [FakeDetection("person")])

        for event in events:
            assert event.body["occurredAt"] == event.occurred_at.isoformat()

    async def test_the_stamp_is_the_observation_not_the_write(self, session, clock):
        """
        The clock is read where the record is built. A transaction that opened
        earlier does not lend its timestamp to what is written inside it.
        """
        service = EventService()

        clock.advance(3600)
        events = await service.observe(session, OWNER, [FakeDetection("person")])

        for event in events:
            assert event.occurred_at.timestamp() == pytest.approx(clock.now, abs=1e-3)
