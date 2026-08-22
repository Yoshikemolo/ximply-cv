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
from app.models.entities import ObjectEntity, ObjectImageEntity, PersonEmbeddingEntity
from app.models.enums import Permission
from app.models.schemas import (
    DetectionResponse,
    DetectionResult,
    BoundingBox,
    BarcodeResult,
    ObjectResponse,
    SkeletonEdge,
    SkeletonKeypoint,
    SkeletonResult,
)
from app.services.detection_service import get_detection_service
from app.services.feature_matching_service import get_feature_matching_service, FeatureLoadResult
from app.services.barcode_service import get_barcode_service
from app.services.person_catalog import (
    enrol_person,
    get_or_create_people_category,
    load_gallery,
    should_enrol,
    store_sighting,
)
from app.services.person_recognition_service import get_person_recognition_service
from app.services.pose_service import get_pose_service
from app.services.segmentation_service import get_segmentation_service
from app.services.description_service import get_description_service

logger = get_logger(__name__)
router = APIRouter(prefix="/detection", tags=["Detection"])


def _calculate_iou(box1: BoundingBox, box2: BoundingBox) -> float:
    """
    Calculate Intersection over Union (IoU) between two bounding boxes.

    Args:
        box1: First bounding box.
        box2: Second bounding box.

    Returns:
        IoU value between 0 and 1.
    """
    # Calculate intersection
    x1 = max(box1.x, box2.x)
    y1 = max(box1.y, box2.y)
    x2 = min(box1.x + box1.width, box2.x + box2.width)
    y2 = min(box1.y + box1.height, box2.y + box2.height)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)

    # Calculate union
    area1 = box1.width * box1.height
    area2 = box2.width * box2.height
    union = area1 + area2 - intersection

    if union <= 0:
        return 0.0

    return intersection / union


def _calculate_overlap_ratio(box1: BoundingBox, box2: BoundingBox) -> float:
    """
    Calculate how much of box2 is covered by box1.

    This helps detect when a smaller box is mostly inside a larger one,
    even if IoU is low due to size difference.

    Args:
        box1: First bounding box.
        box2: Second bounding box.

    Returns:
        Ratio of box2's area that overlaps with box1 (0 to 1).
    """
    # Calculate intersection
    x1 = max(box1.x, box2.x)
    y1 = max(box1.y, box2.y)
    x2 = min(box1.x + box1.width, box2.x + box2.width)
    y2 = min(box1.y + box1.height, box2.y + box2.height)

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area2 = box2.width * box2.height

    if area2 <= 0:
        return 0.0

    return intersection / area2


def _filter_person_detections(
    detections: List[DetectionResult],
) -> List[DetectionResult]:
    """
    Filter out 'person' detections when there are other objects detected.

    This helps when users hold objects with their hands - we want to focus
    on the objects, not the person holding them.

    Args:
        detections: List of detection results.

    Returns:
        Filtered list without person detections (if other objects exist).
    """
    # Check if there are non-person detections
    non_person_detections = [d for d in detections if d.label.lower() != "person"]

    # If there are other objects, filter out persons
    if non_person_detections:
        return non_person_detections

    # If only person detections, keep them
    return detections


def _describes_same_thing(a: DetectionResult, b: DetectionResult) -> bool:
    """
    Whether two overlapping boxes are two views of one thing.

    Only these are duplicates worth suppressing. Anything else is a genuine
    overlap between distinct things and must stay visible, which is why a
    person and the object they are holding both survive NMS.

    Args:
        a: First detection.
        b: Second detection.

    Returns:
        bool: True when one of the two boxes is redundant.
    """
    # Both resolved to the same catalog entry or the same person.
    if a.object_id and b.object_id:
        return a.object_id == b.object_id

    # A recognised entry and a raw box of the same class are the same thing seen
    # twice, the recognised one carrying the better label.
    if a.label.lower() == b.label.lower():
        return True

    # A person box never suppresses an object box, nor the other way round.
    a_is_person = a.label.lower() == "person"
    b_is_person = b.label.lower() == "person"
    if a_is_person != b_is_person:
        return False

    # Different classes that are not people: keep both, the scene has two things.
    return False


