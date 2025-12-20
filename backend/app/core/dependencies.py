"""
FastAPI dependency injection utilities.

Provides reusable dependencies for authentication, authorization, and database access.
"""

from typing import List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import TokenData, decode_token, has_all_permissions, has_any_permission

logger = get_logger(__name__)

# Security scheme
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    """
    Validate JWT token and return current user data.

    Args:
        credentials: HTTP Bearer credentials.

    Returns:
        TokenData: Decoded token data containing user information.

    Raises:
        HTTPException: If token is missing, invalid, or expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_token(credentials.credentials)

    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token_data.token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_data


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[TokenData]:
    """
    Validate JWT token if present, return None if not.

    Args:
        credentials: HTTP Bearer credentials.

    Returns:
        TokenData: Decoded token data if valid, None otherwise.
    """
    if credentials is None:
        return None

    return decode_token(credentials.credentials)


def require_permissions(permissions: List[str], require_all: bool = True):
    """
    Create a dependency that requires specific permissions.

    Args:
        permissions: List of required permission strings.
        require_all: If True, all permissions are required. If False, any one is sufficient.

    Returns:
        Callable: Dependency function for FastAPI.

    Example:
        @app.get("/admin", dependencies=[Depends(require_permissions(["admin:read"]))])
        async def admin_endpoint():
            ...
    """

    async def permission_checker(
        current_user: TokenData = Depends(get_current_user),
    ) -> TokenData:
        if require_all:
            has_perms = has_all_permissions(current_user, permissions)
        else:
            has_perms = has_any_permission(current_user, permissions)

        if not has_perms:
            logger.warning(
                f"Permission denied for user {current_user.sub}. "
                f"Required: {permissions}, Has: {current_user.permissions}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return current_user

    return permission_checker


def require_roles(roles: List[str], require_all: bool = False):
    """
    Create a dependency that requires specific roles.

    Args:
        roles: List of required role names.
        require_all: If True, all roles are required. If False, any one is sufficient.

    Returns:
        Callable: Dependency function for FastAPI.

    Example:
        @app.get("/admin", dependencies=[Depends(require_roles(["admin"]))])
        async def admin_endpoint():
            ...
    """

    async def role_checker(
        current_user: TokenData = Depends(get_current_user),
    ) -> TokenData:
        if require_all:
            has_roles = all(role in current_user.roles for role in roles)
        else:
            has_roles = any(role in current_user.roles for role in roles)

        if not has_roles:
            logger.warning(
                f"Role denied for user {current_user.sub}. "
                f"Required: {roles}, Has: {current_user.roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )

        return current_user

    return role_checker


class DatabaseDep:
    """Database session dependency with proper typing."""

    def __call__(self, db: AsyncSession = Depends(get_db)) -> AsyncSession:
        """Return database session."""
        return db


# Typed dependency for IDE support
db_dependency = DatabaseDep()
