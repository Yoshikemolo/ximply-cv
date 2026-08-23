"""
Tests for what it takes to create a person.

Recognition failing costs one frame. A person invented from a bad crop stays in
the catalog, is a biometric record of somebody who was never there in the sense
the catalog claims, and splits every later sighting of that face in two. The
gates below are what separate the two, and each exists because failing it
produced an entry that was seen once and never again.

See ADR-0012 and ADR-0019.
"""

import numpy as np
import pytest
from uuid_extensions import uuid7

from app.core.config import settings
from app.services.person_recognition_service import (
    BODY,
    FACE,
    PersonRecognitionService,
    PersonSighting,
)


def unit(*values) -> np.ndarray:
    """A unit length vector, so a dot product is the cosine similarity."""
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def rotated(vector: np.ndarray, similarity: float, axis: int = 1) -> np.ndarray:
    """
    A unit vector at a chosen cosine similarity to another.

    Building the similarity rather than asserting on whatever two arbitrary
    vectors happen to score keeps these tests about the thresholds instead of
    about the numbers.

    The axis chooses which direction to lean away in. Two results built on the
    same axis are near identical to each other whatever their similarity to the
    original, so a test about telling people apart has to vary it: that is the
    difference between one stranger seen twice and two strangers.
    """
    basis = np.zeros_like(vector)
    basis[axis] = 1.0
    perpendicular = basis - float(basis @ vector) * vector
    perpendicular /= np.linalg.norm(perpendicular)
    result = similarity * vector + np.sqrt(1.0 - similarity**2) * perpendicular
    return (result / np.linalg.norm(result)).astype(np.float32)


KNOWN_FACE = unit(1.0, 0.0, 0.0, 0.0)
KNOWN_BODY = unit(0.0, 1.0, 0.0, 0.0)


def sighting(face=None, body=None, face_quality=0.9, body_quality=0.9):
    """One sighting carrying whichever embeddings a test needs."""
    return PersonSighting(
        bbox=(0, 0, 100, 200),
        face_vector=face,
        body_vector=body,
        face_quality=face_quality,
        body_quality=body_quality,
    )


@pytest.fixture
def service():
    """A service with one known person and no models loaded."""
    recogniser = PersonRecognitionService()
    recogniser.load_person(
        uuid7(),
        "Jorge",
        [(FACE, KNOWN_FACE.tolist()), (BODY, KNOWN_BODY.tolist())],
    )
    return recogniser


@pytest.fixture
def enrol_on_sight(monkeypatch):
    """Take confirmation out of the way, for tests about the other gates."""
    monkeypatch.setattr(settings, "person_enrol_confirmations", 1)


class TestEvaluationReportsTheNearMiss:
    """
    Answering with a person or with nothing loses the difference between a
    stranger and a known person seen badly. Only the second should ever be
    refused an entry, and only the first should get one.
    """

    def test_a_clear_match_is_accepted(self, service):
        evaluation = service.evaluate(sighting(face=KNOWN_FACE))
        assert evaluation.matched
        assert evaluation.match.person_name == "Jorge"

    def test_the_best_similarity_is_reported_even_when_refused(self, service):
        near = settings.person_face_threshold - 0.01
        evaluation = service.evaluate(sighting(face=rotated(KNOWN_FACE, near)))

        assert not evaluation.matched
        assert evaluation.best_face_similarity == pytest.approx(near, abs=1e-3)

    def test_a_stranger_scores_far_below_the_threshold(self, service):
        evaluation = service.evaluate(sighting(face=rotated(KNOWN_FACE, 0.02)))
        assert not evaluation.matched
        assert not evaluation.near_miss


