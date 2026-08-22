"""
Skeleton and mesh overlay for people, hands and faces.

Produces the joint positions and the edges that connect them, so the frontend
can draw a wireframe over the video without knowing anything about the models.

Three landmark sets are published, all of them the standard layouts of the
MediaPipe Tasks vision API rather than anything invented here:

- Bodies: 33 BlazePose landmarks. Denser than the 17 point COCO layout, and the
  extra points are the ones that matter for a readable reconstruction: the feet
  get a heel and a toe, and each wrist gains a thumb, index and pinky anchor, so
  the arm chain continues into the hand instead of stopping dead.
- Hands: 21 landmarks per hand, the palm ring plus five finger chains. This is
  what carries gestures; the body model only anchors the wrist.
- Faces: 478 landmarks, drawn either as feature contours or as the full
  tessellation, which is the low polygon mesh of the face.

Every set travels with its own edge list taken from the official connection
constants, so a change in the models cannot leave the drawing out of step with
the points.
"""

import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.acceleration_service import get_acceleration_service

logger = get_logger(__name__)


# Where the task bundles are published, and the file each one is cached as.
MODEL_SOURCES: Dict[str, Tuple[str, str]] = {
    "pose": (
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_full/float16/latest/pose_landmarker_full.task",
        "pose_landmarker_full.task",
    ),
    "hand": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/latest/hand_landmarker.task",
        "hand_landmarker.task",
    ),
    "face": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/latest/face_landmarker.task",
        "face_landmarker.task",
    ),
}


def _download_model(kind: str) -> Optional[Path]:
    """
    Return the local path of a task bundle, fetching it once if needed.

    Args:
        kind: One of "pose", "hand" or "face".

    Returns:
        Path to the bundle, or None when it could not be obtained.
    """
    url, filename = MODEL_SOURCES[kind]
    destination = settings.models_path / filename

    if destination.exists() and destination.stat().st_size > 0:
        return destination

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading the {kind} landmark model")
        # Written to a temporary name first so an interrupted download cannot
        # leave a truncated bundle that every later start would accept.
        staging = destination.with_suffix(destination.suffix + ".part")
        urllib.request.urlretrieve(url, staging)
        staging.replace(destination)
        logger.info(f"The {kind} landmark model is ready at {destination}")
        return destination
    except Exception as e:
        logger.warning(f"Could not download the {kind} landmark model: {e}")
        return None


def _pose_landmark_names() -> List[str]:
    """The 33 BlazePose landmark names, in index order."""
    from mediapipe.tasks.python import vision

    return [landmark.name.lower() for landmark in vision.PoseLandmark]


HAND_LANDMARK_NAMES = [
    "wrist",
    "thumb_cmc",
    "thumb_mcp",
    "thumb_ip",
    "thumb_tip",
    "index_mcp",
    "index_pip",
    "index_dip",
    "index_tip",
    "middle_mcp",
    "middle_pip",
    "middle_dip",
    "middle_tip",
    "ring_mcp",
    "ring_pip",
    "ring_dip",
    "ring_tip",
    "pinky_mcp",
    "pinky_pip",
    "pinky_dip",
    "pinky_tip",
]


def _pose_part(name: str) -> str:
    """
    Which limb a body landmark belongs to, used to colour the wireframe.

    Args:
        name: Landmark name such as "left_elbow".

    Returns:
        str: The part label carried on every edge that ends here.
    """
    if any(token in name for token in ("eye", "ear", "nose", "mouth")):
        return "head"
    if "shoulder" in name or "hip" in name:
        return "torso"
    side = "left" if name.startswith("left") else "right"
    if any(token in name for token in ("elbow", "wrist", "thumb", "index", "pinky")):
        return f"{side}_arm"
    if any(token in name for token in ("knee", "ankle", "heel", "foot")):
        return f"{side}_leg"
    return "torso"


@dataclass
class Keypoint:
    """One landmark, in pixel coordinates of the source frame."""

    name: str
    x: float
    y: float
    score: float
    z: float = 0.0


