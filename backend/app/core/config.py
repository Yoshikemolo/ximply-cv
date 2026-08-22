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

    # Skeleton overlay
    # Body keypoints follow the COCO 17 point layout, which is what every YOLO
    # pose model emits and the format the skeleton edges below are defined for.
    # Hand landmarks follow the 21 point MediaPipe layout.
    pose_enabled: bool = True
    pose_model: str = "yolo11n-pose"
    pose_confidence_threshold: float = 0.5
    pose_keypoint_threshold: float = 0.5
    hands_enabled: bool = True
    hands_max_number: int = 4
    hands_confidence_threshold: float = 0.5

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
