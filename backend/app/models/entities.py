"""
SQLAlchemy database entity models.

Defines the database schema using SQLAlchemy ORM with UUID7 primary keys.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Column,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


# Association tables for many-to-many relationships
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", PGUUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("role_id", PGUUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", PGUUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
    Column(
        "permission_id", PGUUID(as_uuid=True), ForeignKey("permissions.id"), primary_key=True
    ),
)


class UserEntity(Base):
    """
    User account entity.

    Stores user credentials and profile information.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    roles: Mapped[List["RoleEntity"]] = relationship(
        "RoleEntity", secondary=user_roles, back_populates="users"
    )
    objects: Mapped[List["ObjectEntity"]] = relationship("ObjectEntity", back_populates="owner")


class RoleEntity(Base):
    """
    User role entity.

    Defines roles that group permissions together.
    """

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    users: Mapped[List["UserEntity"]] = relationship(
        "UserEntity", secondary=user_roles, back_populates="roles"
    )
    permissions: Mapped[List["PermissionEntity"]] = relationship(
        "PermissionEntity", secondary=role_permissions, back_populates="roles"
    )


class PermissionEntity(Base):
    """
    Permission entity.

    Defines granular permissions for access control.
    """

    __tablename__ = "permissions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    roles: Mapped[List["RoleEntity"]] = relationship(
        "RoleEntity", secondary=role_permissions, back_populates="permissions"
    )


class CategoryEntity(Base):
    """
    Object category entity.

    Groups objects into hierarchical categories.
    """

    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    objects: Mapped[List["ObjectEntity"]] = relationship("ObjectEntity", back_populates="category")
    children: Mapped[List["CategoryEntity"]] = relationship("CategoryEntity")


class ObjectEntity(Base):
    """
    Catalog object entity.

    Stores learned objects with their metadata and training data.
    """

    __tablename__ = "objects"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    # Physical properties
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    weight_unit: Mapped[Optional[str]] = mapped_column(String(10), default="kg")
    width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    height: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dimension_unit: Mapped[Optional[str]] = mapped_column(String(10), default="cm")

    # Commercial properties
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), default="EUR")
    color: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    materials: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)

    # ML properties
    model_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    training_samples: Mapped[int] = mapped_column(Integer, default=0)
    last_trained_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Storage
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    category_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[Optional["CategoryEntity"]] = relationship(
        "CategoryEntity", back_populates="objects"
    )
    owner: Mapped["UserEntity"] = relationship("UserEntity", back_populates="objects")
    images: Mapped[List["ObjectImageEntity"]] = relationship(
        "ObjectImageEntity", back_populates="object", cascade="all, delete-orphan"
    )
    embeddings: Mapped[List["PersonEmbeddingEntity"]] = relationship(
        "PersonEmbeddingEntity", back_populates="person", cascade="all, delete-orphan"
    )


class ObjectImageEntity(Base):
    """
    Object training image entity.

    Stores images used for training object detection.
    """

    __tablename__ = "object_images"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    object_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("objects.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    # Bounding box for object in image (optional, for training)
    bbox_x: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox_y: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bbox_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    object: Mapped["ObjectEntity"] = relationship("ObjectEntity", back_populates="images")


class PersonEmbeddingEntity(Base):
    """
    Identity embedding for a person in the catalog.

    A person is an ObjectEntity inside the system "People" category. Each row
    here is one appearance sample of that person, stored as a normalised
    embedding vector.

    Two kinds coexist:
    - "face": produced by the face model. Survives a change of clothes, degrades
      behind a mask.
    - "body": produced by the body model over the full person crop. Survives a
      cap, glasses and a mask, but not a change of clothes.

    Keeping several samples per person and per kind is what makes recognition
    hold up across poses, lighting and partial occlusion.
    """

    __tablename__ = "person_embeddings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("objects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    vector: Mapped[List[float]] = mapped_column(ARRAY(Float), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    quality: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    person: Mapped["ObjectEntity"] = relationship("ObjectEntity", back_populates="embeddings")


class EventEntity(Base):
    """
    Something the camera observed, recorded as an OpenTelemetry log record.

    The shape is not invented here. It follows the OpenTelemetry logs data
    model, so an event can be exported to any collector, backend or tracing tool
    that speaks OTLP without a translation layer, and correlated with traces
    from the rest of a system by trace and span id.

    Top level fields map one to one onto the specification: EventName,
    Timestamp, ObservedTimestamp, TraceId, SpanId, TraceFlags, SeverityNumber,
    SeverityText, Body, Attributes, Resource and InstrumentationScope.
    Severity numbers follow the specified bands, where 9 to 12 is informational.

    The domain columns below the standard ones are a deliberate duplication.
    Attributes hold the same values in the standard form, and these exist only
    so the database can index and filter on them, which a JSON blob does poorly.
    Attributes remain the source of truth for anything delivered.

    Events are emitted on a transition, never per frame. Detection runs several
    times a second, so a per frame record would produce tens of thousands of
    identical entries an hour and make any subscriber useless.
    """

    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    # OpenTelemetry log record fields
    event_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Nanoseconds since the Unix epoch, as the specification requires. Stored
    # separately from occurred_at because a timestamp column cannot hold that
    # precision, and losing it would make correlation with traces imprecise.
    timestamp_nanos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_timestamp_nanos: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    span_id: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    trace_flags: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity_number: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    severity_text: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    resource: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    scope_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Projections of the attributes above, for indexing and filtering only.
    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    subject_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("objects.id", ondelete="SET NULL"), nullable=True
    )
    subject_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    camera_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    capture_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class WebhookSubscriptionEntity(Base):
    """
    A client that wants events delivered to it.

    The secret is used to sign every delivery so the receiver can verify the
    request came from this instance and was not altered in transit. It is stored
    because it has to be used on every send; see the security record for what
    that implies.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    secret: Mapped[str] = mapped_column(String(128), nullable=False)

    # Event types this client wants. Empty means every type.
    event_types: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    # Delivery health, so a subscriber that has been failing is visible without
    # reading logs.
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IntegrationTokenEntity(Base):
    """
    A credential issued to one external client.

    Agents and scripts need to reach the API without a password and without a
    session that expires every half hour. A token per client is what makes that
    safe: it can be scoped narrowly, revoked on its own, and its last use is
    visible, none of which is true of a shared password.

    Only the hash is stored. A token that can be read back out of the database
    is a token that leaks through every screen and backup that touches it, so
    the value is shown once at creation and never again. The prefix is kept in
    the clear purely so a person can tell two tokens apart in a list.
    """

    __tablename__ = "integration_tokens"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)

    # Permission codes this token may exercise. Never more than its owner holds,
    # which is checked at issue time and again on every request.
    scopes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(String), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DetectionLogEntity(Base):
    """
    Detection event log entity.

    Stores history of object detections for analytics.
    """

    __tablename__ = "detection_logs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    object_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("objects.id"), nullable=True
    )
    detected_label: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_y: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_width: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_height: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_width: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_height: Mapped[int] = mapped_column(Integer, nullable=False)
    camera_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
