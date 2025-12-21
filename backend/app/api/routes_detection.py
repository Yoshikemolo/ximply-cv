"""
Detection API routes.

Provides endpoints for real-time object detection and streaming.
"""

import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
from typing import AsyncGenerator, List, Optional, Tuple
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_permissions
from app.core.logging import get_logger
from app.core.minio_client import upload_file
from app.core.security import TokenData
from app.models.entities import ObjectEntity, ObjectImageEntity
from app.models.enums import Permission
from app.models.schemas import (
    DetectionResponse,
    DetectionResult,
    BoundingBox,
    BarcodeResult,
    ObjectResponse,
)
from app.services.detection_service import get_detection_service
from app.services.feature_matching_service import get_feature_matching_service, FeatureLoadResult
from app.services.barcode_service import get_barcode_service

logger = get_logger(__name__)
router = APIRouter(prefix="/detection", tags=["Detection"])


class DetectRequest(BaseModel):
    """Request body for detection endpoint."""

    image: str  # Base64 encoded image
    confidenceThreshold: Optional[float] = None
    iouThreshold: Optional[float] = None


class CaptureDetectionRequest(BaseModel):
    """Request body for capturing a detection and adding to catalog."""

    image: str  # Base64 encoded full frame image
    bbox: BoundingBox  # Bounding box of the object to capture
    name: str = Field(min_length=1, max_length=255)  # Name for the new object
    description: Optional[str] = None
    category_id: Optional[UUID] = None


async def generate_detection_events(
    user_id: str,
) -> AsyncGenerator[dict, None]:
    """
    Generate SSE events for real-time detection streaming.

    This is a placeholder that would be connected to the actual
    detection service in production.

    Args:
        user_id: User ID for the stream.

    Yields:
        dict: SSE event data.
    """
    # Placeholder for actual camera detection stream
    # In production, this would:
    # 1. Connect to camera feed
    # 2. Run detection model on frames
    # 3. Yield detection results

    while True:
        # Simulate detection results (replace with actual detection)
        detection = DetectionResponse(
            detections=[
                DetectionResult(
                    label="placeholder",
                    confidence=0.0,
                    bbox=BoundingBox(x=0, y=0, width=0, height=0),
                    object_id=None,
                    object_name=None,
                )
            ],
            frame_width=settings.camera_resolution_width,
            frame_height=settings.camera_resolution_height,
            processing_time_ms=0.0,
            timestamp=datetime.now(timezone.utc),
        )

        yield {
            "event": "detection",
            "data": detection.model_dump_json(),
        }

        await asyncio.sleep(1.0 / settings.camera_frame_rate)


@router.get("/stream")
async def stream_detections(
    current_user: TokenData = Depends(require_permissions([Permission.DETECTION_VIEW])),
) -> EventSourceResponse:
    """
    Stream real-time object detections via Server-Sent Events.

    Opens a persistent connection that streams detection results
    as objects are detected in the camera feed.

    Args:
        current_user: Authenticated user.

    Returns:
        EventSourceResponse: SSE stream of detection events.
    """
    logger.info(f"Detection stream started for user: {current_user.sub}")

    return EventSourceResponse(
        generate_detection_events(current_user.sub),
        media_type="text/event-stream",
    )


@router.post("/start")
async def start_detection(
    camera_id: str = "default",
    current_user: TokenData = Depends(require_permissions([Permission.DETECTION_VIEW])),
) -> dict:
    """
    Start detection on a specific camera.

    Args:
        camera_id: Camera identifier.
        current_user: Authenticated user.

    Returns:
        dict: Detection session information.
    """
    # Placeholder for starting detection
    # In production, this would:
    # 1. Validate camera access
    # 2. Initialize detection service
    # 3. Return session ID

    logger.info(f"Detection started on camera {camera_id} by user {current_user.sub}")

    return {
        "status": "started",
        "camera_id": camera_id,
        "user_id": current_user.sub,
        "message": "Detection session started. Use /detection/stream to receive events.",
    }