def _apply_custom_nms(
    detections: List[DetectionResult],
    iou_threshold: float = 0.3,
    overlap_threshold: float = 0.5,
) -> List[DetectionResult]:
    """
    Apply custom Non-Maximum Suppression that prioritizes trained objects.

    Suppression only ever applies between detections of the same thing. Two
    boxes that describe different things are both kept however much they
    overlap, because the overlap is the real scene rather than a duplicate: a
    person holding a bottle contains the bottle box inside the person box, and
    hiding either one loses information. This is what _describes_same_thing
    decides.

    Among boxes of the same thing:
    1. If one has objectId (trained) and the other doesn't, keep the trained one
    2. If both have same priority, keep the one with higher confidence

    Overlap is detected using either:
    - IoU >= iou_threshold (traditional NMS)
    - overlap_ratio >= overlap_threshold (one box mostly inside another)

    Args:
        detections: List of detection results.
        iou_threshold: IoU threshold for considering detections as overlapping.
        overlap_threshold: Overlap ratio threshold for containment check.

    Returns:
        Filtered list of detections with duplicates removed.
    """
    if len(detections) <= 1:
        return detections

    # Sort by priority: trained objects first (objectId is not None), then by confidence
    # Priority score: trained objects get +1000 to their confidence for sorting
    def sort_key(d: DetectionResult) -> float:
        priority_boost = 1000.0 if d.object_id else 0.0
        return priority_boost + d.confidence

    sorted_detections = sorted(detections, key=sort_key, reverse=True)

    keep = []
    suppressed = set()

    for i, detection in enumerate(sorted_detections):
        if i in suppressed:
            continue

        keep.append(detection)

        # Suppress overlapping detections with lower priority
        for j in range(i + 1, len(sorted_detections)):
            if j in suppressed:
                continue

            other = sorted_detections[j]
            iou = _calculate_iou(detection.bbox, other.bbox)

            # Check if boxes overlap using IoU
            overlaps_by_iou = iou >= iou_threshold

            # Check if the lower-priority box is mostly inside the higher-priority one
            overlap_ratio = _calculate_overlap_ratio(detection.bbox, other.bbox)
            overlaps_by_containment = overlap_ratio >= overlap_threshold

            if (overlaps_by_iou or overlaps_by_containment) and _describes_same_thing(
                detection, other
            ):
                # Suppress the lower priority detection
                suppressed.add(j)
                logger.debug(
                    f"NMS: Suppressing '{other.object_name or other.label}' "
                    f"(conf={other.confidence:.2f}, trained={other.object_id is not None}) "
                    f"in favor of '{detection.object_name or detection.label}' "
                    f"(conf={detection.confidence:.2f}, trained={detection.object_id is not None}), "
                    f"IoU={iou:.2f}, overlap={overlap_ratio:.2f}"
                )

    return keep


class DetectRequest(BaseModel):
    """
    Request body for detection endpoint.

    The two view toggles travel with the request because they change what
    counts as a duplicate. Filtering them on the client after the fact is not
    equivalent: by then NMS has already resolved overlaps against boxes the
    user asked not to see, so a suppressed box could disappear in favour of a
    hidden one and leave a gap on screen.
    """

    image: str  # Base64 encoded image
    confidenceThreshold: Optional[float] = None
    iouThreshold: Optional[float] = None
    hidePersonDetections: bool = False
    showOnlyCustomObjects: bool = False
    # An overlay the client is not drawing is not computed. The landmark models
    # dominate the cost of a frame, so switching one off has to stop the work
    # rather than discard its result.
    includeSkeletons: bool = True
    includeFaceMesh: bool = True
    # "yolo" draws rectangles, "sam" prompts Segment Anything with those same
    # rectangles and draws the outline instead. Segmentation never replaces
    # detection: it has no idea what it is looking at.
    detectionModel: str = "yolo"
    # Calibration for the silhouettes, only meaningful when detectionModel is
    # "sam". Absent means the server side defaults apply.
    segmentationTightness: Optional[float] = None
    segmentationExcludeSiblings: Optional[bool] = None


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

    Only loads features from ACTIVE objects, and never from people. A person
    is a catalog entry like any other, but their portrait must not reach the
    ORB matcher: those descriptors are generic enough that any textured object
    can score against a photo of a face, which is how a bus ends up announced
    as "Person 7". People are identified by their own face and body
    embeddings instead.

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

        # Drop the People category: their identity comes from the recognition
        # service, and feeding their portraits to the object matcher produces
        # confident nonsense.
        people_category = await get_or_create_people_category(db, user_uuid)
        objects = [obj for obj in objects if obj.category_id != people_category.id]

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


