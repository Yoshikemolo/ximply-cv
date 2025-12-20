"""
Barcode detection service.

Uses OpenCV's built-in barcode detector to detect and decode barcodes including EAN, UPC, etc.
No external C libraries required - pure Python with OpenCV.
"""

from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class BarcodeResult:
    """Single barcode detection result."""

    barcode_type: str  # EAN13, EAN8, UPC_A, UPC_E, etc.
    data: str  # The decoded barcode value
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    polygon: List[Tuple[int, int]]  # Corner points
    quality: float  # Detection quality (0-1)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "barcodeType": self.barcode_type,
            "data": self.data,
            "bbox": {
                "x": self.bbox[0],
                "y": self.bbox[1],
                "width": self.bbox[2],
                "height": self.bbox[3],
            },
            "polygon": [{"x": p[0], "y": p[1]} for p in self.polygon],
            "quality": self.quality,
        }


class BarcodeService:
    """
    Service for detecting and decoding barcodes in images.

    Uses OpenCV's BarcodeDetector which supports:
    - EAN-8, EAN-13
    - UPC-A, UPC-E
    - Code39, Code93, Code128
    - And more standard 1D barcodes
    """

    def __init__(self):
        self._detector = None
        self._qr_detector = None

    @property
    def detector(self):
        """Lazy load the barcode detector."""
        if self._detector is None:
            try:
                self._detector = cv2.barcode.BarcodeDetector()
                logger.info("OpenCV BarcodeDetector initialized")
            except AttributeError:
                logger.warning("OpenCV BarcodeDetector not available in this version")
                self._detector = False
        return self._detector if self._detector else None

    @property
    def qr_detector(self):
        """Lazy load the QR code detector."""
        if self._qr_detector is None:
            self._qr_detector = cv2.QRCodeDetector()
        return self._qr_detector

    def detect_from_base64(self, image_base64: str) -> List[BarcodeResult]:
        """
        Detect barcodes in a base64 encoded image.

        Args:
            image_base64: Base64 encoded image (with or without data URI prefix).

        Returns:
            List of detected barcodes.
        """
        import base64

        # Decode base64 image
        if "," in image_base64:
            image_base64 = image_base64.split(",")[1]

        image_bytes = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_bytes))

        # Convert to numpy array
        frame = np.array(image)

        return self.detect(frame)

    def detect(self, frame: np.ndarray) -> List[BarcodeResult]:
        """
        Detect barcodes in a numpy array image.

        Args:
            frame: Image as numpy array (RGB or BGR).

        Returns:
            List of detected barcodes.
        """
        results = []

        # Convert to grayscale for better detection
        if len(frame.shape) == 3:
            if frame.shape[2] == 4:  # RGBA
                gray = cv2.cvtColor(frame, cv2.COLOR_RGBA2GRAY)
            else:  # RGB or BGR
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        else:
            gray = frame

        # Detect 1D barcodes using OpenCV BarcodeDetector
        if self.detector:
            try:
                # OpenCV 4.x detectAndDecode returns: (retval, decoded_info, decoded_type, points)
                # But some versions return only 3 values: (decoded_info, decoded_type, points)
                detect_result = self.detector.detectAndDecode(gray)

                if len(detect_result) == 4:
                    retval, decoded_info, decoded_type, points = detect_result
                elif len(detect_result) == 3:
                    decoded_info, decoded_type, points = detect_result
                    retval = decoded_info is not None and len(decoded_info) > 0
                else:
                    retval = False
                    decoded_info = None
                    decoded_type = None
                    points = None

                if retval and decoded_info is not None:
                    # Handle both single and multiple barcode detection
                    if isinstance(decoded_info, str):
                        # Single barcode detected
                        decoded_info = [decoded_info]
                        decoded_type = [decoded_type] if not isinstance(decoded_type, (list, tuple)) else decoded_type
                        if points is not None and len(points.shape) == 2:
                            points = [points]

                    for i, data in enumerate(decoded_info):
                        if data:  # Only process successfully decoded barcodes
                            # Get barcode type
                            barcode_type = decoded_type[i] if i < len(decoded_type) else 0

                            # Get bounding box from points
                            if points is not None and len(points) > i:
                                pts = points[i].astype(int)
                                x_min = int(pts[:, 0].min())
                                y_min = int(pts[:, 1].min())
                                x_max = int(pts[:, 0].max())
                                y_max = int(pts[:, 1].max())

                                bbox = (x_min, y_min, x_max - x_min, y_max - y_min)
                                polygon = [(int(p[0]), int(p[1])) for p in pts]
                            else:
                                bbox = (0, 0, frame.shape[1], frame.shape[0])
                                polygon = []

                            # Map OpenCV barcode type to readable name
                            type_name = self._get_barcode_type_name(barcode_type)

                            result = BarcodeResult(
                                barcode_type=type_name,
                                data=data,
                                bbox=bbox,
                                polygon=polygon,
                                quality=0.9,  # OpenCV doesn't provide confidence
                            )
                            results.append(result)

            except Exception as e:
                logger.debug(f"Barcode detection error: {e}")

        # Also try QR code detection
        try:
            qr_data, qr_points, _ = self.qr_detector.detectAndDecode(gray)

            if qr_data and qr_points is not None:
                pts = qr_points[0].astype(int)
                x_min = int(pts[:, 0].min())
                y_min = int(pts[:, 1].min())
                x_max = int(pts[:, 0].max())
                y_max = int(pts[:, 1].max())

                result = BarcodeResult(
                    barcode_type="QR",
                    data=qr_data,
                    bbox=(x_min, y_min, x_max - x_min, y_max - y_min),
                    polygon=[(int(p[0]), int(p[1])) for p in pts],
                    quality=0.95,
                )
                results.append(result)

        except Exception as e:
            logger.debug(f"QR detection error: {e}")

        if results:
            logger.debug(f"Detected {len(results)} barcodes/QR codes")

        return results

    def _get_barcode_type_name(self, barcode_type: int) -> str:
        """
        Convert OpenCV barcode type constant to readable name.

        Args:
            barcode_type: OpenCV barcode type constant.

        Returns:
            Human-readable barcode type name.
        """
        # OpenCV barcode type constants
        type_names = {
            0: "NONE",
            1: "EAN_8",
            2: "EAN_13",
            3: "UPC_A",
            4: "UPC_E",
            5: "UPC_EAN_EXTENSION",
        }
        return type_names.get(barcode_type, f"TYPE_{barcode_type}")

    def detect_in_region(
        self,
        frame: np.ndarray,
        x: int,
        y: int,
        width: int,
        height: int,
        padding: int = 10,
    ) -> List[BarcodeResult]:
        """
        Detect barcodes in a specific region of an image.

        Args:
            frame: Full image as numpy array.
            x, y, width, height: Region bounding box.
            padding: Extra padding around the region.

        Returns:
            List of detected barcodes with coordinates relative to full image.
        """
        # Crop region with padding
        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(frame.shape[1], x + width + padding)
        y2 = min(frame.shape[0], y + height + padding)

        region = frame[y1:y2, x1:x2]

        # Detect in region
        results = self.detect(region)

        # Adjust coordinates to full image
        adjusted_results = []
        for result in results:
            adjusted_bbox = (
                result.bbox[0] + x1,
                result.bbox[1] + y1,
                result.bbox[2],
                result.bbox[3],
            )
            adjusted_polygon = [
                (p[0] + x1, p[1] + y1) for p in result.polygon
            ]
            adjusted_results.append(
                BarcodeResult(
                    barcode_type=result.barcode_type,
                    data=result.data,
                    bbox=adjusted_bbox,
                    polygon=adjusted_polygon,
                    quality=result.quality,
                )
            )

        return adjusted_results


# Global service instance
_barcode_service: Optional[BarcodeService] = None


def get_barcode_service() -> BarcodeService:
    """Get the barcode service singleton."""
    global _barcode_service
    if _barcode_service is None:
        _barcode_service = BarcodeService()
    return _barcode_service