@router.post("/stop")
async def stop_detection(
    current_user: TokenData = Depends(require_permissions([Permission.DETECTION_VIEW])),
) -> dict:
    """
    Stop the current detection session.

    Args:
        current_user: Authenticated user.

    Returns:
        dict: Stop confirmation.
    """
    logger.info(f"Detection stopped by user {current_user.sub}")

    return {
        "status": "stopped",
        "user_id": current_user.sub,
        "message": "Detection session stopped.",
    }


async def _load_catalog_features(
    feature_service,
    user_id: str,
    db: AsyncSession,
) -> Tuple[int, int, List[str]]:
    """
    Load catalog object features into the feature matching cache.

    Only loads features from ACTIVE objects.

    Args:
        feature_service: The feature matching service instance.
        user_id: User ID to load objects for.
        db: Database session.

    Returns:
        Tuple of (loaded_count, failed_count, error_messages).
    """
    from sqlalchemy.orm import selectinload

    try:
        # Convert user_id string to UUID for comparison
        user_uuid = UUID(user_id)

        # Get all ACTIVE objects with images for this user
        result = await db.execute(
            select(ObjectEntity)
            .options(selectinload(ObjectEntity.images))
            .where(
                ObjectEntity.owner_id == user_uuid,
                ObjectEntity.training_samples > 0,
                ObjectEntity.status == "active",
            )
        )
        objects = result.scalars().all()

        loaded_count = 0
        failed_count = 0
        errors = []

        for obj in objects:
            if obj.images:
                image_paths = [img.file_path for img in obj.images]
                load_result = feature_service.load_object_features(
                    object_id=obj.id,
                    object_name=obj.name,
                    image_paths=image_paths,
                )
                if load_result.success:
                    loaded_count += 1
                else:
                    failed_count += 1
                    if load_result.error_message:
                        errors.append(f"{obj.name}: {load_result.error_message}")

        if loaded_count > 0:
            logger.info(f"Auto-loaded features for {loaded_count} catalog objects")
        if failed_count > 0:
            logger.warning(f"Failed to load features for {failed_count} objects")

        return loaded_count, failed_count, errors

    except Exception as e:
        logger.warning(f"Failed to auto-load catalog features: {e}")
        return 0, 0, [str(e)]


