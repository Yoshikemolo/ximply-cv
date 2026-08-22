"""
Object catalog API routes.

Provides CRUD operations for catalog objects and their images.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_extensions import uuid7

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_permissions
from app.core.logging import get_logger
from fastapi.responses import StreamingResponse
from app.core.minio_client import delete_file, download_file, upload_file
from app.core.security import TokenData
from app.models.entities import CategoryEntity, ObjectEntity, ObjectImageEntity
from app.models.enums import Permission
from app.models.schemas import (
    MessageResponse,
    ObjectCreate,
    ObjectImageResponse,
    ObjectImageUploadResponse,
    ObjectListResponse,
    ObjectResponse,
    ObjectUpdate,
    PaginatedResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/objects", tags=["Objects"])


@router.get("", response_model=PaginatedResponse[ObjectListResponse])
async def list_objects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ObjectListResponse]:
    """
    List catalog objects with pagination and filters.

    Args:
        page: Page number (1-indexed).
        page_size: Number of items per page.
        search: Search term for name or reference.
        category_id: Filter by category.
        status_filter: Filter by status.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        PaginatedResponse: Paginated list of objects.
    """
    # Convert user_id string to UUID for comparison
    user_uuid = UUID(current_user.sub)

    # Build base query
    query = select(ObjectEntity).where(ObjectEntity.owner_id == user_uuid)

    # Apply filters
    if search:
        search_term = f"%{search}%"
        query = query.where(
            (ObjectEntity.name.ilike(search_term))
            | (ObjectEntity.reference.ilike(search_term))
        )

    if category_id:
        query = query.where(ObjectEntity.category_id == category_id)

    if status_filter:
        query = query.where(ObjectEntity.status == status_filter)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(ObjectEntity.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    objects = result.scalars().all()

    # One lookup for every category in this page, rather than one per row.
    category_ids = {obj.category_id for obj in objects if obj.category_id}
    category_names: dict = {}
    if category_ids:
        category_rows = await db.execute(
            select(CategoryEntity.id, CategoryEntity.name).where(
                CategoryEntity.id.in_(category_ids)
            )
        )
        category_names = {row[0]: row[1] for row in category_rows.all()}

    items = []
    for obj in objects:
        thumbnail_url = None
        if obj.thumbnail_path:
            # Use proxy URL instead of presigned URL to avoid signature issues
            thumbnail_url = f"/api/v1/objects/files/{obj.thumbnail_path}"

        items.append(
            ObjectListResponse(
                id=obj.id,
                name=obj.name,
                description=obj.description,
                reference=obj.reference,
                status=obj.status,
                thumbnail_path=obj.thumbnail_path,
                thumbnail_url=thumbnail_url,
                category_id=obj.category_id,
                category_name=category_names.get(obj.category_id),
                training_samples=obj.training_samples,
                model_confidence=obj.model_confidence,
                created_at=obj.created_at,
            )
        )

    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=ObjectResponse, status_code=status.HTTP_201_CREATED)
async def create_object(
    data: ObjectCreate,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> ObjectResponse:
    """
    Create a new catalog object.

    Args:
        data: Object creation data.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectResponse: Created object.
    """
    obj = ObjectEntity(
        id=uuid7(),
        name=data.name,
        description=data.description,
        reference=data.reference,
        category_id=data.category_id,
        owner_id=UUID(current_user.sub),
        status="draft",
        weight=data.weight,
        weight_unit=data.weight_unit,
        price=data.price,
        currency=data.currency,
        color=data.color,
        materials=data.materials,
        extra_data=data.extra_data,
    )

    if data.dimensions:
        obj.width = data.dimensions.width
        obj.height = data.dimensions.height
        obj.depth = data.dimensions.depth
        obj.dimension_unit = data.dimensions.unit

    db.add(obj)
    await db.commit()
    await db.refresh(obj, ["images"])

    logger.info(f"Object created: {obj.id} by user {current_user.sub}")

    return ObjectResponse.model_validate(obj)


@router.get("/{object_id}", response_model=ObjectResponse)
async def get_object(
    object_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> ObjectResponse:
    """
    Get a single catalog object by ID.

    Args:
        object_id: Object UUID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectResponse: Object details.

    Raises:
        HTTPException: If object not found.
    """
    result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(
            ObjectEntity.id == object_id,
            ObjectEntity.owner_id == UUID(current_user.sub),
        )
    )
    obj = result.scalar_one_or_none()

    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    return ObjectResponse.model_validate(obj)


class RenameRequest(BaseModel):
    """Payload for renaming a catalog entry."""

    name: str


@router.patch("/{object_id}/name", response_model=ObjectResponse)
async def rename_object(
    object_id: UUID,
    data: RenameRequest,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> ObjectResponse:
    """
    Rename a catalog object or a person.

    The name is the identity of an entry across the whole application, so it is
    validated here rather than trusted from the client: an empty name is
    rejected, and so is a name already used by another entry of the same owner.
    The comparison ignores case and surrounding spaces, because two entries that
    differ only in those are indistinguishable to a person reading the list.

    Args:
        object_id: Object or person UUID.
        data: New name.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectResponse: The renamed entry.

    Raises:
        HTTPException: 404 when not found, 422 when empty, 409 when duplicated.
    """
    from app.services.feature_matching_service import get_feature_matching_service
    from app.services.person_recognition_service import get_person_recognition_service

    new_name = (data.name or "").strip()

    if not new_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The name cannot be empty",
        )

    owner_id = UUID(current_user.sub)

    result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(ObjectEntity.id == object_id, ObjectEntity.owner_id == owner_id)
    )
    obj = result.scalar_one_or_none()

    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    duplicate = await db.execute(
        select(ObjectEntity.id).where(
            ObjectEntity.owner_id == owner_id,
            ObjectEntity.id != object_id,
            func.lower(func.trim(ObjectEntity.name)) == new_name.lower(),
        )
    )
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A catalog entry named '{new_name}' already exists",
        )

    obj.name = new_name
    await db.commit()
    await db.refresh(obj, ["images"])

    # Both caches key their labels by name, so they would keep announcing the
    # old one until the next reload if they were not updated here.
    get_feature_matching_service().remove_object(object_id)
    if obj.images:
        get_feature_matching_service().load_object_features(
            object_id=obj.id,
            object_name=obj.name,
            image_paths=[img.file_path for img in obj.images],
        )
    get_person_recognition_service().rename_person(object_id, new_name)

    logger.info(f"Renamed catalog entry {object_id} to '{new_name}'")

    return ObjectResponse.model_validate(obj)


@router.put("/{object_id}", response_model=ObjectResponse)
async def update_object(
    object_id: UUID,
    data: ObjectUpdate,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> ObjectResponse:
    """
    Update a catalog object.

    When status changes, the feature cache is updated:
    - active -> inactive: features removed from cache
    - inactive -> active: features loaded into cache

    Args:
        object_id: Object UUID.
        data: Update data.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectResponse: Updated object.

    Raises:
        HTTPException: If object not found.
    """
    from app.services.feature_matching_service import get_feature_matching_service

    result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(
            ObjectEntity.id == object_id,
            ObjectEntity.owner_id == UUID(current_user.sub),
        )
    )
    obj = result.scalar_one_or_none()

    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    # Track status change for feature cache update
    old_status = obj.status
    update_data = data.model_dump(exclude_unset=True)
    new_status = update_data.get("status", old_status)

    # Handle dimensions separately
    if "dimensions" in update_data and update_data["dimensions"]:
        dims = update_data.pop("dimensions")
        obj.width = dims.get("width", obj.width)
        obj.height = dims.get("height", obj.height)
        obj.depth = dims.get("depth", obj.depth)
        obj.dimension_unit = dims.get("unit", obj.dimension_unit)

    for field, value in update_data.items():
        if hasattr(obj, field):
            setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)

    # Update feature cache if status changed
    if old_status != new_status:
        feature_service = get_feature_matching_service()
        if new_status == "active" and obj.images and obj.training_samples > 0:
            # Object activated - load features into cache
            image_paths = [img.file_path for img in obj.images]
            load_result = feature_service.load_object_features(
                object_id=obj.id,
                object_name=obj.name,
                image_paths=image_paths,
            )
            if load_result.success:
                logger.info(f"Loaded features for activated object '{obj.name}'")
            else:
                logger.warning(f"Failed to load features for activated object: {load_result.error_message}")
        elif old_status == "active" and new_status != "active":
            # Object deactivated - remove features from cache
            removed = feature_service.remove_object(obj.id)
            if removed:
                logger.info(f"Removed features for deactivated object '{obj.name}'")

    logger.info(f"Object updated: {obj.id} by user {current_user.sub}")

    return ObjectResponse.model_validate(obj)


@router.delete("/all")
async def delete_all_objects(
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_DELETE])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Delete all catalog objects for the current user and clear feature cache.

    This is a destructive operation that cannot be undone.

    Args:
        current_user: Authenticated user.
        db: Database session.

    Returns:
        dict: Number of objects deleted.
    """
    from app.services.feature_matching_service import get_feature_matching_service
    from app.services.person_recognition_service import get_person_recognition_service

    user_uuid = UUID(current_user.sub)

    # Get all objects for this user with their images
    result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(ObjectEntity.owner_id == user_uuid)
    )
    objects = result.scalars().all()

    deleted_count = 0
    for obj in objects:
        # Delete images from MinIO
        for image in obj.images:
            try:
                delete_file(image.file_path)
            except Exception as e:
                logger.warning(f"Failed to delete file {image.file_path}: {e}")

        await db.delete(obj)
        deleted_count += 1

    await db.commit()

    # Clear both caches: object features and the person identity gallery
    feature_service = get_feature_matching_service()
    feature_service.clear_cache()
    get_person_recognition_service().clear_gallery()

    logger.info(f"Deleted all objects ({deleted_count}) for user {current_user.sub}")

    return {"deleted": deleted_count, "message": f"Deleted {deleted_count} objects"}