class TestEnrolmentGates:
    """Each gate refuses a sighting that used to create a person."""

    def test_a_near_miss_does_not_become_a_new_person(
        self, service, enrol_on_sight
    ):
        """
        A face one hundredth under the threshold is that person in worse light.
        Enrolling on it splits somebody already in the catalog.
        """
        near = settings.person_face_threshold - 0.01
        candidate = sighting(face=rotated(KNOWN_FACE, near))
        evaluation = service.evaluate(candidate)

        assert evaluation.near_miss
        assert not service.should_enrol(candidate, evaluation)

    def test_a_stranger_is_still_enrolled(self, service, enrol_on_sight):
        candidate = sighting(face=rotated(KNOWN_FACE, 0.02))
        assert service.should_enrol(candidate, service.evaluate(candidate))

    def test_a_face_the_detector_was_unsure_of_is_refused(
        self, service, enrol_on_sight
    ):
        poor = settings.person_min_enrol_face_quality - 0.1
        candidate = sighting(face=rotated(KNOWN_FACE, 0.02), face_quality=poor)

        assert not service.should_enrol(candidate, service.evaluate(candidate))

    def test_a_body_only_sighting_needs_a_large_crop(self, service, enrol_on_sight):
        small = settings.person_min_enrol_body_quality - 0.1
        candidate = sighting(body=rotated(KNOWN_BODY, 0.02, axis=0), body_quality=small)

        assert not service.should_enrol(candidate, service.evaluate(candidate))

    def test_a_matched_sighting_is_never_enrolled(self, service, enrol_on_sight):
        candidate = sighting(face=KNOWN_FACE)
        evaluation = service.evaluate(candidate)

        assert evaluation.matched
        assert not service.should_enrol(candidate, evaluation)

    def test_the_switch_turns_enrolment_off(self, service, monkeypatch):
        monkeypatch.setattr(settings, "person_auto_enroll", False)
        candidate = sighting(face=rotated(KNOWN_FACE, 0.02))

        assert not service.should_enrol(candidate, service.evaluate(candidate))


class TestConfirmationOverFrames:
    """
    A fingerprint seen once and never again was a reflection, a face on a
    screen, or a second box on somebody already identified. Waiting for it to
    come back costs a few frames of being called nobody, and costs nothing when
    the person is really there.
    """

    def test_one_sighting_is_not_enough(self, service, monkeypatch):
        monkeypatch.setattr(settings, "person_enrol_confirmations", 3)
        candidate = sighting(face=rotated(KNOWN_FACE, 0.02))

        assert not service.should_enrol(candidate, service.evaluate(candidate))

    def test_the_same_face_coming_back_earns_an_entry(self, service, monkeypatch):
        monkeypatch.setattr(settings, "person_enrol_confirmations", 3)
        stranger = rotated(KNOWN_FACE, 0.02)

        results = [
            service.should_enrol(
                sighting(face=stranger), service.evaluate(sighting(face=stranger))
            )
            for _ in range(3)
        ]

        assert results == [False, False, True]

    def test_different_faces_do_not_confirm_each_other(self, service, monkeypatch):
        """
        Three strangers passing once each are three unconfirmed candidates, not
        one confirmed person.
        """
        monkeypatch.setattr(settings, "person_enrol_confirmations", 3)

        for axis in (1, 2, 3):
            candidate = sighting(face=rotated(KNOWN_FACE, 0.02, axis=axis))
            assert not service.should_enrol(candidate, service.evaluate(candidate))

    def test_a_candidate_that_stops_coming_back_expires(
        self, service, monkeypatch
    ):
        monkeypatch.setattr(settings, "person_enrol_confirmations", 3)
        monkeypatch.setattr(settings, "person_enrol_window_seconds", 0.0)
        stranger = rotated(KNOWN_FACE, 0.02)

        for _ in range(4):
            candidate = sighting(face=stranger)
            assert not service.should_enrol(candidate, service.evaluate(candidate))

    def test_confirmed_candidates_are_not_kept(self, service, monkeypatch):
        """
        A confirmed candidate is about to become a catalog entry. Holding both
        would let the next sighting match the pending copy rather than the
        person, and the count would start again.
        """
        monkeypatch.setattr(settings, "person_enrol_confirmations", 2)
        stranger = rotated(KNOWN_FACE, 0.02)

        service.should_enrol(sighting(face=stranger), service.evaluate(sighting(face=stranger)))
        assert service.should_enrol(
            sighting(face=stranger), service.evaluate(sighting(face=stranger))
        )
        assert service._pending == []

    def test_clearing_the_gallery_drops_the_candidates(self, service, monkeypatch):
        monkeypatch.setattr(settings, "person_enrol_confirmations", 3)
        candidate = sighting(face=rotated(KNOWN_FACE, 0.02))
        service.should_enrol(candidate, service.evaluate(candidate))

        service.clear_gallery()

        assert service._pending == []


class TestSequentialNaming:
    """Renaming a person must never cause a later collision."""

    def test_the_counter_continues_after_the_highest_used(self, service):
        assert service.next_person_name(["Person 1", "Person 7", "Jorge"]) == "Person 8"

    def test_an_empty_catalog_starts_at_one(self, service):
        assert service.next_person_name([]) == "Person 1"