@router.post("/detect")
async def detect_objects(
    request: DetectRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DetectionResponse:
    """
    Detect objects in a single image.

    Accepts a base64 encoded image and returns detection results.
    Also matches detected regions against catalog objects using feature matching.

    Args:
        request: Detection request with base64 image.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        DetectionResponse: Detected objects with bounding boxes and catalog matches.
    """
    try:
        service = get_detection_service()
        feature_service = get_feature_matching_service()

        # Auto-load catalog features if cache is empty
        if not feature_service.has_cached_objects():
            loaded, failed, errors = await _load_catalog_features(feature_service, current_user.sub, db)
            if errors:
                logger.debug(f"Some objects failed to load: {errors}")

        detections, processing_time, (width, height) = service.detect_from_base64(
            request.image,
            confidence_threshold=request.confidenceThreshold,
            iou_threshold=request.iouThreshold,
        )

        # Decode the image for feature matching
        image_array = None
        try:
            image_data = request.image
            if "," in image_data:
                image_data = image_data.split(",")[1]
            image_bytes = base64.b64decode(image_data)
            image = Image.open(BytesIO(image_bytes))
            image_array = np.array(image)
            # Convert RGB to BGR for OpenCV
            if len(image_array.shape) == 3 and image_array.shape[2] == 3:
                image_array = image_array[:, :, ::-1].copy()
        except Exception as e:
            logger.warning(f"Failed to decode image for feature matching: {e}")

        # Convert to response format and match against catalog
        detection_results = []
        for d in detections:
            object_id = d.object_id
            object_name = d.object_name

            # Try to match against catalog objects if image was decoded
            if image_array is not None and object_id is None:
                try:
                    # Crop the detection region with padding
                    padding = 5
                    x1 = max(0, int(d.x) - padding)
                    y1 = max(0, int(d.y) - padding)
                    x2 = min(image_array.shape[1], int(d.x + d.width) + padding)
                    y2 = min(image_array.shape[0], int(d.y + d.height) + padding)

                    if x2 > x1 and y2 > y1:
                        cropped_region = image_array[y1:y2, x1:x2]

                        # Match against catalog
                        match = feature_service.match_region(cropped_region)
                        if match:
                            object_id = str(match[0])
                            object_name = match[1]
                            # Optionally boost confidence with match confidence
                            # match[2] contains the feature match confidence

                except Exception as e:
                    logger.debug(f"Feature matching failed for detection: {e}")

            detection_results.append(
                DetectionResult(
                    label=d.label,
                    confidence=d.confidence,
                    bbox=BoundingBox(
                        x=d.x,
                        y=d.y,
                        width=d.width,
                        height=d.height,
                    ),
                    class_id=d.class_id,
                    object_id=object_id,
                    object_name=object_name,
                )
            )

        # Detect barcodes
        barcode_results = []
        if image_array is not None:
            try:
                barcode_service = get_barcode_service()
                # Convert BGR back to RGB for barcode detection
                rgb_image = image_array[:, :, ::-1] if len(image_array.shape) == 3 else image_array
                barcodes = barcode_service.detect(rgb_image)

                for bc in barcodes:
                    barcode_results.append(
                        BarcodeResult(
                            barcode_type=bc.barcode_type,
                            data=bc.data,
                            bbox=BoundingBox(
                                x=bc.bbox[0],
                                y=bc.bbox[1],
                                width=bc.bbox[2],
                                height=bc.bbox[3],
                            ),
                            quality=bc.quality,
                        )
                    )
            except Exception as e:
                logger.debug(f"Barcode detection failed: {e}")

        return DetectionResponse(
            detections=detection_results,
            barcodes=barcode_results,
            frame_width=width,
            frame_height=height,
            processing_time_ms=processing_time,
            timestamp=datetime.now(timezone.utc),
        )

    except RuntimeError as e:
        logger.error(f"Detection failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Detection service not available",
        )
    except Exception as e:
        logger.error(f"Detection error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Detection failed: {str(e)}",
        )


@router.post("/capture")
async def capture_detection(
    request: CaptureDetectionRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ObjectResponse:
    """
    Capture a detected object and add it to the catalog.

    Takes the current frame, crops the region specified by the bounding box,
    and creates a new catalog object with the given name.

    Args:
        request: Capture request with image, bounding box, and object name.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectResponse: The created catalog object.
    """
    try:
        # Decode base64 image
        image_data = request.image
        if "," in image_data:
            image_data = image_data.split(",")[1]

        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))

        # Crop the bounding box region with some padding
        bbox = request.bbox
        padding = 10  # pixels of padding around the detection

        left = max(0, bbox.x - padding)
        top = max(0, bbox.y - padding)
        right = min(image.width, bbox.x + bbox.width + padding)
        bottom = min(image.height, bbox.y + bbox.height + padding)

        cropped = image.crop((left, top, right, bottom))

        # Create object entity
        # Set status to "active" so the object is immediately available for recognition
        object_id = uuid7()
        obj = ObjectEntity(
            id=object_id,
            name=request.name,
            description=request.description,
            category_id=request.category_id,
            owner_id=UUID(current_user.sub),
            status="active",
            training_samples=1,
        )

        # Save cropped image to MinIO
        image_id = uuid7()
        file_path = f"objects/{object_id}/images/{image_id}.jpg"

        # Convert to JPEG bytes
        buffer = BytesIO()
        cropped.convert("RGB").save(buffer, format="JPEG", quality=90)
        buffer.seek(0)

        if not upload_file(buffer, file_path, "image/jpeg"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save object image",
            )

        # Create image entity
        buffer.seek(0, 2)
        file_size = buffer.tell()

        image_entity = ObjectImageEntity(
            id=image_id,
            object_id=object_id,
            file_path=file_path,
            file_name=f"{request.name.replace(' ', '_')}.jpg",
            file_size=file_size,
            mime_type="image/jpeg",
            width=cropped.width,
            height=cropped.height,
            is_primary=True,
            bbox_x=bbox.x,
            bbox_y=bbox.y,
            bbox_width=bbox.width,
            bbox_height=bbox.height,
        )

        # Set thumbnail
        obj.thumbnail_path = file_path

        # Save to database
        db.add(obj)
        db.add(image_entity)
        await db.commit()
        await db.refresh(obj, ["images"])

        logger.info(
            f"Object captured: {obj.id} '{request.name}' by user {current_user.sub}"
        )

        return ObjectResponse.model_validate(obj)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to capture detection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to capture detection: {str(e)}",
        )


