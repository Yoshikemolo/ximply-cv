"""
Security utilities for authentication and authorization.

Provides JWT token generation, validation, and password hashing.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.core.config import settings


# Password hashing context
# Use bcrypt__ident="2b" to avoid passlib bug detection issues with bcrypt>=4.1
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__ident="2b",
)


class TokenData(BaseModel):
    """
    JWT token payload data.

    Attributes:
        sub: Subject (user ID).
        email: User email address.
        roles: List of role names.
        permissions: List of permission strings.
        exp: Expiration timestamp.
        iat: Issued at timestamp.
        token_type: Type of token (access or refresh).
    """

    sub: str
    email: str
    roles: List[str] = []
    permissions: List[str] = []
    exp: Optional[datetime] = None
    iat: Optional[datetime] = None
    token_type: str = "access"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    Args:
        plain_password: The plain text password to verify.
        hashed_password: The hashed password to compare against.

    Returns:
        bool: True if the password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a plain password using bcrypt.

    Args:
        password: The plain text password to hash.

    Returns:
        str: The hashed password.
    """
    return pwd_context.hash(password)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        data: Dictionary containing token payload data.
        expires_delta: Optional custom expiration time.

    Returns:
        str: Encoded JWT access token.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": "access",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a JWT refresh token.

    Args:
        data: Dictionary containing token payload data.
        expires_delta: Optional custom expiration time.

    Returns:
        str: Encoded JWT refresh token.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": "refresh",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    return encoded_jwt


def decode_token(token: str) -> Optional[TokenData]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string to decode.

    Returns:
        TokenData: Decoded token data if valid, None otherwise.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        return TokenData(
            sub=payload.get("sub", ""),
            email=payload.get("email", ""),
            roles=payload.get("roles", []),
            permissions=payload.get("permissions", []),
            exp=datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc),
            iat=datetime.fromtimestamp(payload.get("iat", 0), tz=timezone.utc),
            token_type=payload.get("token_type", "access"),
        )
    except JWTError:
        return None


def has_permission(token_data: TokenData, required_permission: str) -> bool:
    """
    Check if token has the required permission.

    Args:
        token_data: Decoded token data.
        required_permission: Permission string to check.

    Returns:
        bool: True if permission is present, False otherwise.
    """
    return required_permission in token_data.permissions


def has_any_permission(token_data: TokenData, permissions: List[str]) -> bool:
    """
    Check if token has any of the required permissions.

    Args:
        token_data: Decoded token data.
        permissions: List of permission strings to check.

    Returns:
        bool: True if any permission is present, False otherwise.
    """
    return any(perm in token_data.permissions for perm in permissions)


def has_all_permissions(token_data: TokenData, permissions: List[str]) -> bool:
    """
    Check if token has all required permissions.

    Args:
        token_data: Decoded token data.
        permissions: List of permission strings to check.

    Returns:
        bool: True if all permissions are present, False otherwise.
    """
    return all(perm in token_data.permissions for perm in permissions)


def has_role(token_data: TokenData, role: str) -> bool:
    """
    Check if token has a specific role.

    Args:
        token_data: Decoded token data.
        role: Role name to check.

    Returns:
        bool: True if role is present, False otherwise.
    """
    return role in token_data.roles
