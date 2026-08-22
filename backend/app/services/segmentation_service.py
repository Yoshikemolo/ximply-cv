"""
Object silhouettes through Segment Anything.

Turns the rectangles produced by the detector into the actual outline of each
object. Detection and segmentation answer different questions and neither
replaces the other: the detector says what a thing is and roughly where, while
Segment Anything says exactly where its edge runs but has no idea what it is
looking at. Running the detector first and prompting the segmenter with its
boxes keeps the labels, the catalog match and the person identity, and adds the
outline on top.

Contours come back with well over a thousand points for a large object, which
is far more than a canvas stroke can show and far more than is worth sending
every frame. Each one is simplified with the Douglas-Peucker algorithm to the
smallest polygon that still follows the shape.

A box prompt is ambiguous by nature: the rectangle around a person also contains
the chair behind them, and Segment Anything cannot know which of the two was
meant. Two levers narrow it down.

Tightness picks among the three candidates the model offers per prompt. They
differ in granularity, from a part of the subject up to the subject plus
whatever it is resting against, and the answer the model ranks highest is often
the widest one. Choosing a smaller candidate is what stops a silhouette
swallowing the background.

Excluding siblings uses something only this application knows: the detector has
already found the chair, the table and the cup separately. Their centres are fed
back as negative points, telling the segmenter that whatever else the subject
is, it is not those.
"""

import threading
import time
from typing import List, Optional, Sequence, Tuple

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.acceleration_service import get_acceleration_service

logger = get_logger(__name__)


