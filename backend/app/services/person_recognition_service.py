"""
Person re-identification service.

Builds a stable fingerprint for every person seen by the camera and matches new
sightings against the people already known.

Two independent embeddings are produced per sighting, because each one fails
where the other holds:

- The face embedding is computed from the aligned face crop. It survives a
  change of clothes and a different camera, which is what makes a person
  recognisable across sessions. It degrades when a mask covers the mouth and
  nose, and it is unavailable when the person faces away.
- The body embedding is computed from the whole person crop. It is unaffected by
  a cap, sunglasses or a mask, and it works from behind. It does not survive a
  change of clothes, so on its own it only carries identity within a session.

A sighting matches a known person when the weighted combination of both
similarities clears the configured thresholds. When nothing matches and
auto enrolment is on, a new person is created with the next free sequential
name, "Person 1", "Person 2", and so on.
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

FACE = "face"
BODY = "body"


def _l2_normalise(vector: np.ndarray) -> np.ndarray:
    """
    Scale a vector to unit length so that a dot product equals cosine similarity.

    Args:
        vector: Raw embedding.

    Returns:
        np.ndarray: Unit length embedding, or the input when its norm is zero.
    """
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        return vector.astype(np.float32)
    return (vector / norm).astype(np.float32)


@dataclass
class PersonSighting:
    """One person detected in a frame, with whatever embeddings could be built."""

    bbox: Tuple[int, int, int, int]
    face_vector: Optional[np.ndarray] = None
    body_vector: Optional[np.ndarray] = None
    face_quality: float = 0.0
    body_quality: float = 0.0
    crop: Optional[np.ndarray] = None

    @property
    def has_any_embedding(self) -> bool:
        """Whether at least one embedding could be extracted."""
        return self.face_vector is not None or self.body_vector is not None

    @property
    def representativeness(self) -> float:
        """
        How good this sighting is as the picture that represents the person.

        A visible face is what makes a thumbnail recognisable to a human, so it
        dominates the score; crop size breaks ties between sightings that are
        otherwise equal.
        """
        return self.face_quality * 2.0 + self.body_quality


@dataclass
class PersonMatch:
    """Result of matching a sighting against the known gallery."""

    person_id: UUID
    person_name: str
    similarity: float
    face_similarity: float = 0.0
    body_similarity: float = 0.0
    matched_on: str = ""


@dataclass
class GalleryEntry:
    """All stored embeddings for one known person."""

    person_id: UUID
    person_name: str
    face_vectors: List[np.ndarray] = field(default_factory=list)
    body_vectors: List[np.ndarray] = field(default_factory=list)

    def best_similarity(self, kind: str, query: np.ndarray) -> float:
        """
        Highest cosine similarity between a query vector and the stored samples.

        Args:
            kind: Either "face" or "body".
            query: Unit length query embedding.

        Returns:
            float: Best similarity, or 0.0 when no sample of that kind exists.
        """
        vectors = self.face_vectors if kind == FACE else self.body_vectors
        if not vectors:
            return 0.0
        stacked = np.vstack(vectors)
        return float(np.max(stacked @ query))


class FaceEmbedder:
    """
    Face detection and embedding through InsightFace.

    Wraps the model so that a missing or broken installation degrades to no face
    embeddings instead of breaking detection for everyone.
    """

    def __init__(self) -> None:
        self._app = None
        self._unavailable = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Whether the face model can be used."""
        return not self._unavailable

    def _ensure_loaded(self) -> bool:
        """Load the model on first use. Returns False when unavailable."""
        if self._app is not None:
            return True
        if self._unavailable:
            return False

        with self._lock:
            if self._app is not None:
                return True
            if self._unavailable:
                return False
            try:
                from insightface.app import FaceAnalysis

                app = FaceAnalysis(
                    name=settings.person_face_model,
                    allowed_modules=["detection", "recognition"],
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=-1, det_size=(640, 640))
                self._app = app
                logger.info(f"Face model ready: {settings.person_face_model}")
                return True
            except Exception as e:
                self._unavailable = True
                logger.warning(
                    f"Face recognition unavailable, falling back to body only: {e}"
                )
                return False

    def embed(self, person_crop: np.ndarray) -> Tuple[Optional[np.ndarray], float]:
        """
        Extract a face embedding from a person crop.

        Args:
            person_crop: BGR crop containing one person.

        Returns:
            Tuple of (unit length embedding or None, quality score).
        """
        if not self._ensure_loaded():
            return None, 0.0

        try:
            faces = self._app.get(person_crop)
        except Exception as e:
            logger.debug(f"Face inference failed: {e}")
            return None, 0.0

        if not faces:
            return None, 0.0

        # Keep the largest face, which is the one belonging to this crop rather
        # than a bystander leaking in from behind.
        def area(face) -> float:
            x1, y1, x2, y2 = face.bbox
            return float((x2 - x1) * (y2 - y1))

        face = max(faces, key=area)
        x1, y1, x2, y2 = face.bbox
        side = min(float(x2 - x1), float(y2 - y1))
        if side < settings.person_min_face_size:
            return None, 0.0

        embedding = getattr(face, "normed_embedding", None)
        if embedding is None:
            embedding = getattr(face, "embedding", None)
        if embedding is None:
            return None, 0.0

        quality = float(getattr(face, "det_score", 0.0))
        return _l2_normalise(np.asarray(embedding, dtype=np.float32)), quality