async def _identify_people(
    detections: List[DetectionResult],
    frame: np.ndarray,
    user_id: str,
    db: AsyncSession,
) -> None:
    """
    Attach an identity to every person detected in a frame.

    Each person box is turned into a face embedding and a body embedding, then
    matched against the people already known. A sighting that matches nobody
    becomes a new person named "Person N", so an unknown face is remembered from
    the moment it first appears.

    Detections are modified in place: object_id and object_name are filled with
    the identified person.

    Args:
        detections: Detection results for the frame, person boxes included.
        frame: Full BGR frame the detections came from.
        user_id: Owner of the people catalog.
        db: Database session.
    """
    service = get_person_recognition_service()
    if not service.enabled:
        return

    person_detections = [
        d for d in detections if d.label.lower() == "person" and d.object_id is None
    ]
    if not person_detections:
        return

    owner_id = UUID(user_id)

    if not service.has_gallery():
        await load_gallery(service, db, owner_id)

    changed = False

    for detection in person_detections:
        try:
            sighting = service.build_sighting(
                frame,
                (
                    detection.bbox.x,
                    detection.bbox.y,
                    detection.bbox.width,
                    detection.bbox.height,
                ),
            )
            if not sighting.has_any_embedding:
                continue

            match = service.match(sighting)

            if match is not None:
                detection.object_id = str(match.person_id)
                detection.object_name = match.person_name
                detection.match_confidence = float(match.similarity)

                # Remembering a confirmed sighting is what lets the fingerprint
                # follow a person as they put on a cap or take off a mask.
                person = await db.get(ObjectEntity, match.person_id)
                if person is not None:
                    await store_sighting(db, person, service, sighting)
                    changed = True
            elif await should_enrol(sighting):
                person = await enrol_person(db, owner_id, service, sighting)
                detection.object_id = str(person.id)
                detection.object_name = person.name
                # A brand new person is certain by construction: they are
                # whoever this sighting is, nobody else.
                detection.match_confidence = 1.0
                changed = True

        except Exception as e:
            logger.debug(f"Person identification failed for one box: {e}")
            continue

    if changed:
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning(f"Could not persist person identities: {e}")


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

        # Identities that may only ever be attached to a person box.
        people_category = await get_or_create_people_category(db, UUID(current_user.sub))
        people_rows = await db.execute(
            select(ObjectEntity.id).where(ObjectEntity.category_id == people_category.id)
        )
        person_ids = {str(row) for row in people_rows.scalars().all()}

        # Convert to response format and match against catalog
        detection_results = []
        for d in detections:
            object_id = d.object_id
            object_name = d.object_name
            match_confidence = None

            # Try to match against catalog objects if image was decoded
            # Skip feature matching for "person" detections to avoid matching
            # hands/fingers in training images with person detections
            is_person = d.label.lower() == "person"
            if image_array is not None and object_id is None and not is_person:
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
                            # Belt and braces: a person can only ever be the
                            # identity of a person box, whatever the cache holds.
                            match_confidence = float(match[2])
                            if str(object_id) in person_ids:
                                object_id = None
                                object_name = None
                                match_confidence = None
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
                    match_confidence=match_confidence,
                )
            )

        # Identify people before NMS so that a recognised person carries a name
        # into the deduplication step and wins over a bare YOLO box.
        if image_array is not None and not request.hidePersonDetections:
            await _identify_people(detection_results, image_array, current_user.sub, db)

        # Apply the view toggles before NMS, not after. A box the user chose to
        # hide must not take part in resolving overlaps, otherwise it can
        # suppress a visible box and leave nothing in its place.
        candidates = detection_results
        if request.hidePersonDetections:
            candidates = [d for d in candidates if d.label.lower() != "person"]
        if request.showOnlyCustomObjects:
            candidates = [d for d in candidates if d.object_id]

        # Apply custom NMS to remove duplicate/overlapping detections
        # Prioritizes trained objects over YOLO-only detections
        # Uses iou_threshold=0.3 and overlap_threshold=0.5 (defaults)
        filtered_detections = _apply_custom_nms(candidates)

        if len(filtered_detections) < len(candidates):
            logger.debug(
                f"Filtering reduced detections from {len(candidates)} to {len(filtered_detections)}"
            )

        # Trace the outline of each detection when the client asked for it
        if request.detectionModel == "sam" and image_array is not None and filtered_detections:
            try:
                segmentation = get_segmentation_service()
                boxes = [
                    (
                        float(d.bbox.x),
                        float(d.bbox.y),
                        float(d.bbox.x + d.bbox.width),
                        float(d.bbox.y + d.bbox.height),
                    )
                    for d in filtered_detections
                ]
                polygons, segmentation_time = segmentation.segment_boxes(
                    image_array,
                    boxes,
                    tightness=request.segmentationTightness,
                    exclude_siblings=request.segmentationExcludeSiblings,
                )
                processing_time += segmentation_time
                for detection, polygon in zip(filtered_detections, polygons):
                    if polygon:
                        detection.polygon = polygon
            except Exception as e:
                logger.debug(f"Segmentation failed: {e}")

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

        # Skeleton overlay for people and hands
        skeleton_results = []
        wants_overlay = request.includeSkeletons or request.includeFaceMesh
        if image_array is not None and wants_overlay:
            try:
                pose_service = get_pose_service()
                skeletons, pose_time = pose_service.extract(
                    image_array,
                    include_bodies=request.includeSkeletons,
                    include_hands=request.includeSkeletons,
                    include_faces=request.includeFaceMesh,
                )
                if request.hidePersonDetections:
                    # Hiding people hides their wireframe as well; hands stay,
                    # since a hand is what the user is pointing at the camera.
                    skeletons = [s for s in skeletons if s.kind != "body"]
                processing_time += pose_time

                # The edge list of a kind never changes and the face mesh runs to
                # thousands of edges, so it is sent once per kind per frame and
                # the client reuses it for the rest.
                edges_sent = set()
                for skeleton in skeletons:
                    include_edges = skeleton.kind not in edges_sent
                    edges_sent.add(skeleton.kind)
                    payload = skeleton.to_dict(include_edges=include_edges)
                    skeleton_results.append(
                        SkeletonResult(
                            kind=payload["kind"],
                            label=payload["label"],
                            score=payload["score"],
                            bbox=BoundingBox(**payload["bbox"]),
                            keypoints=[
                                SkeletonKeypoint(**point) for point in payload["keypoints"]
                            ],
                            edges=[
                                SkeletonEdge(
                                    from_index=edge["from"],
                                    to_index=edge["to"],
                                    part=edge["part"],
                                )
                                for edge in payload["edges"]
                            ],
                        )
                    )
            except Exception as e:
                logger.debug(f"Skeleton extraction failed: {e}")

        return DetectionResponse(
            detections=filtered_detections,
            barcodes=barcode_results,
            skeletons=skeleton_results,
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

    If an object with the same name already exists, adds the image to that object.
    Otherwise, creates a new catalog object.
    In both cases, automatically updates the feature cache for immediate recognition.

    Args:
        request: Capture request with image, bounding box, and object name.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectResponse: The created or updated catalog object.
    """
    from sqlalchemy.orm import selectinload

    try:
        user_uuid = UUID(current_user.sub)

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

        # Check if object with same name already exists for this user
        existing_result = await db.execute(
            select(ObjectEntity)
            .options(selectinload(ObjectEntity.images))
            .where(
                ObjectEntity.owner_id == user_uuid,
                ObjectEntity.name == request.name,
            )
        )
        existing_obj = existing_result.scalar_one_or_none()

        is_new_object = existing_obj is None

        if is_new_object:
            # Create new object entity
            object_id = uuid7()
            obj = ObjectEntity(
                id=object_id,
                name=request.name,
                description=request.description,
                category_id=request.category_id,
                owner_id=user_uuid,
                status="active",
                training_samples=1,
            )
            db.add(obj)
        else:
            # Use existing object
            obj = existing_obj
            object_id = obj.id
            obj.training_samples += 1
            # Ensure object is active for recognition
            if obj.status != "active":
                obj.status = "active"

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
            file_name=f"{request.name.replace(' ', '_')}_{image_id}.jpg",
            file_size=file_size,
            mime_type="image/jpeg",
            width=cropped.width,
            height=cropped.height,
            is_primary=is_new_object,  # Only set as primary for new objects
            bbox_x=bbox.x,
            bbox_y=bbox.y,
            bbox_width=bbox.width,
            bbox_height=bbox.height,
        )

        db.add(image_entity)

        # Set thumbnail for new objects
        if is_new_object:
            obj.thumbnail_path = file_path

        # Save to database
        await db.commit()
        await db.refresh(obj, ["images"])

        # Load/refresh features into cache for immediate recognition
        feature_service = get_feature_matching_service()
        image_paths = [img.file_path for img in obj.images]

        load_result = feature_service.load_object_features(
            object_id=obj.id,
            object_name=obj.name,
            image_paths=image_paths,
        )

        if load_result.success:
            logger.info(
                f"Object {'created' if is_new_object else 'updated'}: {obj.id} '{request.name}' "
                f"with {load_result.feature_count} features from {load_result.images_processed} images"
            )
        else:
            logger.warning(
                f"Object saved but feature extraction failed: {load_result.error_message}"
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


class DescribeRequest(BaseModel):
    """Request body for the scene description endpoint."""

    image: str
    # The detections the client is already showing. Passing them saves running
    # detection twice and, more importantly, fixes the names the description
    # uses to the ones on screen.
    detections: List[dict] = []


@router.post("/describe")
async def describe_scene(
    request: DescribeRequest,
    current_user: TokenData = Depends(get_current_user),
) -> dict:
    """
    Write a short description of what the camera is looking at.

    The detector has already worked out what is in the frame and who the people
    are, so that list is handed to the model as context. It fixes the names,
    keeps the model from inventing objects, and lets the prose refer to a person
    by the name the rest of the application uses.

    Args:
        request: The frame and the detections already found in it.
        current_user: Authenticated user.

    Returns:
        dict: The description, or the reason there is not one.
    """
    service = get_description_service()

    if not service.available:
        return {
            "description": None,
            "available": False,
            "status": service.describe_status(),
        }

    image_array = None
    try:
        image_data = request.image
        if "," in image_data:
            image_data = image_data.split(",")[1]
        image = Image.open(BytesIO(base64.b64decode(image_data)))
        image_array = np.array(image)
        if len(image_array.shape) == 3 and image_array.shape[2] == 3:
            image_array = image_array[:, :, ::-1].copy()
    except Exception as e:
        logger.warning(f"Could not decode the frame to describe: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The image could not be decoded",
        )

    description, elapsed = service.describe(image_array, request.detections)

    return {
        "description": description,
        "available": service.available,
        "processingTimeMs": elapsed,
        "status": service.describe_status(),
    }


@router.get("/describe/status")
async def description_status(
    current_user: TokenData = Depends(get_current_user),
) -> dict:
    """Report whether the description model is loaded and usable."""
    return get_description_service().describe_status()


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

        # People never enter the object matcher: their portraits would match any
        # textured object, and their identity comes from the recognition service.
        people_category = await get_or_create_people_category(db, user_uuid)
        objects = [obj for obj in objects if obj.category_id != people_category.id]

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
