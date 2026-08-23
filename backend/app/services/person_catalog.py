"""
Database access for the People side of the catalog.

A person is an ObjectEntity that lives in the system "People" category, so the
whole catalog already applies to people: listing, renaming, thumbnails, images
and deletion. What is specific to people is the set of identity embeddings
stored alongside, which this module reads and writes.
"""

from io import BytesIO
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.logging import get_logger
from app.core.minio_client import upload_file
from app.models.entities import (
    CategoryEntity,
    ObjectEntity,
    ObjectImageEntity,
    PersonEmbeddingEntity,
)
from app.services.person_recognition_service import (
    PersonRecognitionService,
    PersonSighting,
)

logger = get_logger(__name__)


async def get_or_create_people_category(db: AsyncSession, owner_id: UUID) -> CategoryEntity:
    """
    Fetch the People category for a user, creating it when it does not exist.

    Args:
        db: Database session.
        owner_id: Owner of the category.

    Returns:
        CategoryEntity: The People category.
    """
    name = settings.person_category_name

    result = await db.execute(
        select(CategoryEntity).where(
            CategoryEntity.owner_id == owner_id,
            func.lower(CategoryEntity.name) == name.lower(),
        )
    )
    category = result.scalar_one_or_none()
    if category is not None:
        return category

    category = CategoryEntity(
        id=uuid7(),
        name=name,
        description="People recognised by the camera, identified by face and body",
        owner_id=owner_id,
    )
    db.add(category)
    await db.flush()
    logger.info(f"Created the {name} category for user {owner_id}")
    return category


async def is_people_category(db: AsyncSession, category_id: Optional[UUID]) -> bool:
    """
    Whether a category id refers to the People category.

    Args:
        db: Database session.
        category_id: Category to check, may be None.

    Returns:
        bool: True when the category is the People category.
    """
    if category_id is None:
        return False
    result = await db.execute(
        select(CategoryEntity.name).where(CategoryEntity.id == category_id)
    )
    name = result.scalar_one_or_none()
    return name is not None and name.lower() == settings.person_category_name.lower()


async def list_people(db: AsyncSession, owner_id: UUID) -> List[ObjectEntity]:
    """
    Every person in the catalog of a user.

    Args:
        db: Database session.
        owner_id: Owner of the people.

    Returns:
        List[ObjectEntity]: People, with their embeddings eagerly loaded.
    """
    category = await get_or_create_people_category(db, owner_id)
    result = await db.execute(
        select(ObjectEntity)
        .options(selectinload(ObjectEntity.embeddings))
        .where(
            ObjectEntity.owner_id == owner_id,
            ObjectEntity.category_id == category.id,
        )
        .order_by(ObjectEntity.created_at)
    )
    return list(result.scalars().all())


async def load_gallery(
    service: PersonRecognitionService,
    db: AsyncSession,
    owner_id: UUID,
) -> Tuple[int, int]:
    """
    Fill the in memory gallery from the stored embeddings.

    Args:
        service: Recognition service whose gallery is filled.
        db: Database session.
        owner_id: Owner whose people are loaded.

    Returns:
        Tuple of (people loaded, vectors loaded).
    """
    people = await list_people(db, owner_id)

    service.clear_gallery()
    vectors = 0
    for person in people:
        pairs = [(e.kind, e.vector) for e in person.embeddings]
        vectors += service.load_person(person.id, person.name, pairs)

    if people:
        logger.info(f"Loaded {len(people)} people and {vectors} identity vectors")

    return len(people), vectors


async def enrol_person(
    db: AsyncSession,
    owner_id: UUID,
    service: PersonRecognitionService,
    sighting: PersonSighting,
) -> ObjectEntity:
    """
    Create a new person from an unrecognised sighting.

    The name is the next free entry in the "Person N" sequence, computed from
    the names already present so renaming never causes a later collision.

    Args:
        db: Database session.
        owner_id: Owner of the new person.
        service: Recognition service, whose gallery is updated.
        sighting: The sighting that could not be matched.

    Returns:
        ObjectEntity: The newly created person.
    """
    category = await get_or_create_people_category(db, owner_id)

    result = await db.execute(
        select(ObjectEntity.name).where(
            ObjectEntity.owner_id == owner_id,
            ObjectEntity.category_id == category.id,
        )
    )
    taken = [row for row in result.scalars().all()]
    name = service.next_person_name(taken)

    person = ObjectEntity(
        id=uuid7(),
        name=name,
        description="Recognised automatically from the camera",
        status="active",
        category_id=category.id,
        owner_id=owner_id,
        training_samples=0,
    )
    db.add(person)
    await db.flush()

    service.load_person(person.id, person.name, [])
    await store_sighting(db, person, service, sighting)

    logger.info(f"Enrolled new person: {name}")
    return person


