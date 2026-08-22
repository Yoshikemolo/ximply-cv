"""
Pydantic schemas for API request and response validation.

Uses camelCase conversion for JSON serialization.
"""

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def to_camel_case(string: str) -> str:
    """Convert snake_case to camelCase."""
    components = string.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


class CamelCaseModel(BaseModel):
    """Base model with camelCase JSON serialization."""

    model_config = ConfigDict(
        alias_generator=to_camel_case,
        populate_by_name=True,
        from_attributes=True,
    )


T = TypeVar("T")


class PaginatedResponse(CamelCaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class MessageResponse(CamelCaseModel):
    """Simple message response."""

    message: str
    success: bool = True


class ErrorResponse(CamelCaseModel):
    """Error response model."""

    detail: str
    code: Optional[str] = None
    errors: Optional[Dict[str, Any]] = None


# ==============================================================================
# Authentication Schemas
# ==============================================================================


class LoginRequest(CamelCaseModel):
    """Login request payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=100)


class LoginResponse(CamelCaseModel):
    """Login response with tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserResponse"


class RefreshTokenRequest(CamelCaseModel):
    """Refresh token request payload."""

    refresh_token: str


class RefreshTokenResponse(CamelCaseModel):
    """Refresh token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(CamelCaseModel):
    """User registration request."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=100)
    full_name: str = Field(min_length=2, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Validate password strength."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


# ==============================================================================
# User Schemas
# ==============================================================================


class UserBase(CamelCaseModel):
    """Base user schema."""

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(min_length=8, max_length=100)
    role_ids: Optional[List[UUID]] = None


class UserUpdate(CamelCaseModel):
    """User update schema."""

    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    status: Optional[str] = None
    role_ids: Optional[List[UUID]] = None


class UserResponse(UserBase):
    """User response schema."""

    id: UUID
    status: str
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    roles: List["RoleResponse"] = []


class UserListResponse(CamelCaseModel):
    """Simplified user response for lists."""

    id: UUID
    email: str
    full_name: str
    status: str
    created_at: datetime


# ==============================================================================
# Role Schemas
# ==============================================================================


class RoleBase(CamelCaseModel):
    """Base role schema."""

    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None


class RoleCreate(RoleBase):
    """Role creation schema."""

    permission_ids: Optional[List[UUID]] = None


class RoleUpdate(CamelCaseModel):
    """Role update schema."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    description: Optional[str] = None
    permission_ids: Optional[List[UUID]] = None


class RoleResponse(RoleBase):
    """Role response schema."""

    id: UUID
    is_system: bool
    created_at: datetime
    permissions: List["PermissionResponse"] = []


# ==============================================================================
# Permission Schemas
# ==============================================================================


class PermissionResponse(CamelCaseModel):
    """Permission response schema."""

    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    category: str


# ==============================================================================
# Category Schemas
# ==============================================================================


class CategoryBase(CamelCaseModel):
    """Base category schema."""

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    parent_id: Optional[UUID] = None


class CategoryCreate(CategoryBase):
    """Category creation schema."""

    pass


class CategoryUpdate(CamelCaseModel):
    """Category update schema."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    parent_id: Optional[UUID] = None


class CategoryResponse(CategoryBase):
    """Category response schema."""

    id: UUID
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
    children: List["CategoryResponse"] = []


# ==============================================================================
# Object Schemas
# ==============================================================================


class ObjectDimensions(CamelCaseModel):
    """Object dimensions."""

    width: Optional[float] = None
    height: Optional[float] = None
    depth: Optional[float] = None
    unit: str = "cm"


class ObjectBase(CamelCaseModel):
    """Base object schema."""

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    reference: Optional[str] = Field(default=None, max_length=100)
    category_id: Optional[UUID] = None


class ObjectCreate(ObjectBase):
    """Object creation schema."""

    weight: Optional[float] = None
    weight_unit: str = "kg"
    dimensions: Optional[ObjectDimensions] = None
    price: Optional[float] = None
    currency: str = "EUR"
    color: Optional[str] = None
    materials: Optional[List[str]] = None
    extra_data: Optional[Dict[str, Any]] = None


class ObjectUpdate(CamelCaseModel):
    """Object update schema."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    reference: Optional[str] = Field(default=None, max_length=100)
    status: Optional[str] = None
    category_id: Optional[UUID] = None
    weight: Optional[float] = None
    weight_unit: Optional[str] = None
    dimensions: Optional[ObjectDimensions] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    color: Optional[str] = None
    materials: Optional[List[str]] = None
    extra_data: Optional[Dict[str, Any]] = None


class ObjectResponse(ObjectBase):
    """Object response schema."""

    id: UUID
    status: str
    owner_id: UUID
    weight: Optional[float] = None
    weight_unit: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    depth: Optional[float] = None
    dimension_unit: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    color: Optional[str] = None
    materials: Optional[List[str]] = None
    model_confidence: Optional[float] = None
    training_samples: int = 0
    thumbnail_path: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    last_trained_at: Optional[datetime] = None
    images: List["ObjectImageResponse"] = []


class ObjectListResponse(CamelCaseModel):
    """Simplified object response for lists."""

    id: UUID
    name: str
    description: Optional[str] = None
    reference: Optional[str] = None
    status: str
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    category_id: Optional[UUID] = None
    # The category name travels with the entry so the client can tell a person
    # from an object without a second request per row.
    category_name: Optional[str] = None
    training_samples: int = 0
    model_confidence: Optional[float] = None
    created_at: datetime


# ==============================================================================
# Object Image Schemas
# ==============================================================================


class ObjectImageResponse(CamelCaseModel):
    """Object image response schema."""

    id: UUID
    object_id: UUID
    file_path: str
    file_name: str
    file_size: int
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    is_primary: bool
    created_at: datetime


class ObjectImageUploadResponse(CamelCaseModel):
    """Response after uploading an object image."""

    id: UUID
    file_name: str
    file_size: int
    url: str


# ==============================================================================
# Detection Schemas
# ==============================================================================


class BoundingBox(CamelCaseModel):
    """Bounding box coordinates."""

    x: int
    y: int
    width: int
    height: int


class DetectionResult(CamelCaseModel):
    """Single detection result."""

    label: str
    # How sure the detector is that something is there.
    confidence: float
    bbox: BoundingBox
    class_id: Optional[int] = None
    object_id: Optional[str] = None
    object_name: Optional[str] = None
    # How sure the matcher is that the something is this particular entry.
    # These are different questions: a bus can be detected at 92% and still be
    # a terrible match for a phone in the catalog. Reporting only the first
    # number would announce a wrong identity with the detector's confidence.
    match_confidence: Optional[float] = None


class BarcodeResult(CamelCaseModel):
    """Single barcode detection result."""

    barcode_type: str  # EAN13, EAN8, UPC, QR, Code128, etc.
    data: str  # The decoded barcode value
    bbox: BoundingBox
    quality: float = Field(ge=0, le=1)


class SkeletonKeypoint(CamelCaseModel):
    """One landmark, in pixel coordinates of the frame."""

    name: str
    x: float
    y: float
    # Depth relative to the subject, as the landmark models report it. Kept so
    # the client can shade the mesh by depth rather than drawing it flat.
    z: float = 0.0
    score: float


class SkeletonEdge(CamelCaseModel):
    """One bone, joining two keypoints by index."""

    from_index: int = Field(alias="from")
    to_index: int = Field(alias="to")
    part: str


class SkeletonResult(CamelCaseModel):
    """
    A wireframe over one body or one hand.

    Bodies use the 33 point BlazePose layout, hands the 21 landmark layout and
    faces the 478 point mesh. The edges travel with the skeleton so the client
    can draw it without hardcoding any of those conventions, and are sent once
    per kind per frame because they never change.
    """

    kind: str
    label: Optional[str] = None
    score: float
    bbox: BoundingBox
    keypoints: List[SkeletonKeypoint]
    edges: List[SkeletonEdge]


class DetectionResponse(CamelCaseModel):
    """Detection response with all detected objects and barcodes."""

    detections: List[DetectionResult]
    barcodes: List[BarcodeResult] = []
    skeletons: List[SkeletonResult] = []
    frame_width: int
    frame_height: int
    processing_time_ms: float
    timestamp: datetime


class DetectionStreamEvent(CamelCaseModel):
    """SSE event for detection stream."""

    event_type: str = "detection"
    data: DetectionResponse


# ==============================================================================
# Training Schemas
# ==============================================================================


class TrainingRequest(CamelCaseModel):
    """Request to start training for an object."""

    object_id: UUID
    epochs: int = Field(default=10, ge=1, le=100)
    batch_size: int = Field(default=16, ge=1, le=64)
    learning_rate: float = Field(default=0.001, gt=0, lt=1)


class TrainingStatusResponse(CamelCaseModel):
    """Training job status response."""

    job_id: UUID
    object_id: UUID
    status: str
    progress: float = 0.0
    current_epoch: int = 0
    total_epochs: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


# ==============================================================================
# Health Check Schemas
# ==============================================================================


class HealthCheckResponse(CamelCaseModel):
    """Health check response."""

    status: str
    version: str
    database: str
    minio: str
    timestamp: datetime


# Rebuild models to resolve forward references
UserResponse.model_rebuild()
RoleResponse.model_rebuild()
CategoryResponse.model_rebuild()
ObjectResponse.model_rebuild()
LoginResponse.model_rebuild()