@dataclass
class Skeleton:
    """A set of landmarks plus the edges that connect them."""

    kind: str
    keypoints: List[Keypoint]
    edges: List[Tuple[int, int, str]]
    bbox: Tuple[int, int, int, int]
    score: float
    label: Optional[str] = None

    def to_dict(self, include_edges: bool = True) -> dict:
        """
        Serialise for the API.

        Args:
            include_edges: Whether to carry the edge list. The tessellation runs
                to a few thousand edges and never changes, so it is sent on the
                first skeleton of each kind and the client reuses it for the
                rest of the frame.
        """
        return {
            "kind": self.kind,
            "label": self.label,
            "score": self.score,
            "bbox": {
                "x": self.bbox[0],
                "y": self.bbox[1],
                "width": self.bbox[2],
                "height": self.bbox[3],
            },
            "keypoints": [
                {"name": k.name, "x": k.x, "y": k.y, "z": k.z, "score": k.score}
                for k in self.keypoints
            ],
            "edges": (
                [{"from": a, "to": b, "part": part} for a, b, part in self.edges]
                if include_edges
                else []
            ),
        }


def _bounds(points: List[Keypoint]) -> Tuple[int, int, int, int]:
    """Axis aligned box around the visible landmarks."""
    visible = [p for p in points if p.score > 0.0]
    if not visible:
        return (0, 0, 0, 0)
    xs = [p.x for p in visible]
    ys = [p.y for p in visible]
    return (
        int(min(xs)),
        int(min(ys)),
        int(max(xs) - min(xs)),
        int(max(ys) - min(ys)),
    )


