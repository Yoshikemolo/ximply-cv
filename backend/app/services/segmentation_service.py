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

        for _ in range(8):
            approximated = cv2.approxPolyDP(points, tolerance, True)
            if len(approximated) <= limit:
                break
            tolerance *= 1.8
        else:
            approximated = approximated[:limit]

        return [[float(p[0][0]), float(p[0][1])] for p in approximated]

    def segment_boxes(
        self,
        frame: np.ndarray,
        boxes: Sequence[Tuple[float, float, float, float]],
    ) -> Tuple[List[List[List[float]]], float]:
        """
        Produce one silhouette per detection box.

        Args:
            frame: Full BGR frame.
            boxes: Boxes in xyxy pixel coordinates, one per detection.

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

        try:
            results = model(
                frame,
                bboxes=[list(box) for box in boxes],
                verbose=False,
                device=get_acceleration_service().ultralytics_device,
            )
        except Exception as e:
            logger.debug(f"Segmentation failed: {e}")
            return [[] for _ in boxes], (time.perf_counter() - started) * 1000

        polygons: List[List[List[float]]] = [[] for _ in boxes]

        for result in results:
            masks = getattr(result, "masks", None)
            if masks is None or masks.xy is None:
                continue
            for index, contour in enumerate(masks.xy):
                if index >= len(polygons):
                    break
                polygons[index] = self._simplify(contour)

        elapsed = (time.perf_counter() - started) * 1000
        return polygons, elapsed


_segmentation_service: Optional[SegmentationService] = None


def get_segmentation_service() -> SegmentationService:
    """Get the segmentation service singleton."""
    global _segmentation_service
    if _segmentation_service is None:
        _segmentation_service = SegmentationService()
    return _segmentation_service
