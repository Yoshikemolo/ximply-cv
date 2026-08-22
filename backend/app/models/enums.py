"""
Enumeration types used throughout the application.

Defines status codes, permissions, and other categorical values.
"""

from enum import Enum


class Permission(str, Enum):
    """
    System permissions for RBAC.

    Permissions follow the pattern: resource:action
    """

    # Object permissions
    OBJECTS_READ = "objects:read"
    OBJECTS_WRITE = "objects:write"
    OBJECTS_DELETE = "objects:delete"
    OBJECTS_TRAIN = "objects:train"

    # Category permissions
    CATEGORIES_READ = "categories:read"
    CATEGORIES_WRITE = "categories:write"
    CATEGORIES_DELETE = "categories:delete"

    # User permissions
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"
    USERS_DELETE = "users:delete"

    # Role permissions
    ROLES_READ = "roles:read"
    ROLES_WRITE = "roles:write"
    ROLES_DELETE = "roles:delete"

    # Detection permissions
    DETECTION_VIEW = "detection:view"
    DETECTION_CONFIGURE = "detection:configure"

    # Event and integration permissions
    EVENTS_READ = "events:read"
    EVENTS_MANAGE = "events:manage"

    # Admin permissions
    ADMIN_FULL = "admin:full"


class Role(str, Enum):
    """
    Default system roles.
    """

    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class ObjectStatus(str, Enum):
    """
    Status of a catalog object.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRAINING = "training"


class DetectionStatus(str, Enum):
    """
    Status of a detection job.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingStatus(str, Enum):
    """
    Status of a training job.
    """

    QUEUED = "queued"
    PREPARING = "preparing"
    TRAINING = "training"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


class UserStatus(str, Enum):
    """
    Status of a user account.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class ImageFormat(str, Enum):
    """
    Supported image formats.
    """

    JPEG = "jpeg"
    PNG = "png"
    WEBP = "webp"
    BMP = "bmp"


class MaterialType(str, Enum):
    """
    Common material types for objects.
    """

    PLASTIC = "plastic"
    METAL = "metal"
    WOOD = "wood"
    GLASS = "glass"
    CERAMIC = "ceramic"
    FABRIC = "fabric"
    PAPER = "paper"
    RUBBER = "rubber"
    COMPOSITE = "composite"
    OTHER = "other"