class BodyEmbedder:
    """
    Whole body appearance embedding.

    Two backends, chosen at load time:

    - An ONNX re-identification model when PERSON_BODY_MODEL_PATH points at one.
      Drop an OSNet export there to get proper re-identification accuracy.
    - Otherwise a torchvision ResNet50 backbone, pooled and normalised. The
      weights ship with torchvision, so this always works without extra
      downloads or packaging conflicts. It is weaker than a dedicated
      re-identification model but good enough to hold identity within a session,
      which is the role the body embedding plays here.
    """

    INPUT_HEIGHT = 256
    INPUT_WIDTH = 128
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self) -> None:
        self._session = None
        self._input_name: Optional[str] = None
        self._torch_model = None
        self._unavailable = False
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        """Whether a body embedding backend can be used."""
        return not self._unavailable

    def _ensure_loaded(self) -> bool:
        """Load the configured backend on first use."""
        if self._session is not None or self._torch_model is not None:
            return True
        if self._unavailable:
            return False

        with self._lock:
            if self._session is not None or self._torch_model is not None:
                return True
            if self._unavailable:
                return False

            model_path = settings.person_body_model_path
            if model_path:
                try:
                    import onnxruntime

                    self._session = onnxruntime.InferenceSession(
                        model_path, providers=["CPUExecutionProvider"]
                    )
                    self._input_name = self._session.get_inputs()[0].name
                    logger.info(f"Body re-identification model ready: {model_path}")
                    return True
                except Exception as e:
                    logger.warning(
                        f"Could not load body model at {model_path}, "
                        f"falling back to the torchvision backbone: {e}"
                    )

            try:
                import torch
                from torchvision.models import ResNet50_Weights, resnet50

                model = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2)
                # Drop the classifier: the pooled features are the descriptor.
                model.fc = torch.nn.Identity()
                model.eval()
                self._torch_model = model
                logger.info("Body appearance backbone ready: torchvision resnet50")
                return True
            except Exception as e:
                self._unavailable = True
                logger.warning(f"Body embeddings unavailable: {e}")
                return False

    def _preprocess(self, person_crop: np.ndarray) -> np.ndarray:
        """Resize, convert to RGB, scale and normalise a crop into NCHW."""
        import cv2

        resized = cv2.resize(
            person_crop, (self.INPUT_WIDTH, self.INPUT_HEIGHT), interpolation=cv2.INTER_LINEAR
        )
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        normalised = (rgb - self.MEAN) / self.STD
        return np.transpose(normalised, (2, 0, 1))[np.newaxis, ...].astype(np.float32)

    def embed(self, person_crop: np.ndarray) -> Tuple[Optional[np.ndarray], float]:
        """
        Extract a body appearance embedding from a person crop.

        Args:
            person_crop: BGR crop containing one person.

        Returns:
            Tuple of (unit length embedding or None, quality score).
        """
        if person_crop.size == 0:
            return None, 0.0
        if not self._ensure_loaded():
            return None, 0.0

        try:
            batch = self._preprocess(person_crop)

            if self._session is not None:
                outputs = self._session.run(None, {self._input_name: batch})
                vector = np.asarray(outputs[0]).reshape(-1)
            else:
                import torch

                with torch.no_grad():
                    output = self._torch_model(torch.from_numpy(batch))
                vector = output.numpy().reshape(-1)

            # A crop with more pixels carries a more reliable descriptor.
            height, width = person_crop.shape[:2]
            quality = float(min(1.0, (height * width) / (self.INPUT_HEIGHT * self.INPUT_WIDTH)))
            return _l2_normalise(vector), quality
        except Exception as e:
            logger.debug(f"Body inference failed: {e}")
            return None, 0.0


