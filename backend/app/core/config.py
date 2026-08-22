"""
Application configuration management using Pydantic Settings.

Loads configuration from environment variables and .env files.
Supports different configurations for development and production.
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Attributes:
        app_name: Name of the application.
        app_version: Current application version.
        api_version: API version prefix (e.g., 'v1').
        debug: Enable debug mode.
        host: Server host address.
        port: Server port number.
        workers: Number of uvicorn workers.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "XIMPLY Vision"
    app_version: str = "1.0.0"
    api_version: str = "v1"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ximply_vision",
        description="PostgreSQL connection string with asyncpg driver",
    )
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"  # Public URL for browser access
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "ximply-vision"
    minio_secure: bool = False

    # JWT Authentication
    jwt_secret_key: str = Field(
        default="change-this-secret-key-in-production",
        description="Secret key for JWT token signing",
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # CORS
    cors_origins: List[str] = ["http://localhost:4200", "http://localhost:4202"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v

    # Storage paths
    storage_base_path: Path = Path("./storage")
    upload_path: Path = Path("./storage/uploads")
    models_path: Path = Path("./models/weights")

    # ML Models
    # YOLO11s offers better accuracy than YOLOv8s with similar speed
    # Options: yolo11n (fast), yolo11s (balanced), yolo11m (accurate), yolo11l/x (most accurate)
    detection_model: str = "yolo11s"
    detection_confidence_threshold: float = 0.25  # lower threshold for more detections
    detection_iou_threshold: float = 0.45

    # Person recognition
    # Face embeddings survive a change of clothes but degrade behind a mask.
    # Body embeddings survive caps, glasses and masks but not a change of clothes.
    # Both are combined so each covers the other's blind spot.
    person_recognition_enabled: bool = True
    person_face_model: str = "buffalo_l"
    person_body_model_path: Optional[str] = None
    person_face_threshold: float = 0.38
    person_body_threshold: float = 0.75
    person_face_weight: float = 0.7
    person_min_face_size: int = 40
    person_max_embeddings_per_person: int = 40
    person_auto_enroll: bool = True
    person_category_name: str = "People"
    person_name_prefix: str = "Person"

    # Events
    # Emitted on a transition, never per frame: detection runs several times a
    # second and a per frame stream would drown any subscriber.
    events_enabled: bool = True
    events_store_captures: bool = True
    events_capture_max_side: int = 1024
    # How long a subject must be missing before a departure is raised. Without
    # this a single dropped frame reads as someone leaving and returning.
    events_absence_seconds: float = 4.0
    # Floor between two scene change events, whatever the scene does.
    events_scene_min_interval: float = 5.0
    events_retention_days: int = 30

    # Webhooks
    # Deliveries are signed with HMAC-SHA256 so a receiver can verify the
    # request came from this instance and was not altered in transit.
    webhooks_enabled: bool = True
    webhook_timeout_seconds: float = 10.0
    webhook_max_attempts: int = 3
    webhook_disable_after_failures: int = 20

    # Model Context Protocol
    # Read only by design: an agent that can be persuaded by the text it reads
    # must not be able to alter what a camera remembers about people.
    mcp_enabled: bool = True
    mcp_path: str = "/mcp"
    mcp_sse_path: str = "/mcp/sse"

    # Scene description
    # Runs locally on whatever accelerator the machine has, so no frame ever
    # leaves the host. Loaded lazily: a stack that never asks for a description
    # should not pay several gigabytes of download and VRAM for one.
    description_enabled: bool = True
    description_model: str = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
    description_max_tokens: int = 120
    description_max_side: int = 768
    description_prompt: str = (
        "Describe this scene in two or three sentences. Say what the people are "
        "doing and what the setting looks like, not just what is present."
    )

    # Object silhouettes
    # Segment Anything says exactly where an edge runs but not what the thing
    # is, so it never replaces the detector: it is prompted with the boxes the
    # detector already produced, which keeps the labels and adds the outline.
    segmentation_enabled: bool = True
    segmentation_model: str = "sam2.1_t"
    # Contours arrive with well over a thousand points for a large object. This
    # caps the polygon after simplification, per silhouette.
    segmentation_max_points: int = 80
    # A box prompt is ambiguous: the rectangle around a person also holds the
    # chair behind them. Tightness picks among the granularity levels the model
    # offers, 0 keeping the widest reading and 1 the narrowest.
    segmentation_tightness: float = 0.6
    # A mask covering more of its box than this has escaped onto the background.
    segmentation_max_coverage: float = 0.92
    # Feed the centres of other detections back as negative points, so the
    # silhouette of a person is told it is not the chair the detector already
    # found separately.
    segmentation_exclude_siblings: bool = True

    # Skeleton and mesh overlay
    # Bodies use the 33 point BlazePose layout, hands the 21 point layout and
    # faces the 478 point mesh, all of them from the MediaPipe Tasks API. Edge
    # lists come from the official connection constants rather than being
    # hardcoded, so the drawing cannot drift from the points.
    pose_enabled: bool = True
    pose_max_people: int = 4
    pose_confidence_threshold: float = 0.5
    pose_keypoint_threshold: float = 0.5
    hands_enabled: bool = True
    hands_max_number: int = 4
    hands_confidence_threshold: float = 0.4
    face_mesh_enabled: bool = True
    face_mesh_max_faces: int = 4
    face_mesh_confidence_threshold: float = 0.4
    # "contours" draws the silhouette of each feature with about a hundred
    # edges. "tesselation" draws the full low polygon mesh with a few thousand,
    # which is the 3D surface rather than an outline, at a real bandwidth cost.
    face_mesh_mode: str = "contours"

    # Hardware acceleration
    # Detected at runtime rather than configured, so the same image runs on a
    # workstation with a GPU and on a laptop without one. These only switch the
    # detection off or narrow it.
    acceleration_enabled: bool = True
    acceleration_mediapipe_gpu: bool = False

    # Detection display
    # Below this confidence a detection is reported as a guess, not a fact.
    detection_certainty_threshold: float = 0.7

    # Services
    use_mock_services: bool = False

    # Camera
    camera_frame_rate: int = 30
    camera_resolution_width: int = 1280
    camera_resolution_height: int = 720

    @property
    def api_prefix(self) -> str:
        """Get the full API prefix with version."""
        return f"/api/{self.api_version}"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings instance.

    Returns:
        Settings: Application settings singleton.
    """
    return Settings()


# Global settings instance
settings = get_settings()
