"""
Barcode detection service.

Uses pyzbar (ZBar) for reliable barcode and QR code detection.
"""

from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)

# Try to import pyzbar
try:
    from pyzbar import pyzbar
    from pyzbar.pyzbar import ZBarSymbol
    PYZBAR_AVAILABLE = True
    logger.info("pyzbar loaded successfully")
except ImportError:
    PYZBAR_AVAILABLE = False
    logger.warning("pyzbar not available, barcode detection will be limited")


@dataclass
class BarcodeResult:
    """Single barcode detection result."""

    barcode_type: str  # EAN13, EAN8, UPC_A, UPC_E, QRCODE, etc.
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

    Uses pyzbar (ZBar) which supports:
    - EAN-8, EAN-13
    - UPC-A, UPC-E
    - Code39, Code93, Code128
    - QR codes
    - And more standard barcodes
    """

    def __init__(self):
        self._opencv_detector = None
        self._opencv_qr_detector = None

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
            else:  # RGB or BGR - both work with pyzbar
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Primary: Use pyzbar (more reliable)
        if PYZBAR_AVAILABLE:
            try:
                # Decode all barcodes in the image
                decoded = pyzbar.decode(gray)

                for barcode in decoded:
                    # Get barcode data
                    data = barcode.data.decode('utf-8', errors='replace')
                    barcode_type = barcode.type

                    # Get bounding box
                    rect = barcode.rect
                    bbox = (rect.left, rect.top, rect.width, rect.height)

                    # Get polygon points
                    polygon = [(p.x, p.y) for p in barcode.polygon]

                    # Quality based on how well-formed the barcode data is
                    quality = 0.95 if data else 0.5

                    result = BarcodeResult(
                        barcode_type=barcode_type,
                        data=data,
                        bbox=bbox,
                        polygon=polygon,
                        quality=quality,
                    )
                    results.append(result)
                    logger.debug(f"pyzbar detected: {barcode_type} = {data[:50] if len(data) > 50 else data}")

            except Exception as e:
                logger.warning(f"pyzbar detection error: {e}")

        # Fallback: Use OpenCV QRCodeDetector if pyzbar found nothing
        if not results:
            try:
                if self._opencv_qr_detector is None:
                    self._opencv_qr_detector = cv2.QRCodeDetector()

                qr_data, qr_points, _ = self._opencv_qr_detector.detectAndDecode(gray)

                if qr_data and qr_points is not None:
                    pts = qr_points[0].astype(int)
                    x_min = int(pts[:, 0].min())
                    y_min = int(pts[:, 1].min())
                    x_max = int(pts[:, 0].max())
                    y_max = int(pts[:, 1].max())

                    result = BarcodeResult(
                        barcode_type="QRCODE",
                        data=qr_data,
                        bbox=(x_min, y_min, x_max - x_min, y_max - y_min),
                        polygon=[(int(p[0]), int(p[1])) for p in pts],
                        quality=0.9,
                    )
                    results.append(result)
                    logger.debug(f"OpenCV QR detected: {qr_data[:50] if len(qr_data) > 50 else qr_data}")

            except Exception as e:
                logger.debug(f"OpenCV QR detection error: {e}")

        if results:
            logger.info(f"Detected {len(results)} barcodes/QR codes")

        return results

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