class PoseService:
    """
    Extracts body, hand and face landmarks from a frame.

    Every backend loads lazily and fails soft: when a model cannot be obtained
    the service stops offering that kind of overlay and ordinary detection
    carries on unaffected.
    """

    def __init__(self) -> None:
        self._pose = None
        self._hands = None
        self._face = None
        self._unavailable: Dict[str, bool] = {"pose": False, "hand": False, "face": False}
        self._pose_names: List[str] = []
        self._pose_edges: List[Tuple[int, int, str]] = []
        self._hand_edges: List[Tuple[int, int, str]] = []
        self._face_edges: List[Tuple[int, int, str]] = []
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether any overlay is switched on."""
        return settings.pose_enabled or settings.hands_enabled or settings.face_mesh_enabled

    def reload_models(self) -> None:
        """
        Close the landmarkers so the next frame rebuilds them.

        The delegate is fixed when a landmarker is created, so moving these
        between processor and graphics hardware means building new ones. Each is
        closed first: they hold native resources that are not freed by dropping
        the reference.
        """
        with self._lock:
            for existing in (self._pose, self._hands, self._face):
                if existing is None:
                    continue
                try:
                    existing.close()
                except Exception as e:
                    # A landmarker that will not close is still being replaced,
                    # so this is worth recording and not worth stopping for.
                    logger.warning(f"Could not close a landmarker cleanly: {e}")

            self._pose = None
            self._hands = None
            self._face = None
            self._unavailable = {"pose": False, "hand": False, "face": False}

    def describe(self) -> dict:
        """Report backend availability for the status endpoint."""
        return {
            "poseEnabled": settings.pose_enabled,
            "poseAvailable": not self._unavailable["pose"],
            "poseLandmarks": len(self._pose_names) or 33,
            "handsEnabled": settings.hands_enabled,
            "handsAvailable": not self._unavailable["hand"],
            "handLandmarks": len(HAND_LANDMARK_NAMES),
            "faceEnabled": settings.face_mesh_enabled,
            "faceAvailable": not self._unavailable["face"],
            "faceMode": settings.face_mesh_mode,
            "faceEdges": len(self._face_edges),
        }

    def _build_pose_edges(self) -> None:
        """Translate the official pose connections into coloured edges."""
        from mediapipe.tasks.python import vision

        self._pose_names = _pose_landmark_names()
        self._pose_edges = [
            (c.start, c.end, _pose_part(self._pose_names[c.start]))
            for c in vision.PoseLandmarksConnections.POSE_LANDMARKS
            if c.start < len(self._pose_names) and c.end < len(self._pose_names)
        ]

    def _build_hand_edges(self) -> None:
        """Translate the official hand connections into coloured edges."""
        from mediapipe.tasks.python import vision

        groups = {
            "thumb": vision.HandLandmarksConnections.HAND_THUMB_CONNECTIONS,
            "index": vision.HandLandmarksConnections.HAND_INDEX_FINGER_CONNECTIONS,
            "middle": vision.HandLandmarksConnections.HAND_MIDDLE_FINGER_CONNECTIONS,
            "ring": vision.HandLandmarksConnections.HAND_RING_FINGER_CONNECTIONS,
            "pinky": vision.HandLandmarksConnections.HAND_PINKY_FINGER_CONNECTIONS,
            "palm": vision.HandLandmarksConnections.HAND_PALM_CONNECTIONS,
        }
        edges: List[Tuple[int, int, str]] = []
        seen = set()
        for part, connections in groups.items():
            for c in connections:
                key = (c.start, c.end)
                if key in seen:
                    continue
                seen.add(key)
                edges.append((c.start, c.end, part))
        self._hand_edges = edges

    def _build_face_edges(self) -> None:
        """
        Translate the official face connections into edges.

        Contours draw the silhouette of each feature and cost a hundred or so
        edges. The tessellation is the full low polygon mesh and costs a few
        thousand, which is the difference between an outline and a 3D surface.
        """
        from mediapipe.tasks.python import vision

        connections = vision.FaceLandmarksConnections
        if settings.face_mesh_mode == "tesselation":
            self._face_edges = [
                (c.start, c.end, "mesh") for c in connections.FACE_LANDMARKS_TESSELATION
            ]
            return

        groups = {
            "face_oval": connections.FACE_LANDMARKS_FACE_OVAL,
            "left_eye": connections.FACE_LANDMARKS_LEFT_EYE,
            "right_eye": connections.FACE_LANDMARKS_RIGHT_EYE,
            "left_eyebrow": connections.FACE_LANDMARKS_LEFT_EYEBROW,
            "right_eyebrow": connections.FACE_LANDMARKS_RIGHT_EYEBROW,
            "left_iris": connections.FACE_LANDMARKS_LEFT_IRIS,
            "right_iris": connections.FACE_LANDMARKS_RIGHT_IRIS,
            "lips": connections.FACE_LANDMARKS_LIPS,
            "nose": connections.FACE_LANDMARKS_NOSE,
        }
        edges: List[Tuple[int, int, str]] = []
        for part, connections_group in groups.items():
            for c in connections_group:
                edges.append((c.start, c.end, part))
        self._face_edges = edges

    def _ensure(self, kind: str):
        """
        Load one landmarker on first use.

        Args:
            kind: One of "pose", "hand" or "face".

        Returns:
            The landmarker, or None when unavailable.
        """
        existing = {"pose": self._pose, "hand": self._hands, "face": self._face}[kind]
        if existing is not None:
            return existing
        if self._unavailable[kind]:
            return None

        with self._lock:
            existing = {"pose": self._pose, "hand": self._hands, "face": self._face}[kind]
            if existing is not None:
                return existing
            if self._unavailable[kind]:
                return None

            try:
                from mediapipe.tasks import python as mp_python
                from mediapipe.tasks.python import vision

                model_path = _download_model(kind)
                if model_path is None:
                    self._unavailable[kind] = True
                    return None

                # The GPU delegate needs a GL context that a headless container
                # usually lacks, so a failure here falls back to CPU rather than
                # taking the overlay down with it.
                delegate = (
                    mp_python.BaseOptions.Delegate.GPU
                    if get_acceleration_service().mediapipe_gpu
                    else mp_python.BaseOptions.Delegate.CPU
                )
                base = mp_python.BaseOptions(
                    model_asset_path=str(model_path), delegate=delegate
                )

                if kind == "pose":
                    landmarker = vision.PoseLandmarker.create_from_options(
                        vision.PoseLandmarkerOptions(
                            base_options=base,
                            num_poses=settings.pose_max_people,
                            min_pose_detection_confidence=settings.pose_confidence_threshold,
                            min_pose_presence_confidence=settings.pose_keypoint_threshold,
                            min_tracking_confidence=settings.pose_keypoint_threshold,
                        )
                    )
                    self._build_pose_edges()
                    self._pose = landmarker
                elif kind == "hand":
                    landmarker = vision.HandLandmarker.create_from_options(
                        vision.HandLandmarkerOptions(
                            base_options=base,
                            num_hands=settings.hands_max_number,
                            min_hand_detection_confidence=settings.hands_confidence_threshold,
                            min_hand_presence_confidence=settings.hands_confidence_threshold,
                            min_tracking_confidence=settings.hands_confidence_threshold,
                        )
                    )
                    self._build_hand_edges()
                    self._hands = landmarker
                else:
                    landmarker = vision.FaceLandmarker.create_from_options(
                        vision.FaceLandmarkerOptions(
                            base_options=base,
                            num_faces=settings.face_mesh_max_faces,
                            min_face_detection_confidence=settings.face_mesh_confidence_threshold,
                            min_face_presence_confidence=settings.face_mesh_confidence_threshold,
                            min_tracking_confidence=settings.face_mesh_confidence_threshold,
                        )
                    )
                    self._build_face_edges()
                    self._face = landmarker

                logger.info(f"The {kind} landmarker is ready")
                return landmarker
            except Exception as e:
                self._unavailable[kind] = True
                logger.warning(f"The {kind} landmarker is unavailable: {e}")
                return None

    def _to_mp_image(self, frame: np.ndarray):
        """Wrap a BGR frame as the SRGB image the tasks API expects."""
        import cv2
        import mediapipe as mp

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    def extract_bodies(self, frame: np.ndarray) -> List[Skeleton]:
        """
        Find every person in a frame and return their 33 point skeleton.

        Args:
            frame: Full BGR frame.

        Returns:
            List[Skeleton]: One entry per person with enough visible landmarks.
        """
        landmarker = self._ensure("pose") if settings.pose_enabled else None
        if landmarker is None:
            return []

        try:
            result = landmarker.detect(self._to_mp_image(frame))
        except Exception as e:
            logger.debug(f"Pose inference failed: {e}")
            return []

        height, width = frame.shape[:2]
        threshold = settings.pose_keypoint_threshold
        skeletons: List[Skeleton] = []

        for landmarks in getattr(result, "pose_landmarks", []) or []:
            points: List[Keypoint] = []
            for index, landmark in enumerate(landmarks):
                if index >= len(self._pose_names):
                    break
                # Visibility is what tells a genuinely occluded joint from one
                # the model simply placed badly, so it drives the score.
                visibility = float(getattr(landmark, "visibility", 1.0) or 0.0)
                points.append(
                    Keypoint(
                        name=self._pose_names[index],
                        x=float(landmark.x * width),
                        y=float(landmark.y * height),
                        z=float(getattr(landmark, "z", 0.0) or 0.0),
                        score=visibility if visibility >= threshold else 0.0,
                    )
                )

            if len([p for p in points if p.score > 0.0]) < 3:
                continue

            skeletons.append(
                Skeleton(
                    kind="body",
                    keypoints=points,
                    edges=self._pose_edges,
                    bbox=_bounds(points),
                    score=1.0,
                )
            )

        return skeletons

    def extract_hands(self, frame: np.ndarray) -> List[Skeleton]:
        """
        Find every hand in a frame and return its 21 landmark skeleton.

        Args:
            frame: Full BGR frame.

        Returns:
            List[Skeleton]: One entry per hand, labelled Left or Right.
        """
        landmarker = self._ensure("hand") if settings.hands_enabled else None
        if landmarker is None:
            return []

        try:
            result = landmarker.detect(self._to_mp_image(frame))
        except Exception as e:
            logger.debug(f"Hand inference failed: {e}")
            return []

        height, width = frame.shape[:2]
        handedness = getattr(result, "handedness", []) or []
        skeletons: List[Skeleton] = []

        for index, landmarks in enumerate(getattr(result, "hand_landmarks", []) or []):
            points: List[Keypoint] = []
            for joint, landmark in enumerate(landmarks):
                if joint >= len(HAND_LANDMARK_NAMES):
                    break
                points.append(
                    Keypoint(
                        name=HAND_LANDMARK_NAMES[joint],
                        x=float(landmark.x * width),
                        y=float(landmark.y * height),
                        z=float(getattr(landmark, "z", 0.0) or 0.0),
                        score=1.0,
                    )
                )

            if not points:
                continue

            label = None
            score = 1.0
            if index < len(handedness) and handedness[index]:
                category = handedness[index][0]
                label = category.category_name
                score = float(category.score)

            skeletons.append(
                Skeleton(
                    kind="hand",
                    keypoints=points,
                    edges=self._hand_edges,
                    bbox=_bounds(points),
                    score=score,
                    label=label,
                )
            )

        return skeletons

    def extract_faces(self, frame: np.ndarray) -> List[Skeleton]:
        """
        Find every face in a frame and return its landmark mesh.

        Args:
            frame: Full BGR frame.

        Returns:
            List[Skeleton]: One entry per face.
        """
        landmarker = self._ensure("face") if settings.face_mesh_enabled else None
        if landmarker is None:
            return []

        try:
            result = landmarker.detect(self._to_mp_image(frame))
        except Exception as e:
            logger.debug(f"Face inference failed: {e}")
            return []

        height, width = frame.shape[:2]
        skeletons: List[Skeleton] = []

        for landmarks in getattr(result, "face_landmarks", []) or []:
            points = [
                Keypoint(
                    name=str(index),
                    x=float(landmark.x * width),
                    y=float(landmark.y * height),
                    z=float(getattr(landmark, "z", 0.0) or 0.0),
                    score=1.0,
                )
                for index, landmark in enumerate(landmarks)
            ]

            if not points:
                continue

            skeletons.append(
                Skeleton(
                    kind="face",
                    keypoints=points,
                    edges=self._face_edges,
                    bbox=_bounds(points),
                    score=1.0,
                )
            )

        return skeletons

    def extract(
        self,
        frame: np.ndarray,
        include_bodies: bool = True,
        include_hands: bool = True,
        include_faces: bool = True,
    ) -> Tuple[List[Skeleton], float]:
        """
        Extract the requested overlays from a frame.

        Each kind is skipped rather than filtered afterwards, because running a
        landmark model and throwing the result away is the whole cost for none
        of the benefit.

        Args:
            frame: Full BGR frame.
            include_bodies: Whether to run the body model.
            include_hands: Whether to run the hand model.
            include_faces: Whether to run the face model.

        Returns:
            Tuple of (skeletons, processing time in milliseconds).
        """
        if not self.enabled:
            return [], 0.0

        start = time.perf_counter()
        skeletons: List[Skeleton] = []
        if include_bodies:
            skeletons += self.extract_bodies(frame)
        if include_hands:
            skeletons += self.extract_hands(frame)
        if include_faces:
            skeletons += self.extract_faces(frame)
        elapsed = (time.perf_counter() - start) * 1000
        return skeletons, elapsed


_pose_service: Optional[PoseService] = None


def get_pose_service() -> PoseService:
    """Get the pose service singleton."""
    global _pose_service
    if _pose_service is None:
        _pose_service = PoseService()
    return _pose_service
