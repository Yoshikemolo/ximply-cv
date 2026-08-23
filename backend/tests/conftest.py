"""
Shared fixtures.

The tests here exercise the two services whose defects are hardest to see from
outside: the event layer, which can be wrong for hours before anyone notices,
and person enrolment, which is wrong only in what it silently adds to a
catalog. Both are tested without a database and without a model, because both
hold their logic in plain Python and reaching for either would only test the
container.
"""

from typing import List

import pytest


class FakeSession:
    """
    Enough of an AsyncSession for the event service.

    The service adds records and leaves the transaction to its caller, so
    collecting what was added is the whole contract. Anything else raising is
    the point: a test should fail loudly if the service starts doing database
    work it did not do before.
    """

    def __init__(self) -> None:
        self.added: List[object] = []

    def add(self, entity: object) -> None:
        self.added.append(entity)


class FakeClock:
    """
    A clock the test moves by hand.

    The event service reads the wall clock to decide whether a floor has passed
    and to stamp records. Both of those are the subject of these tests, so
    neither can be left to real time.
    """

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start
        self.reads = 0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def time(self) -> float:
        """The instant the test has moved to, for deciding whether a floor passed."""
        return self.now

    def time_ns(self) -> int:
        """
        The instant a record is stamped with.

        Each read is a microsecond later than the last, because a real clock
        read twice never returns the same nanosecond, and records raised by one
        frame depend on that to be distinguishable.
        """
        self.reads += 1
        return int(self.now * 1_000_000_000) + self.reads * 1_000


class FakeDetection:
    """One detection as the event service reads it."""

    def __init__(
        self,
        label: str,
        confidence: float = 0.9,
        object_id: object = None,
        object_name: object = None,
        match_confidence: object = None,
    ) -> None:
        self.label = label
        self.confidence = confidence
        self.object_id = object_id
        self.object_name = object_name
        self.match_confidence = match_confidence


@pytest.fixture
def session() -> FakeSession:
    """A collecting stand-in for the database session."""
    return FakeSession()


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    """
    Replace the clock the event service reads.

    The module reference is swapped rather than the standard library function,
    so nothing outside this service sees a different time.
    """
    from app.services import event_service

    fake = FakeClock()
    monkeypatch.setattr(event_service, "time", fake)
    # The service refuses to hand out a microsecond it has already used. That
    # memory outlives a test, so it is reset with the clock it is derived from,
    # or one test would push the next one's stamps forward.
    monkeypatch.setattr(event_service, "_last_stamp_us", 0)
    return fake
