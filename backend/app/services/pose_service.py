"""
Skeleton overlay for people and hands.

Produces the joint positions and the edges that connect them, so the frontend
can draw a wireframe over the video without knowing anything about the models.

Two standard layouts are used, both of them the de facto convention in their
field rather than anything invented here:

- Bodies use the COCO 17 keypoint layout, the output format of every YOLO pose
  model. The 19 skeleton edges below are the canonical COCO pairs, matching the
  ones Ultralytics itself draws.
- Hands use the 21 landmark MediaPipe layout, with the standard connection set
  of a palm ring plus five finger chains.

Keeping the published layouts means an exported frame is directly comparable
with any other pose tooling.
"""

import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# COCO 17 keypoint names, in the index order every pose model emits.
COCO_KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

# Canonical COCO skeleton, zero indexed. Grouped by the body part each edge
# belongs to so the frontend can colour the limbs by hierarchy.
COCO_SKELETON: List[Tuple[int, int, str]] = [
    # Head
    (0, 1, "head"),
    (0, 2, "head"),
    (1, 3, "head"),
    (2, 4, "head"),
    (3, 5, "head"),
    (4, 6, "head"),
    # Torso
    (5, 6, "torso"),
    (5, 11, "torso"),
    (6, 12, "torso"),
    (11, 12, "torso"),
    # Arms
    (5, 7, "left_arm"),
    (7, 9, "left_arm"),
    (6, 8, "right_arm"),
    (8, 10, "right_arm"),
    # Legs
    (11, 13, "left_leg"),
    (13, 15, "left_leg"),
    (12, 14, "right_leg"),
    (14, 16, "right_leg"),
]

# MediaPipe hand landmark names, in index order.
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

# Standard MediaPipe hand connections: the palm ring plus one chain per finger.
HAND_SKELETON: List[Tuple[int, int, str]] = (
    [(0, 1, "thumb"), (1, 2, "thumb"), (2, 3, "thumb"), (3, 4, "thumb")]
    + [(0, 5, "index"), (5, 6, "index"), (6, 7, "index"), (7, 8, "index")]
    + [(9, 10, "middle"), (10, 11, "middle"), (11, 12, "middle")]
    + [(13, 14, "ring"), (14, 15, "ring"), (15, 16, "ring")]
    + [(0, 17, "pinky"), (17, 18, "pinky"), (18, 19, "pinky"), (19, 20, "pinky")]
    + [(5, 9, "palm"), (9, 13, "palm"), (13, 17, "palm")]
)


@dataclass
class Keypoint:
    """One joint, in pixel coordinates of the source frame."""

    name: str
    x: float
    y: float
    score: float