@router.delete("/{object_id}", response_model=MessageResponse)
async def delete_object(
    object_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_DELETE])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Delete a catalog object and its images.

    Also removes the object from the feature matching cache.

    Args:
        object_id: Object UUID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        MessageResponse: Deletion confirmation.

    Raises:
        HTTPException: If object not found.
    """
    from app.services.feature_matching_service import get_feature_matching_service

    result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(
            ObjectEntity.id == object_id,
            ObjectEntity.owner_id == UUID(current_user.sub),
        )
    )
    obj = result.scalar_one_or_none()

    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    # Delete images from MinIO
    for image in obj.images:
        delete_file(image.file_path)

    await db.delete(obj)
    await db.commit()

    # Remove from feature cache
    feature_service = get_feature_matching_service()
    feature_service.remove_object(object_id)

    # A deleted person must also leave the identity gallery, otherwise the next
    # frame would still recognise them under a name that no longer exists.
    from app.services.person_recognition_service import get_person_recognition_service

    get_person_recognition_service().remove_person(object_id)

    logger.info(f"Object deleted: {object_id} by user {current_user.sub}")

    return MessageResponse(message="Object deleted successfully")


# ==============================================================================
# Merge Objects
# ==============================================================================


class MergeObjectsRequest(BaseModel):
    """Request to merge multiple objects into one."""

    object_ids: List[UUID]  # First ID is the target (master), rest are sources


class MergeObjectsResponse(BaseModel):
    """Response from merge operation."""

    target_id: UUID
    target_name: str
    merged_count: int
    total_images: int
    message: str


@router.post("/merge", response_model=MergeObjectsResponse)
async def merge_objects(
    request: MergeObjectsRequest,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> MergeObjectsResponse:
    """
    Merge multiple objects into one.

    The first object_id in the list becomes the target (master).
    All images from source objects are moved to the target.
    Source objects are deleted after merge.
    Feature cache is refreshed for the merged object.

    Args:
        request: List of object IDs to merge (first is target).
        current_user: Authenticated user.
        db: Database session.

    Returns:
        MergeObjectsResponse: Result of merge operation.

    Raises:
        HTTPException: If less than 2 objects or objects not found.
    """
    from app.services.feature_matching_service import get_feature_matching_service

    if len(request.object_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 2 objects required for merge",
        )

    user_uuid = UUID(current_user.sub)
    target_id = request.object_ids[0]
    source_ids = request.object_ids[1:]

    # Get target object with images
    target_result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(
            ObjectEntity.id == target_id,
            ObjectEntity.owner_id == user_uuid,
        )
    )
    target = target_result.scalar_one_or_none()

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target object {target_id} not found",
        )

    # Get source objects with images
    source_result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.images))
        .where(
            ObjectEntity.id.in_(source_ids),
            ObjectEntity.owner_id == user_uuid,
        )
    )
    sources = source_result.scalars().all()

    if len(sources) != len(source_ids):
        found_ids = {str(s.id) for s in sources}
        missing = [str(sid) for sid in source_ids if str(sid) not in found_ids]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source objects not found: {missing}",
        )

    # Move images from sources to target
    images_moved = 0
    feature_service = get_feature_matching_service()

    for source in sources:
        for image in source.images:
            # Update image's object_id to target
            image.object_id = target.id
            # Ensure not primary (target keeps its primary)
            image.is_primary = False
            images_moved += 1

        # Update target's training samples count
        target.training_samples += source.training_samples

        # Remove source from feature cache
        feature_service.remove_object(source.id)

        # Delete source object (images are now under target)
        await db.delete(source)

    await db.commit()

    # Refresh target object
    await db.refresh(target, ["images"])

    # Reload features for merged object
    if target.images:
        image_paths = [img.file_path for img in target.images]
        load_result = feature_service.load_object_features(
            object_id=target.id,
            object_name=target.name,
            image_paths=image_paths,
        )
        if load_result.success:
            logger.info(
                f"Merged {len(sources)} objects into '{target.name}': "
                f"{load_result.feature_count} features from {len(target.images)} images"
            )
        else:
            logger.warning(f"Feature refresh failed after merge: {load_result.error_message}")

    logger.info(
        f"Objects merged: {len(sources)} sources into target {target.id} by user {current_user.sub}"
    )

    return MergeObjectsResponse(
        target_id=target.id,
        target_name=target.name,
        merged_count=len(sources),
        total_images=len(target.images),
        message=f"Merged {len(sources)} objects into '{target.name}'",
    )


# ==============================================================================
# Object Images
# ==============================================================================


@router.post("/{object_id}/images", response_model=ObjectImageUploadResponse)
async def upload_object_image(
    object_id: UUID,
    file: UploadFile = File(...),
    is_primary: bool = Form(False),
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> ObjectImageUploadResponse:
    """
    Upload an image for an object.

    Args:
        object_id: Object UUID.
        file: Image file to upload.
        is_primary: Set as primary image.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        ObjectImageUploadResponse: Upload result with URL.

    Raises:
        HTTPException: If object not found or file invalid.
    """
    # Verify object exists and belongs to user
    result = await db.execute(
        select(ObjectEntity).where(
            ObjectEntity.id == object_id,
            ObjectEntity.owner_id == UUID(current_user.sub),
        )
    )
    obj = result.scalar_one_or_none()

    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {allowed_types}",
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Generate storage path
    image_id = uuid7()
    extension = file.filename.split(".")[-1] if file.filename else "jpg"
    file_path = f"objects/{object_id}/images/{image_id}.{extension}"

    # Upload to MinIO
    from io import BytesIO

    if not upload_file(BytesIO(content), file_path, file.content_type or "image/jpeg"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload image",
        )

    # If setting as primary, unset other primary images
    if is_primary:
        await db.execute(
            ObjectImageEntity.__table__.update()
            .where(ObjectImageEntity.object_id == object_id)
            .values(is_primary=False)
        )

    # Create database record
    image = ObjectImageEntity(
        id=image_id,
        object_id=object_id,
        file_path=file_path,
        file_name=file.filename or f"{image_id}.{extension}",
        file_size=file_size,
        mime_type=file.content_type or "image/jpeg",
        is_primary=is_primary,
    )

    db.add(image)

    # Update object training samples count
    obj.training_samples += 1
    if is_primary:
        obj.thumbnail_path = file_path

    await db.commit()

    # Use proxy URL instead of presigned URL
    url = f"/api/v1/objects/files/{file_path}"

    logger.info(f"Image uploaded for object {object_id}: {image_id}")

    return ObjectImageUploadResponse(
        id=image_id,
        file_name=image.file_name,
        file_size=file_size,
        url=url,
    )


@router.get("/{object_id}/images", response_model=list[ObjectImageResponse])
async def list_object_images(
    object_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_READ])),
    db: AsyncSession = Depends(get_db),
) -> list[ObjectImageResponse]:
    """
    List all images for an object.

    Args:
        object_id: Object UUID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        list: List of object images.
    """
    # Verify object exists and belongs to user
    result = await db.execute(
        select(ObjectEntity).where(
            ObjectEntity.id == object_id,
            ObjectEntity.owner_id == UUID(current_user.sub),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    result = await db.execute(
        select(ObjectImageEntity)
        .where(ObjectImageEntity.object_id == object_id)
        .order_by(ObjectImageEntity.is_primary.desc(), ObjectImageEntity.created_at.desc())
    )
    images = result.scalars().all()

    return [ObjectImageResponse.model_validate(img) for img in images]


@router.delete("/{object_id}/images/{image_id}", response_model=MessageResponse)
async def delete_object_image(
    object_id: UUID,
    image_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.OBJECTS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Delete an object image.

    Args:
        object_id: Object UUID.
        image_id: Image UUID.
        current_user: Authenticated user.
        db: Database session.

    Returns:
        MessageResponse: Deletion confirmation.
    """
    # Verify object exists and belongs to user
    obj_result = await db.execute(
        select(ObjectEntity).where(
            ObjectEntity.id == object_id,
            ObjectEntity.owner_id == UUID(current_user.sub),
        )
    )
    obj = obj_result.scalar_one_or_none()

    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        )

    result = await db.execute(
        select(ObjectImageEntity).where(
            ObjectImageEntity.id == image_id,
            ObjectImageEntity.object_id == object_id,
        )
    )
    image = result.scalar_one_or_none()

    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    # Delete from MinIO
    delete_file(image.file_path)

    # Update object
    obj.training_samples = max(0, obj.training_samples - 1)
    if obj.thumbnail_path == image.file_path:
        obj.thumbnail_path = None

    await db.delete(image)
    await db.commit()

    logger.info(f"Image deleted: {image_id} from object {object_id}")

    return MessageResponse(message="Image deleted successfully")


# ==============================================================================
# Image Proxy (serves images from MinIO)
# ==============================================================================


@router.get("/files/{file_path:path}")
async def get_file(
    file_path: str,
) -> StreamingResponse:
    """
    Proxy endpoint to serve files from MinIO storage.

    This avoids CORS and presigned URL issues by serving files through the backend.
    No authentication required - URLs contain UUIDs which are not guessable.

    Args:
        file_path: Path to the file in MinIO (e.g., objects/{id}/images/{id}.jpg).

    Returns:
        StreamingResponse: The file content.

    Raises:
        HTTPException: If file not found.
    """
    from io import BytesIO

    content = download_file(file_path)

    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    # Determine content type from file extension
    extension = file_path.split(".")[-1].lower()
    content_types = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }
    content_type = content_types.get(extension, "application/octet-stream")

    return StreamingResponse(
        BytesIO(content),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
        },
    )