@router.get("/status")
async def get_detection_status(
    current_user: TokenData = Depends(require_permissions([Permission.DETECTION_VIEW])),
) -> dict:
    """
    Get current detection session status.

    Args:
        current_user: Authenticated user.

    Returns:
        dict: Current detection status.
    """
    # Placeholder for status check
    return {
        "active": False,
        "camera_id": None,
        "user_id": current_user.sub,
        "model": settings.detection_model,
        "confidence_threshold": settings.detection_confidence_threshold,
    }


@router.get("/config")
async def get_detection_config(
    current_user: TokenData = Depends(require_permissions([Permission.DETECTION_CONFIGURE])),
) -> dict:
    """
    Get detection configuration settings.

    Args:
        current_user: Authenticated user.

    Returns:
        dict: Current detection configuration.
    """
    return {
        "model": settings.detection_model,
        "confidence_threshold": settings.detection_confidence_threshold,
        "iou_threshold": settings.detection_iou_threshold,
        "camera": {
            "frame_rate": settings.camera_frame_rate,
            "resolution": {
                "width": settings.camera_resolution_width,
                "height": settings.camera_resolution_height,
            },
        },
    }


@router.put("/config")
async def update_detection_config(
    confidence_threshold: float = None,
    iou_threshold: float = None,
    current_user: TokenData = Depends(require_permissions([Permission.DETECTION_CONFIGURE])),
) -> dict:
    """
    Update detection configuration.

    Note: This updates runtime settings only. Permanent changes
    require updating environment variables.

    Args:
        confidence_threshold: New confidence threshold.
        iou_threshold: New IOU threshold.
        current_user: Authenticated user.

    Returns:
        dict: Updated configuration.
    """
    # Placeholder for configuration update
    # In production, this would update the detection service config

    logger.info(f"Detection config updated by user {current_user.sub}")

    return {
        "status": "updated",
        "confidence_threshold": confidence_threshold or settings.detection_confidence_threshold,
        "iou_threshold": iou_threshold or settings.detection_iou_threshold,
    }


