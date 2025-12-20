"""
Feature matching service for custom object recognition.

Uses OpenCV ORB features to match detected objects against catalog objects.
"""

import base64
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import cv2
import numpy as np
from PIL import Image

from app.core.logging import get_logger
from app.core.minio_client import download_file

logger = get_logger(__name__)


class ObjectFeatures:
    """Stored features for a catalog object."""

    def __init__(
        self,
        object_id: UUID,
        object_name: str,
        keypoints: List[cv2.KeyPoint],
        descriptors: np.ndarray,
    ):
        self.object_id = object_id
        self.object_name = object_name
        self.keypoints = keypoints
        self.descriptors = descriptors


class FeatureMatchingService:
    """
    Service for matching detected objects against catalog objects.

    Uses ORB (Oriented FAST and Rotated BRIEF) features for matching.
    ORB is fast and works well for object recognition.
    """

    def __init__(self, min_match_count: int = 10, match_ratio: float = 0.75):
        """
        Initialize the feature matching service.

        Args:
            min_match_count: Minimum number of good matches required.
            match_ratio: Ratio test threshold for filtering matches.
        """
        self.min_match_count = min_match_count
        self.match_ratio = match_ratio

        # Initialize ORB detector
        self.orb = cv2.ORB_create(nfeatures=500)

        # Initialize brute-force matcher with Hamming distance
        self.bf_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

        # Cache of object features: object_id -> ObjectFeatures
        self._object_cache: Dict[UUID, ObjectFeatures] = {}

    def extract_features(self, image: np.ndarray) -> Tuple[List[cv2.KeyPoint], Optional[np.ndarray]]:
        """
        Extract ORB features from an image.

        Args:
            image: Image as numpy array (BGR or RGB).

        Returns:
            Tuple of (keypoints, descriptors). Descriptors may be None if no features found.
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Detect and compute features
        keypoints, descriptors = self.orb.detectAndCompute(gray, None)

        return keypoints, descriptors

    def load_object_features(
        self,
        object_id: UUID,
        object_name: str,
        image_paths: List[str],
    ) -> bool:
        """
        Load and cache features for a catalog object.

        Args:
            object_id: Object UUID.
            object_name: Object name.
            image_paths: List of image file paths in MinIO.

        Returns:
            bool: True if features were loaded successfully.
        """
        all_keypoints = []
        all_descriptors = []

        for path in image_paths:
            try:
                # Download image from MinIO
                image_data = download_file(path)
                if image_data is None:
                    continue

                # Convert to numpy array
                image = Image.open(BytesIO(image_data))
                frame = np.array(image)

                # Convert RGB to BGR for OpenCV
                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                # Extract features
                keypoints, descriptors = self.extract_features(frame)

                if descriptors is not None:
                    all_keypoints.extend(keypoints)
                    all_descriptors.append(descriptors)

            except Exception as e:
                logger.warning(f"Failed to load features from {path}: {e}")
                continue

        if not all_descriptors:
            logger.warning(f"No features extracted for object {object_id}")
            return False

        # Combine all descriptors
        combined_descriptors = np.vstack(all_descriptors)

        # Cache the features
        self._object_cache[object_id] = ObjectFeatures(
            object_id=object_id,
            object_name=object_name,
            keypoints=all_keypoints,
            descriptors=combined_descriptors,
        )

        logger.info(
            f"Loaded {len(combined_descriptors)} features for object '{object_name}'"
        )
        return True

    def match_region(
        self,
        region: np.ndarray,
    ) -> Optional[Tuple[UUID, str, float]]:
        """
        Match a detected region against cached catalog objects.

        Args:
            region: Cropped image region as numpy array.

        Returns:
            Tuple of (object_id, object_name, confidence) if match found, None otherwise.
        """
        if not self._object_cache:
            return None

        # Extract features from the query region
        query_keypoints, query_descriptors = self.extract_features(region)

        if query_descriptors is None or len(query_descriptors) < 4:
            return None

        best_match = None
        best_score = 0.0

        for obj_features in self._object_cache.values():
            if obj_features.descriptors is None:
                continue

            try:
                # Find matches using KNN
                matches = self.bf_matcher.knnMatch(
                    query_descriptors,
                    obj_features.descriptors,
                    k=2,
                )

                # Apply ratio test
                good_matches = []
                for m_list in matches:
                    if len(m_list) >= 2:
                        m, n = m_list[0], m_list[1]
                        if m.distance < self.match_ratio * n.distance:
                            good_matches.append(m)

                # Calculate match score
                if len(good_matches) >= self.min_match_count:
                    # Score based on number of matches and their quality
                    avg_distance = np.mean([m.distance for m in good_matches])
                    match_ratio = len(good_matches) / len(query_descriptors)

                    # Normalize score (lower distance = better match)
                    # ORB distance typically ranges from 0-256
                    distance_score = 1.0 - (avg_distance / 256.0)
                    score = match_ratio * distance_score

                    if score > best_score:
                        best_score = score
                        best_match = (
                            obj_features.object_id,
                            obj_features.object_name,
                            min(score * 1.5, 0.99),  # Scale up but cap at 0.99
                        )

            except Exception as e:
                logger.warning(f"Match error for object {obj_features.object_id}: {e}")
                continue

        return best_match

    def clear_cache(self) -> None:
        """Clear the cached object features."""
        self._object_cache.clear()
        logger.info("Feature cache cleared")

    def remove_object(self, object_id: UUID) -> bool:
        """
        Remove an object from the cache.

        Args:
            object_id: Object UUID to remove.

        Returns:
            bool: True if object was removed.
        """
        if object_id in self._object_cache:
            del self._object_cache[object_id]
            return True
        return False


# Global service instance
_feature_service: Optional[FeatureMatchingService] = None


def get_feature_matching_service() -> FeatureMatchingService:
    """Get the feature matching service singleton."""
    global _feature_service
    if _feature_service is None:
        _feature_service = FeatureMatchingService()
    return _feature_service
