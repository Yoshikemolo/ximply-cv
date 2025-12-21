"""
Feature matching service for custom object recognition.

Uses OpenCV ORB features to match detected objects against catalog objects.
"""

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import cv2
import numpy as np
from PIL import Image

from app.core.logging import get_logger
from app.core.minio_client import download_file

logger = get_logger(__name__)


@dataclass
class FeatureLoadResult:
    """Result of loading features for an object."""

    success: bool
    object_id: UUID
    object_name: str
    feature_count: int
    images_processed: int
    images_failed: int
    error_message: Optional[str] = None


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

    def __init__(
        self,
        min_match_count: int = 4,
        match_ratio: float = 0.85,
        min_confidence: float = 0.03,
    ):
        """
        Initialize the feature matching service.

        Args:
            min_match_count: Minimum number of good matches required.
            match_ratio: Ratio test threshold for filtering matches.
            min_confidence: Minimum confidence score to accept a match.
        """
        self.min_match_count = min_match_count
        self.match_ratio = match_ratio
        self.min_confidence = min_confidence

        # Initialize ORB detector with more features for better matching
        self.orb = cv2.ORB_create(nfeatures=1500)

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
    ) -> FeatureLoadResult:
        """
        Load and cache features for a catalog object.

        This method performs an atomic update - it only updates the cache
        if features were successfully extracted. The old features remain
        in cache until new ones are ready.

        Args:
            object_id: Object UUID.
            object_name: Object name.
            image_paths: List of image file paths in MinIO.

        Returns:
            FeatureLoadResult: Detailed result of the operation.
        """
        all_keypoints = []
        all_descriptors = []
        images_processed = 0
        images_failed = 0

        if not image_paths:
            return FeatureLoadResult(
                success=False,
                object_id=object_id,
                object_name=object_name,
                feature_count=0,
                images_processed=0,
                images_failed=0,
                error_message="No image paths provided",
            )

        for path in image_paths:
            try:
                # Download image from MinIO
                image_data = download_file(path)
                if image_data is None:
                    logger.warning(f"Failed to download image from MinIO: {path}")
                    images_failed += 1
                    continue

                # Convert to numpy array
                image = Image.open(BytesIO(image_data))
                frame = np.array(image)

                # Convert RGB to BGR for OpenCV
                if len(frame.shape) == 3 and frame.shape[2] == 3:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                # Extract features
                keypoints, descriptors = self.extract_features(frame)

                if descriptors is not None and len(descriptors) > 0:
                    all_keypoints.extend(keypoints)
                    all_descriptors.append(descriptors)
                    images_processed += 1
                    logger.debug(f"Extracted {len(descriptors)} features from {path}")
                else:
                    logger.warning(f"No features extracted from image: {path}")
                    images_failed += 1

            except Exception as e:
                logger.warning(f"Failed to load features from {path}: {e}")
                images_failed += 1
                continue

        # Validate we have enough features
        if not all_descriptors:
            error_msg = f"No features extracted from any of {len(image_paths)} images"
            logger.warning(f"{error_msg} for object {object_id}")
            return FeatureLoadResult(
                success=False,
                object_id=object_id,
                object_name=object_name,
                feature_count=0,
                images_processed=images_processed,
                images_failed=images_failed,
                error_message=error_msg,
            )

        # Combine all descriptors
        combined_descriptors = np.vstack(all_descriptors)
        feature_count = len(combined_descriptors)

        # Minimum feature threshold for reliable matching
        MIN_FEATURES_REQUIRED = 10
        if feature_count < MIN_FEATURES_REQUIRED:
            error_msg = f"Only {feature_count} features extracted, minimum {MIN_FEATURES_REQUIRED} required"
            logger.warning(f"{error_msg} for object {object_id}")
            return FeatureLoadResult(
                success=False,
                object_id=object_id,
                object_name=object_name,
                feature_count=feature_count,
                images_processed=images_processed,
                images_failed=images_failed,
                error_message=error_msg,
            )

        # Create new features object BEFORE updating cache (atomic preparation)
        new_features = ObjectFeatures(
            object_id=object_id,
            object_name=object_name,
            keypoints=all_keypoints,
            descriptors=combined_descriptors,
        )

        # Atomic update - only update cache after successful extraction
        self._object_cache[object_id] = new_features

        logger.info(
            f"Loaded {feature_count} features for object '{object_name}' "
            f"({images_processed} images processed, {images_failed} failed)"
        )

        return FeatureLoadResult(
            success=True,
            object_id=object_id,
            object_name=object_name,
            feature_count=feature_count,
            images_processed=images_processed,
            images_failed=images_failed,
        )

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
            logger.debug("No objects in feature cache")
            return None

        # Extract features from the query region
        query_keypoints, query_descriptors = self.extract_features(region)

        if query_descriptors is None or len(query_descriptors) < 4:
            logger.debug(f"Insufficient features in query region: {len(query_descriptors) if query_descriptors is not None else 0}")
            return None

        logger.debug(f"Query region has {len(query_descriptors)} features, matching against {len(self._object_cache)} catalog objects")

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

                # Apply ratio test (Lowe's ratio test)
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
                    num_matches = len(good_matches)

                    # Normalize distance score (lower distance = better match)
                    # ORB distance typically ranges from 0-256
                    distance_score = 1.0 - (avg_distance / 256.0)

                    # Score primarily based on absolute match count and distance quality
                    # More matches = higher confidence, regardless of how many query features
                    # 4 matches = 0.04, 10 = 0.10, 20 = 0.20, 50 = 0.50
                    base_score = num_matches / 100.0

                    # Apply distance quality as a multiplier (0.6 - 1.0 range typically)
                    score = base_score * distance_score

                    # Cap at 0.99
                    score = min(score, 0.99)

                    logger.debug(
                        f"Object '{obj_features.object_name}': "
                        f"{num_matches} matches, "
                        f"avg_dist={avg_distance:.1f}, "
                        f"score={score:.3f}"
                    )

                    if score > best_score:
                        best_score = score
                        best_match = (
                            obj_features.object_id,
                            obj_features.object_name,
                            min(score, 0.99),  # Cap at 0.99
                        )

            except Exception as e:
                logger.warning(f"Match error for object {obj_features.object_id}: {e}")
                continue

        # Only return if confidence meets minimum threshold
        if best_match and best_match[2] >= self.min_confidence:
            logger.info(f"Feature match found: '{best_match[1]}' with confidence {best_match[2]:.2f}")
            return best_match

        if best_match:
            logger.debug(f"Best match '{best_match[1]}' rejected: confidence {best_match[2]:.2f} < {self.min_confidence}")

        return None

    def has_cached_objects(self) -> bool:
        """Check if there are any cached object features."""
        return len(self._object_cache) > 0

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
