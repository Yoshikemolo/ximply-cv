"""
Detection service using YOLO for object detection.

Provides real-time object detection using Ultralytics YOLO models.
"""

import base64
import time
from io import BytesIO
from typing import List, Optional, Tuple
from uuid import UUID

import cv2
import numpy as np
from PIL import Image

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Lazy load YOLO to avoid import errors if not installed
_model = None


def get_model():
    """Get or initialize the YOLO model (lazy loading)."""
    global _model
    if _model is None:
        try:
            from ultralytics import YOLO

            model_name = settings.detection_model
            logger.info(f"Loading YOLO model: {model_name}")

            # Try to load from weights path first, then download
            weights_path = settings.models_path / f"{model_name}.pt"
            if weights_path.exists():
                _model = YOLO(str(weights_path))
                logger.info(f"Loaded model from: {weights_path}")
            else:
                # Download model (will be cached)
                _model = YOLO(f"{model_name}.pt")
                logger.info(f"Downloaded model: {model_name}")

        except ImportError:
            logger.error("Ultralytics not installed. Install with: pip install ultralytics")
            raise RuntimeError("YOLO not available")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            raise

    return _model


class DetectionResult:
    """Single detection result."""

    def __init__(
        self,
        label: str,
        confidence: float,
        bbox: Tuple[int, int, int, int],
        class_id: int,
        object_id: Optional[UUID] = None,
        object_name: Optional[str] = None,
    ):
        self.label = label
        self.confidence = confidence
        self.x, self.y, self.width, self.height = bbox
        self.class_id = class_id
        self.object_id = object_id
        self.object_name = object_name

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "label": self.label,
            "confidence": self.confidence,
            "bbox": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
            "classId": self.class_id,
            "objectId": str(self.object_id) if self.object_id else None,
            "objectName": self.object_name,
        }


class DetectionService:
    """Service for running object detection on images."""

    def __init__(self):
        self._model = None

    @property
    def model(self):
        """Lazy load the model."""
        if self._model is None:
            self._model = get_model()
        return self._model

    def detect_from_base64(
        self,
        image_base64: str,
        confidence_threshold: Optional[float] = None,
        iou_threshold: Optional[float] = None,
    ) -> Tuple[List[DetectionResult], float, Tuple[int, int]]:
        """
        Run detection on a base64 encoded image.

        Args:
            image_base64: Base64 encoded image (with or without data URI prefix).
            confidence_threshold: Minimum confidence for detections.
            iou_threshold: IOU threshold for NMS.

        Returns:
            Tuple of (detections, processing_time_ms, (width, height))
        """
        # Decode base64 image
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]

        image_bytes = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_bytes))

        # Convert to numpy array (RGB)
        frame = np.array(image)

        return self.detect(frame, confidence_threshold, iou_threshold)

    def detect(
        self,
        frame: np.ndarray,
        confidence_threshold: Optional[float] = None,
        iou_threshold: Optional[float] = None,
    ) -> Tuple[List[DetectionResult], float, Tuple[int, int]]:
        """
        Run detection on a numpy array image.

        Args:
            frame: Image as numpy array (RGB or BGR).
            confidence_threshold: Minimum confidence for detections.
            iou_threshold: IOU threshold for NMS.

        Returns:
            Tuple of (detections, processing_time_ms, (width, height))
        """
        conf = confidence_threshold or settings.detection_confidence_threshold
        iou = iou_threshold or settings.detection_iou_threshold

        start_time = time.perf_counter()

        # Run inference
        results = self.model(
            frame,
            conf=conf,
            iou=iou,
            verbose=False,
        )

        processing_time = (time.perf_counter() - start_time) * 1000

        # Parse results
        detections = []
        height, width = frame.shape[:2]

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i, box in enumerate(boxes):
                # Get coordinates (xyxy format)
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

                # Convert to x, y, width, height
                bbox = (
                    int(x1),
                    int(y1),
                    int(x2 - x1),
                    int(y2 - y1),
                )

                class_id = int(box.cls[0].cpu().numpy())
                confidence = float(box.conf[0].cpu().numpy())
                label = result.names[class_id]

                detection = DetectionResult(
                    label=label,
                    confidence=confidence,
                    bbox=bbox,
                    class_id=class_id,
                )
                detections.append(detection)

        logger.debug(
            f"Detection completed: {len(detections)} objects in {processing_time:.1f}ms"
        )

        return detections, processing_time, (width, height)


# Global service instance
_detection_service: Optional[DetectionService] = None


def get_detection_service() -> DetectionService:
    """Get the detection service singleton."""
    global _detection_service
    if _detection_service is None:
        _detection_service = DetectionService()
    return _detection_service