class PersonRecognitionService:
    """
    Recognises people across frames and sessions.

    Holds an in memory gallery of the embeddings stored for each known person.
    The gallery is loaded from the database by the caller and kept in sync as
    people are enrolled, renamed or removed.
    """

    def __init__(self) -> None:
        self.face_embedder = FaceEmbedder()
        self.body_embedder = BodyEmbedder()
        self._gallery: Dict[UUID, GalleryEntry] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether person recognition should run at all."""
        return settings.person_recognition_enabled

    def has_gallery(self) -> bool:
        """Whether any person is currently known."""
        return len(self._gallery) > 0

    def known_names(self) -> List[str]:
        """Names of every person in the gallery."""
        return [entry.person_name for entry in self._gallery.values()]

    def describe(self, sighting_count: int = 0) -> dict:
        """Report the state of the recognition backends for the status endpoint."""
        return {
            "enabled": self.enabled,
            "faceModelAvailable": self.face_embedder.available,
            "bodyModelAvailable": self.body_embedder.available,
            "knownPeople": len(self._gallery),
            "sightings": sighting_count,
        }

    def clear_gallery(self) -> None:
        """Drop every known person from memory."""
        with self._lock:
            self._gallery.clear()
        logger.info("Person gallery cleared")

    def remove_person(self, person_id: UUID) -> bool:
        """
        Forget one person.

        Args:
            person_id: Catalog id of the person.

        Returns:
            bool: True when the person was present.
        """
        with self._lock:
            return self._gallery.pop(person_id, None) is not None

    def rename_person(self, person_id: UUID, new_name: str) -> bool:
        """
        Update the cached display name of a person.

        Args:
            person_id: Catalog id of the person.
            new_name: New display name.

        Returns:
            bool: True when the person was present.
        """
        with self._lock:
            entry = self._gallery.get(person_id)
            if entry is None:
                return False
            entry.person_name = new_name
            return True

    def load_person(
        self,
        person_id: UUID,
        person_name: str,
        embeddings: List[Tuple[str, List[float]]],
    ) -> int:
        """
        Put one person and their stored embeddings into the gallery.

        Args:
            person_id: Catalog id of the person.
            person_name: Display name.
            embeddings: Pairs of (kind, vector) read from the database.

        Returns:
            int: Number of vectors loaded.
        """
        entry = GalleryEntry(person_id=person_id, person_name=person_name)
        for kind, values in embeddings:
            if not values:
                continue
            vector = _l2_normalise(np.asarray(values, dtype=np.float32))
            if kind == FACE:
                entry.face_vectors.append(vector)
            elif kind == BODY:
                entry.body_vectors.append(vector)

        with self._lock:
            self._gallery[person_id] = entry

        return len(entry.face_vectors) + len(entry.body_vectors)

    def add_embeddings(self, person_id: UUID, sighting: PersonSighting) -> None:
        """
        Fold a fresh sighting into the gallery entry of a known person.

        Older samples are dropped once the per person cap is reached, so the
        gallery keeps tracking how a person looks now rather than growing
        without bound.

        Args:
            person_id: Catalog id of the person.
            sighting: The sighting whose embeddings should be remembered.
        """
        cap = settings.person_max_embeddings_per_person
        with self._lock:
            entry = self._gallery.get(person_id)
            if entry is None:
                return
            if sighting.face_vector is not None:
                entry.face_vectors.append(sighting.face_vector)
                if len(entry.face_vectors) > cap:
                    entry.face_vectors = entry.face_vectors[-cap:]
            if sighting.body_vector is not None:
                entry.body_vectors.append(sighting.body_vector)
                if len(entry.body_vectors) > cap:
                    entry.body_vectors = entry.body_vectors[-cap:]

    def build_sighting(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> PersonSighting:
        """
        Extract the face and body embeddings for one detected person.

        Args:
            frame: Full BGR frame.
            bbox: Person box as (x, y, width, height).

        Returns:
            PersonSighting: Whatever embeddings could be produced.
        """
        x, y, width, height = bbox
        frame_height, frame_width = frame.shape[:2]

        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(frame_width, int(x + width))
        y2 = min(frame_height, int(y + height))

        sighting = PersonSighting(bbox=bbox)
        if x2 <= x1 or y2 <= y1:
            return sighting

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return sighting

        sighting.crop = crop

        face_vector, face_quality = self.face_embedder.embed(crop)
        sighting.face_vector = face_vector
        sighting.face_quality = face_quality

        body_vector, body_quality = self.body_embedder.embed(crop)
        sighting.body_vector = body_vector
        sighting.body_quality = body_quality

        return sighting

    def match(self, sighting: PersonSighting) -> Optional[PersonMatch]:
        """
        Find the known person that best explains a sighting.

        The face similarity carries most of the weight because it is the part
        that survives a change of clothes. A strong face match alone is enough,
        and so is a strong body match when no face is visible, which is what
        keeps recognition working behind a mask or from behind.

        Args:
            sighting: The sighting to identify.

        Returns:
            PersonMatch when a person clears the thresholds, None otherwise.
        """
        if not sighting.has_any_embedding:
            return None

        with self._lock:
            entries = list(self._gallery.values())

        if not entries:
            return None

        face_threshold = settings.person_face_threshold
        body_threshold = settings.person_body_threshold
        face_weight = settings.person_face_weight

        best: Optional[PersonMatch] = None

        for entry in entries:
            face_similarity = (
                entry.best_similarity(FACE, sighting.face_vector)
                if sighting.face_vector is not None
                else 0.0
            )
            body_similarity = (
                entry.best_similarity(BODY, sighting.body_vector)
                if sighting.body_vector is not None
                else 0.0
            )

            face_hit = face_similarity >= face_threshold
            body_hit = body_similarity >= body_threshold

            if not face_hit and not body_hit:
                continue

            if face_hit and body_hit:
                combined = face_weight * face_similarity + (1.0 - face_weight) * body_similarity
                matched_on = "face and body"
            elif face_hit:
                combined = face_similarity
                matched_on = "face"
            else:
                combined = body_similarity
                matched_on = "body"

            if best is None or combined > best.similarity:
                best = PersonMatch(
                    person_id=entry.person_id,
                    person_name=entry.person_name,
                    similarity=combined,
                    face_similarity=face_similarity,
                    body_similarity=body_similarity,
                    matched_on=matched_on,
                )

        if best is not None:
            logger.debug(
                f"Person matched: {best.person_name} on {best.matched_on} "
                f"(face={best.face_similarity:.2f}, body={best.body_similarity:.2f})"
            )

        return best

    def next_person_name(self, taken_names: List[str]) -> str:
        """
        Build the next free sequential name for an unknown person.

        Existing names are scanned for the "Person N" pattern so that the
        counter continues after the highest one already used, and renaming a
        person never causes a later collision.

        Args:
            taken_names: Every name already present in the People category.

        Returns:
            str: A name such as "Person 3" that is not currently in use.
        """
        prefix = settings.person_name_prefix
        lowered = {name.strip().lower() for name in taken_names}

        highest = 0
        for name in taken_names:
            parts = name.strip().split()
            if len(parts) == 2 and parts[0].lower() == prefix.lower() and parts[1].isdigit():
                highest = max(highest, int(parts[1]))

        candidate_index = highest + 1
        while f"{prefix} {candidate_index}".lower() in lowered:
            candidate_index += 1

        return f"{prefix} {candidate_index}"


_person_service: Optional[PersonRecognitionService] = None


def get_person_recognition_service() -> PersonRecognitionService:
    """Get the person recognition service singleton."""
    global _person_service
    if _person_service is None:
        _person_service = PersonRecognitionService()
    return _person_service