async def store_sighting(
    db: AsyncSession,
    person: ObjectEntity,
    service: PersonRecognitionService,
    sighting: PersonSighting,
) -> int:
    """
    Persist the embeddings of a sighting and update the in memory gallery.

    Rows beyond the per person cap are pruned oldest first, so a person's
    fingerprint keeps following how they look now.

    Args:
        db: Database session.
        person: The person the sighting belongs to.
        service: Recognition service, whose gallery is updated.
        sighting: The sighting to remember.

    Returns:
        int: Number of vectors stored.
    """
    stored = 0

    for kind, vector, quality in (
        ("face", sighting.face_vector, sighting.face_quality),
        ("body", sighting.body_vector, sighting.body_quality),
    ):
        if vector is None:
            continue
        values = [float(v) for v in vector.tolist()]
        db.add(
            PersonEmbeddingEntity(
                id=uuid7(),
                person_id=person.id,
                kind=kind,
                vector=values,
                dimensions=len(values),
                quality=float(quality),
            )
        )
        stored += 1

    if stored:
        person.training_samples = (person.training_samples or 0) + 1
        service.add_embeddings(person.id, sighting)
        await _store_portrait(db, person, sighting)
        await db.flush()
        await _prune_embeddings(db, person.id)

    return stored


async def _store_portrait(
    db: AsyncSession,
    person: ObjectEntity,
    sighting: PersonSighting,
) -> None:
    """
    Keep the most recognisable picture of a person as their thumbnail.

    A person is enrolled from whatever frame happened to be on screen, which is
    often a blurred back view. Every later sighting is scored, and the picture is
    replaced whenever a clearer one turns up, so the catalog card settles on a
    portrait with a visible face instead of the first frame ever seen.

    Args:
        db: Database session.
        person: The person the picture belongs to.
        sighting: Sighting that may provide a better picture.
    """
    if sighting.crop is None or sighting.crop.size == 0:
        return

    score = float(sighting.representativeness)
    extra = dict(person.extra_data or {})
    best = float(extra.get("portraitScore", 0.0))

    # The first picture always wins, later ones only when they are clearer.
    if person.thumbnail_path and score <= best:
        return

    try:
        import cv2
        from PIL import Image

        rgb = cv2.cvtColor(sighting.crop, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)

        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=90)
        size = buffer.tell()
        buffer.seek(0)

        image_id = uuid7()
        file_path = f"objects/{person.id}/images/{image_id}.jpg"

        if not upload_file(buffer, file_path, "image/jpeg"):
            logger.warning(f"Could not upload the portrait of {person.name}")
            return

        x, y, width, height = sighting.bbox
        db.add(
            ObjectImageEntity(
                id=image_id,
                object_id=person.id,
                file_path=file_path,
                file_name=f"{person.name.replace(' ', '_')}_{image_id}.jpg",
                file_size=size,
                mime_type="image/jpeg",
                width=image.width,
                height=image.height,
                is_primary=True,
                bbox_x=x,
                bbox_y=y,
                bbox_width=width,
                bbox_height=height,
            )
        )

        person.thumbnail_path = file_path
        extra["portraitScore"] = score
        person.extra_data = extra

        logger.debug(f"Stored a better portrait for {person.name} (score {score:.2f})")
    except Exception as e:
        logger.warning(f"Could not store the portrait of {person.name}: {e}")


async def _prune_embeddings(db: AsyncSession, person_id: UUID) -> None:
    """
    Drop the oldest embeddings of a person once the cap is exceeded.

    Args:
        db: Database session.
        person_id: Person whose embeddings are pruned.
    """
    cap = settings.person_max_embeddings_per_person

    for kind in ("face", "body"):
        result = await db.execute(
            select(PersonEmbeddingEntity)
            .where(
                PersonEmbeddingEntity.person_id == person_id,
                PersonEmbeddingEntity.kind == kind,
            )
            .order_by(PersonEmbeddingEntity.created_at.desc())
        )
        rows = list(result.scalars().all())
        for row in rows[cap:]:
            await db.delete(row)