@dataclass
class Skeleton:
    """A set of joints plus the edges that connect them."""

    kind: str
    keypoints: List[Keypoint]
    bbox: Tuple[int, int, int, int]
    score: float
    label: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialise for the API, edges included so the client draws blindly."""
        edges = COCO_SKELETON if self.kind == "body" else HAND_SKELETON
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
                {"name": k.name, "x": k.x, "y": k.y, "score": k.score} for k in self.keypoints
            ],
            "edges": [{"from": a, "to": b, "part": part} for a, b, part in edges],
        }


class PoseService:
    """
    Extracts body and hand skeletons from a frame.

    Both backends load lazily and fail soft: when a model cannot be loaded the
    service simply stops offering that kind of skeleton, and ordinary detection
    carries on.
    """

    def __init__(self) -> None:
        self._pose_model = None
        self._pose_unavailable = False
        self._hands = None
        self._hands_unavailable = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether any skeleton extraction is switched on."""
        return settings.pose_enabled or settings.hands_enabled

    def describe(self) -> dict:
        """Report backend availability for the status endpoint."""
        return {
            "poseEnabled": settings.pose_enabled,
            "poseAvailable": not self._pose_unavailable,
            "handsEnabled": settings.hands_enabled,
            "handsAvailable": not self._hands_unavailable,
            "bodyKeypoints": len(COCO_KEYPOINT_NAMES),
            "handLandmarks": len(HAND_LANDMARK_NAMES),
        }

    def _ensure_pose(self) -> bool:
        """Load the body pose model on first use."""
        if self._pose_model is not None:
            return True
        if self._pose_unavailable or not settings.pose_enabled:
            return False

        with self._lock:
            if self._pose_model is not None:
                return True
            if self._pose_unavailable:
                return False
            try:
                from ultralytics import YOLO

                name = settings.pose_model
                weights = settings.models_path / f"{name}.pt"
                self._pose_model = YOLO(str(weights) if weights.exists() else f"{name}.pt")
                logger.info(f"Pose model ready: {name}")
                return True
            except Exception as e:
                self._pose_unavailable = True
                logger.warning(f"Body pose unavailable: {e}")
                return False

    def _ensure_hands(self) -> bool:
        """Load the hand landmark model on first use."""
        if self._hands is not None:
            return True
        if self._hands_unavailable or not settings.hands_enabled:
            return False

        with self._lock:
            if self._hands is not None:
                return True
            if self._hands_unavailable:
                return False
            try:
                import mediapipe as mp

                self._hands = mp.solutions.hands.Hands(
                    static_image_mode=False,
                    max_num_hands=settings.hands_max_number,
                    min_detection_confidence=settings.hands_confidence_threshold,
                    min_tracking_confidence=settings.hands_confidence_threshold,
                )
                logger.info("Hand landmark model ready")
                return True
            except Exception as e:
                self._hands_unavailable = True
                logger.warning(f"Hand landmarks unavailable: {e}")
                return False

    def extract_bodies(self, frame: np.ndarray) -> List[Skeleton]:
        """
        Find every person in a frame and return their COCO 17 skeleton.

        Args:
            frame: Full BGR frame.

        Returns:
            List[Skeleton]: One entry per person with enough visible joints.
        """
        if not self._ensure_pose():
            return []

        try:
            results = self._pose_model(
                frame, conf=settings.pose_confidence_threshold, verbose=False
            )
        except Exception as e:
            logger.debug(f"Pose inference failed: {e}")
            return []

        skeletons: List[Skeleton] = []
        threshold = settings.pose_keypoint_threshold

        for result in results:
            keypoint_data = getattr(result, "keypoints", None)
            boxes = getattr(result, "boxes", None)
            if keypoint_data is None or keypoint_data.xy is None:
                continue

            coordinates = keypoint_data.xy.cpu().numpy()
            confidences = (
                keypoint_data.conf.cpu().numpy()
                if keypoint_data.conf is not None
                else np.ones(coordinates.shape[:2], dtype=np.float32)
            )

            for index in range(coordinates.shape[0]):
                points: List[Keypoint] = []
                for joint in range(min(len(COCO_KEYPOINT_NAMES), coordinates.shape[1])):
                    x, y = coordinates[index][joint]
                    score = float(confidences[index][joint])
                    # A joint below the threshold is reported with score 0 rather
                    # than dropped, so indices keep matching the edge list.
                    points.append(
                        Keypoint(
                            name=COCO_KEYPOINT_NAMES[joint],
                            x=float(x),
                            y=float(y),
                            score=score if score >= threshold else 0.0,
                        )
                    )

                visible = [p for p in points if p.score > 0.0]
                if len(visible) < 3:
                    continue

                if boxes is not None and index < len(boxes):
                    x1, y1, x2, y2 = boxes.xyxy[index].cpu().numpy()
                    box = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
                    score = float(boxes.conf[index].cpu().numpy())
                else:
                    xs = [p.x for p in visible]
                    ys = [p.y for p in visible]
                    box = (
                        int(min(xs)),
                        int(min(ys)),
                        int(max(xs) - min(xs)),
                        int(max(ys) - min(ys)),
                    )
                    score = float(np.mean([p.score for p in visible]))

                skeletons.append(
                    Skeleton(kind="body", keypoints=points, bbox=box, score=score)
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
        if not self._ensure_hands():
            return []

        try:
            import cv2

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._hands.process(rgb)
        except Exception as e:
            logger.debug(f"Hand inference failed: {e}")
            return []

        landmark_sets = getattr(results, "multi_hand_landmarks", None)
        if not landmark_sets:
            return []

        handedness = getattr(results, "multi_handedness", None)
        height, width = frame.shape[:2]
        skeletons: List[Skeleton] = []

        for index, landmarks in enumerate(landmark_sets):
            points: List[Keypoint] = []
            for joint, landmark in enumerate(landmarks.landmark):
                if joint >= len(HAND_LANDMARK_NAMES):
                    break
                points.append(
                    Keypoint(
                        name=HAND_LANDMARK_NAMES[joint],
                        # MediaPipe reports normalised coordinates; the frontend
                        # draws in frame pixels like every other overlay.
                        x=float(landmark.x * width),
                        y=float(landmark.y * height),
                        score=1.0,
                    )
                )

            if not points:
                continue

            label = None
            score = 1.0
            if handedness is not None and index < len(handedness):
                classification = handedness[index].classification[0]
                label = classification.label
                score = float(classification.score)

            xs = [p.x for p in points]
            ys = [p.y for p in points]
            box = (
                int(min(xs)),
                int(min(ys)),
                int(max(xs) - min(xs)),
                int(max(ys) - min(ys)),
            )

            skeletons.append(
                Skeleton(kind="hand", keypoints=points, bbox=box, score=score, label=label)
            )

        return skeletons

    def extract(self, frame: np.ndarray) -> Tuple[List[Skeleton], float]:
        """
        Extract every skeleton in a frame.

        Args:
            frame: Full BGR frame.

        Returns:
            Tuple of (skeletons, processing time in milliseconds).
        """
        if not self.enabled:
            return [], 0.0

        start = time.perf_counter()
        skeletons = self.extract_bodies(frame) + self.extract_hands(frame)
        elapsed = (time.perf_counter() - start) * 1000
        return skeletons, elapsed


_pose_service: Optional[PoseService] = None


def get_pose_service() -> PoseService:
    """Get the pose service singleton."""
    global _pose_service
    if _pose_service is None:
        _pose_service = PoseService()
    return _pose_service