class SegmentationService:
    """
    Prompts Segment Anything with detection boxes and returns polygons.

    The model loads lazily and fails soft: when it cannot be obtained the
    service stops offering silhouettes and detection carries on with plain
    rectangles.
    """

    def __init__(self) -> None:
        self._model = None
        self._unavailable = False
        self._lock = threading.Lock()
        self._loaded_name: Optional[str] = None

    @property
    def available(self) -> bool:
        """Whether silhouettes can be produced."""
        return not self._unavailable

    def describe(self) -> dict:
        """Report the state of the segmenter for the status endpoint."""
        return {
            "enabled": settings.segmentation_enabled,
            "available": self.available,
            "model": self._loaded_name or settings.segmentation_model,
            "tightness": settings.segmentation_tightness,
            "excludeSiblings": settings.segmentation_exclude_siblings,
        }

    def _ensure_loaded(self):
        """Load the configured Segment Anything weights on first use."""
        if self._model is not None:
            return self._model
        if self._unavailable or not settings.segmentation_enabled:
            return None

        with self._lock:
            if self._model is not None:
                return self._model
            if self._unavailable:
                return None

            try:
                from ultralytics import SAM

                name = settings.segmentation_model
                weights = settings.models_path / f"{name}.pt"
                started = time.perf_counter()
                self._model = SAM(str(weights) if weights.exists() else f"{name}.pt")
                self._loaded_name = name
                logger.info(
                    f"Segmentation model ready: {name} "
                    f"in {time.perf_counter() - started:.1f}s"
                )
                return self._model
            except Exception as e:
                self._unavailable = True
                logger.warning(f"Segmentation unavailable: {e}")
                return None

    def _simplify(self, contour: np.ndarray) -> List[List[float]]:
        """
        Reduce a contour to the fewest points that still trace the same shape.

        Args:
            contour: Nx2 array of pixel coordinates.

        Returns:
            List of [x, y] pairs, at most segmentation_max_points long.
        """
        import cv2

        if contour is None or len(contour) < 3:
            return []

        points = np.asarray(contour, dtype=np.float32).reshape(-1, 1, 2)
        perimeter = cv2.arcLength(points, True)
        if perimeter <= 0:
            return []

        # Start at a tolerance of a few parts per thousand of the perimeter and
        # loosen it until the polygon fits the budget. A fixed tolerance would
        # either mangle small objects or leave large ones far too heavy.
        tolerance = perimeter * 0.002
        limit = settings.segmentation_max_points
        approximated = points

        for _ in range(8):
            approximated = cv2.approxPolyDP(points, tolerance, True)
            if len(approximated) <= limit:
                break
            tolerance *= 1.8
        else:
            approximated = approximated[:limit]

        return [[float(p[0][0]), float(p[0][1])] for p in approximated]

    def _negative_points(
        self,
        box: Tuple[float, float, float, float],
        siblings: Sequence[Tuple[float, float, float, float]],
    ) -> List[List[float]]:
        """
        Centres of other detections that fall inside this box.

        Only a sibling whose centre lies within the box can pollute its mask, so
        the rest are ignored rather than loading the prompt with points the
        segmenter would never have reached anyway.

        Args:
            box: The box being segmented, in xyxy.
            siblings: Every other detection box in the frame, in xyxy.

        Returns:
            List of [x, y] points to mark as background.
        """
        x1, y1, x2, y2 = box
        points: List[List[float]] = []
        for other in siblings:
            cx = (other[0] + other[2]) / 2
            cy = (other[1] + other[3]) / 2
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                points.append([cx, cy])
        return points

    def _choose_mask(
        self,
        masks: np.ndarray,
        scores: np.ndarray,
        box_area: float,
        tightness: float,
    ) -> Optional[np.ndarray]:
        """
        Pick one of the candidate masks according to the tightness setting.

        The model ranks candidates by predicted overlap, which favours the
        widest reading of an ambiguous prompt. Candidates far below the best
        score are dropped as noise, anything covering more of its box than the
        ceiling allows is treated as having bled into the background, and the
        survivors are ordered by area so tightness can choose along that axis.

        Args:
            masks: Candidate masks, shape (candidates, height, width).
            scores: Predicted quality per candidate.
            box_area: Area of the prompting box in the same resolution as the
                masks, for the coverage ceiling.
            tightness: 0 keeps the widest candidate, 1 the narrowest.

        Returns:
            The chosen mask as a boolean array, or None when nothing is usable.
        """
        if masks.size == 0:
            return None

        best_score = float(np.max(scores)) if scores.size else 0.0
        candidates: List[Tuple[float, float, int]] = []

        for index in range(masks.shape[0]):
            area = float((masks[index] > 0).sum())
            if area <= 0:
                continue
            score = float(scores[index]) if index < scores.size else 0.0
            if best_score - score > 0.2:
                continue
            candidates.append((area, score, index))

        if not candidates:
            return None

        # Drop anything that filled its box, which is what a mask looks like
        # once it has escaped onto the furniture behind the subject. If every
        # candidate did, keep them all rather than returning nothing.
        if box_area > 0:
            ceiling = settings.segmentation_max_coverage
            within = [c for c in candidates if c[0] / box_area <= ceiling]
            if within:
                candidates = within

        candidates.sort(key=lambda candidate: candidate[0])
        clamped = min(1.0, max(0.0, tightness))
        position = int(round((1.0 - clamped) * (len(candidates) - 1)))
        return masks[candidates[position][2]] > 0

    def segment_boxes(
        self,
        frame: np.ndarray,
        boxes: Sequence[Tuple[float, float, float, float]],
        tightness: Optional[float] = None,
        exclude_siblings: Optional[bool] = None,
    ) -> Tuple[List[List[List[float]]], float]:
        """
        Produce one silhouette per detection box.

        Boxes are prompted one at a time rather than in a batch, because the
        negative points that keep a mask off the furniture behind the subject
        differ for every box. The image is encoded once and reused, so each
        extra box costs only a decoder pass.

        Args:
            frame: Full BGR frame.
            boxes: Boxes in xyxy pixel coordinates, one per detection.
            tightness: 0 keeps the widest candidate mask, 1 the narrowest.
                Falls back to the configured default when not given.
            exclude_siblings: Whether other detections inside a box are marked
                as background. Falls back to the configured default.

        Returns:
            Tuple of (polygons aligned with the boxes, processing milliseconds).
            A box the model could not segment yields an empty polygon, so the
            caller can keep the two lists in step by index.
        """
        if not boxes:
            return [], 0.0

        model = self._ensure_loaded()
        if model is None:
            return [[] for _ in boxes], 0.0

        started = time.perf_counter()
        device = get_acceleration_service().ultralytics_device
        polygons: List[List[List[float]]] = [[] for _ in boxes]

        if tightness is None:
            tightness = settings.segmentation_tightness
        if exclude_siblings is None:
            exclude_siblings = settings.segmentation_exclude_siblings

        try:
            import cv2
            import torch

            # One call through the public interface sets the predictor up.
            model(frame, bboxes=[list(boxes[0])], verbose=False, device=device)
            predictor = model.predictor
            height, width = frame.shape[:2]

            with torch.no_grad():
                # Encode the frame once. Without this the prompt call re-runs the
                # image encoder for every box, which is the whole cost of a frame
                # paid once per detection.
                predictor.set_image(frame)
                # set_image caches the encoder output but leaves the tensor
                # itself elsewhere, and the prompt call still wants one for its
                # shape. Preprocessing again is only a resize and a normalise.
                image = predictor.preprocess([frame])

                for index, box in enumerate(boxes):
                    points = None
                    labels = None

                    if exclude_siblings:
                        siblings = [b for j, b in enumerate(boxes) if j != index]
                        negatives = self._negative_points(box, siblings)
                        if negatives:
                            centre = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
                            points = np.array([[centre] + negatives], dtype=np.float32)
                            labels = np.array(
                                [[1] + [0] * len(negatives)], dtype=np.int32
                            )

                    masks, scores = predictor.inference(
                        image,
                        bboxes=np.array([list(box)], dtype=np.float32),
                        points=points,
                        labels=labels,
                        multimask_output=True,
                    )

                    candidates = masks.detach().float().cpu().numpy()
                    candidates = candidates.reshape(
                        -1, candidates.shape[-2], candidates.shape[-1]
                    )
                    candidate_scores = scores.detach().float().cpu().numpy().reshape(-1)

                    # Candidates come at model resolution, so the box is scaled
                    # the same way before the coverage ceiling is applied.
                    scale = (candidates.shape[-1] / width) * (candidates.shape[-2] / height)
                    box_area = max(1.0, (box[2] - box[0]) * (box[3] - box[1])) * scale

                    chosen = self._choose_mask(
                        candidates, candidate_scores, box_area, tightness
                    )
                    if chosen is None:
                        continue

                    full = cv2.resize(
                        chosen.astype(np.uint8),
                        (width, height),
                        interpolation=cv2.INTER_NEAREST,
                    )
                    contours, _ = cv2.findContours(
                        full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                    )
                    if not contours:
                        continue

                    largest = max(contours, key=cv2.contourArea)
                    polygons[index] = self._simplify(largest.reshape(-1, 2))

        except Exception as e:
            logger.debug(f"Segmentation failed: {e}")
            return [[] for _ in boxes], (time.perf_counter() - started) * 1000
        finally:
            # Cached features belong to the frame that produced them, so they
            # must not survive into the next one.
            try:
                if model.predictor is not None:
                    model.predictor.reset_image()
            except Exception:
                pass

        elapsed = (time.perf_counter() - started) * 1000
        return polygons, elapsed


_segmentation_service: Optional[SegmentationService] = None


def get_segmentation_service() -> SegmentationService:
    """Get the segmentation service singleton."""
    global _segmentation_service
    if _segmentation_service is None:
        _segmentation_service = SegmentationService()
    return _segmentation_service
