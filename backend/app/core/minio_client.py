"""
MinIO client configuration and utilities.

Provides S3-compatible object storage operations.
"""

from io import BytesIO
from typing import BinaryIO, Optional

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def create_minio_client(endpoint: Optional[str] = None) -> Minio:
    """
    Create MinIO client instance.

    Args:
        endpoint: Optional custom endpoint. Uses settings.minio_endpoint if None.

    Returns:
        Minio: Configured MinIO client.
    """
    return Minio(
        endpoint or settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


# Global MinIO client instance for internal operations
minio_client = create_minio_client()


async def ensure_bucket_exists(bucket_name: Optional[str] = None) -> bool:
    """
    Ensure the specified bucket exists, create if not.

    Args:
        bucket_name: Name of the bucket. Uses default from settings if None.

    Returns:
        bool: True if bucket exists or was created successfully.
    """
    bucket = bucket_name or settings.minio_bucket

    try:
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)
            logger.info(f"Created MinIO bucket: {bucket}")
        return True
    except S3Error as e:
        logger.error(f"Failed to ensure bucket exists: {e}")
        return False


def upload_file(
    file_data: BinaryIO,
    object_name: str,
    content_type: str = "application/octet-stream",
    bucket_name: Optional[str] = None,
) -> bool:
    """
    Upload a file to MinIO.

    Args:
        file_data: File-like object to upload.
        object_name: Name/path for the object in the bucket.
        content_type: MIME type of the file.
        bucket_name: Target bucket. Uses default from settings if None.

    Returns:
        bool: True if upload was successful.
    """
    bucket = bucket_name or settings.minio_bucket

    try:
        # Get file size
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)

        minio_client.put_object(
            bucket,
            object_name,
            file_data,
            file_size,
            content_type=content_type,
        )
        logger.info(f"Uploaded object: {object_name} to bucket: {bucket}")
        return True
    except S3Error as e:
        logger.error(f"Failed to upload object: {e}")
        return False


def upload_bytes(
    data: bytes,
    object_name: str,
    content_type: str = "application/octet-stream",
    bucket_name: Optional[str] = None,
) -> bool:
    """
    Upload bytes data to MinIO.

    Args:
        data: Bytes to upload.
        object_name: Name/path for the object in the bucket.
        content_type: MIME type of the data.
        bucket_name: Target bucket. Uses default from settings if None.

    Returns:
        bool: True if upload was successful.
    """
    return upload_file(BytesIO(data), object_name, content_type, bucket_name)


def download_file(
    object_name: str,
    bucket_name: Optional[str] = None,
) -> Optional[bytes]:
    """
    Download a file from MinIO.

    Args:
        object_name: Name/path of the object in the bucket.
        bucket_name: Source bucket. Uses default from settings if None.

    Returns:
        bytes: File contents if successful, None otherwise.
    """
    bucket = bucket_name or settings.minio_bucket

    try:
        response = minio_client.get_object(bucket, object_name)
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except S3Error as e:
        logger.error(f"Failed to download object: {e}")
        return None


def delete_file(
    object_name: str,
    bucket_name: Optional[str] = None,
) -> bool:
    """
    Delete a file from MinIO.

    Args:
        object_name: Name/path of the object to delete.
        bucket_name: Source bucket. Uses default from settings if None.

    Returns:
        bool: True if deletion was successful.
    """
    bucket = bucket_name or settings.minio_bucket

    try:
        minio_client.remove_object(bucket, object_name)
        logger.info(f"Deleted object: {object_name} from bucket: {bucket}")
        return True
    except S3Error as e:
        logger.error(f"Failed to delete object: {e}")
        return False


def get_presigned_url(
    object_name: str,
    expires_hours: int = 1,
    bucket_name: Optional[str] = None,
) -> Optional[str]:
    """
    Generate a presigned URL for downloading an object.

    Note: This function is deprecated. Use the proxy endpoint at
    /api/v1/objects/files/{path} instead to avoid signature issues
    when accessing from browsers in Docker environments.

    Args:
        object_name: Name/path of the object.
        expires_hours: URL expiration time in hours.
        bucket_name: Source bucket. Uses default from settings if None.

    Returns:
        str: Presigned URL if successful, None otherwise.
    """
    bucket = bucket_name or settings.minio_bucket

    try:
        from datetime import timedelta

        url = minio_client.presigned_get_object(
            bucket,
            object_name,
            expires=timedelta(hours=expires_hours),
        )

        return url
    except S3Error as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        return None


def list_objects(
    prefix: str = "",
    bucket_name: Optional[str] = None,
) -> list:
    """
    List objects in a bucket with optional prefix filter.

    Args:
        prefix: Filter objects by prefix.
        bucket_name: Source bucket. Uses default from settings if None.

    Returns:
        list: List of object names matching the prefix.
    """
    bucket = bucket_name or settings.minio_bucket

    try:
        objects = minio_client.list_objects(bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]
    except S3Error as e:
        logger.error(f"Failed to list objects: {e}")
        return []


def check_connection() -> bool:
    """
    Check if MinIO connection is healthy.

    Returns:
        bool: True if connection is successful.
    """
    try:
        minio_client.list_buckets()
        return True
    except Exception as e:
        logger.error(f"MinIO connection check failed: {e}")
        return False