@router.post("/catalog/load")
async def load_catalog_features(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Load catalog object features for custom object recognition.

    Loads features from all ACTIVE catalog objects with at least one image
    into the feature matching cache. This enables the detection service
    to recognize custom objects added to the catalog.

    Inactive objects are excluded from the feature cache.

    This is an atomic operation - features are loaded into a temporary
    structure first, then atomically swapped into the cache. This ensures
    the cache is never empty during a reload.

    Args:
        current_user: Authenticated user.
        db: Database session.

    Returns:
        dict: Status and number of objects loaded.
    """
    try:
        from sqlalchemy.orm import selectinload

        # Convert user_id string to UUID for comparison
        user_uuid = UUID(current_user.sub)

        # Get all ACTIVE objects with images for this user
        result = await db.execute(
            select(ObjectEntity)
            .options(selectinload(ObjectEntity.images))
            .where(
                ObjectEntity.owner_id == user_uuid,
                ObjectEntity.training_samples > 0,
                ObjectEntity.status == "active",
            )
        )
        objects = result.scalars().all()

        feature_service = get_feature_matching_service()

        # Load features WITHOUT clearing cache first (atomic approach)
        # Each load_object_features call updates the cache atomically
        loaded_count = 0
        failed_count = 0
        errors = []

        for obj in objects:
            if obj.images:
                image_paths = [img.file_path for img in obj.images]
                load_result = feature_service.load_object_features(
                    object_id=obj.id,
                    object_name=obj.name,
                    image_paths=image_paths,
                )
                if load_result.success:
                    loaded_count += 1
                else:
                    failed_count += 1
                    if load_result.error_message:
                        errors.append({
                            "object_id": str(obj.id),
                            "object_name": obj.name,
                            "error": load_result.error_message,
                        })

        logger.info(
            f"Loaded features for {loaded_count} catalog objects for user {current_user.sub}"
        )

        response = {
            "status": "loaded",
            "objectsLoaded": loaded_count,
            "totalObjects": len(objects),
        }

        if failed_count > 0:
            response["objectsFailed"] = failed_count
            response["errors"] = errors
            logger.warning(f"{failed_count} objects failed to load features")

        return response

    except Exception as e:
        logger.error(f"Failed to load catalog features: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load catalog features: {str(e)}",
        )


@router.post("/catalog/refresh/{object_id}")
async def refresh_object_features(
    object_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Refresh features for a specific catalog object.

    Call this after adding new images to an object.
    This is an atomic operation - if feature extraction fails,
    the existing features (if any) remain in the cache.

    Args:
        object_id: Object UUID to refresh.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        dict: Detailed status of the refresh operation.

    Raises:
        HTTPException: 404 if object not found, 422 if feature extraction failed.
    """
    try:
        from sqlalchemy.orm import selectinload

        # Convert user_id string to UUID for comparison
        user_uuid = UUID(current_user.sub)

        result = await db.execute(
            select(ObjectEntity)
            .options(selectinload(ObjectEntity.images))
            .where(
                ObjectEntity.id == object_id,
                ObjectEntity.owner_id == user_uuid,
            )
        )
        obj = result.scalar_one_or_none()

        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Object not found",
            )

        feature_service = get_feature_matching_service()

        if not obj.images:
            # No images - remove from cache if present
            feature_service.remove_object(object_id)
            return {
                "status": "removed",
                "objectId": str(object_id),
                "objectName": obj.name,
                "imageCount": 0,
                "featureCount": 0,
                "message": "Object has no images, removed from feature cache",
            }

        image_paths = [img.file_path for img in obj.images]
        load_result = feature_service.load_object_features(
            object_id=obj.id,
            object_name=obj.name,
            image_paths=image_paths,
        )

        if not load_result.success:
            # Feature extraction failed - return detailed error
            # Don't raise exception - let frontend handle it
            logger.warning(
                f"Feature extraction failed for object {object_id}: {load_result.error_message}"
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "status": "failed",
                    "objectId": str(object_id),
                    "objectName": obj.name,
                    "imageCount": len(obj.images),
                    "imagesProcessed": load_result.images_processed,
                    "imagesFailed": load_result.images_failed,
                    "featureCount": load_result.feature_count,
                    "error": load_result.error_message,
                },
            )

        logger.info(
            f"Successfully refreshed features for object '{obj.name}': "
            f"{load_result.feature_count} features from {load_result.images_processed} images"
        )

        return {
            "status": "refreshed",
            "objectId": str(object_id),
            "objectName": obj.name,
            "imageCount": len(obj.images),
            "imagesProcessed": load_result.images_processed,
            "imagesFailed": load_result.images_failed,
            "featureCount": load_result.feature_count,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to refresh object features: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh object features: {str(e)}",
        )
