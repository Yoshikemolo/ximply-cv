"""
Authentication API routes.

Provides endpoints for user login, registration, and token management.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.logging import get_logger
from app.core.security import (
    TokenData,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.entities import UserEntity, RoleEntity
from app.models.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RegisterRequest,
    RoleResponse,
    UserResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


def build_user_response(user: UserEntity) -> UserResponse:
    """Build user response with roles."""
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
        roles=[
            RoleResponse(
                id=role.id,
                name=role.name,
                description=role.description,
                is_system=role.is_system,
                created_at=role.created_at,
                permissions=[],
            )
            for role in user.roles
        ],
    )


def collect_permissions(user: UserEntity) -> list[str]:
    """Collect all permissions from user roles."""
    permissions = set()
    for role in user.roles:
        for perm in role.permissions:
            permissions.add(perm.code)
    return list(permissions)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate user and return JWT tokens.

    Args:
        request: Login credentials.
        db: Database session.

    Returns:
        LoginResponse: Access and refresh tokens with user info.

    Raises:
        HTTPException: If credentials are invalid.
    """
    # Find user by email
    result = await db.execute(
        select(UserEntity)
        .options(selectinload(UserEntity.roles).selectinload(RoleEntity.permissions))
        .where(UserEntity.email == request.email)
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(request.password, user.hashed_password):
        logger.warning(f"Failed login attempt for email: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User account is {user.status}",
        )

    # Collect permissions and roles BEFORE commit (while data is still loaded)
    permissions = collect_permissions(user)
    roles = [role.name for role in user.roles]

    # Build user response before commit
    user_response = UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
        roles=[
            RoleResponse(
                id=role.id,
                name=role.name,
                description=role.description,
                is_system=role.is_system,
                created_at=role.created_at,
                permissions=[],
            )
            for role in user.roles
        ],
    )

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    # Create tokens
    token_data = {
        "sub": str(user.id),
        "email": user.email,
        "roles": roles,
        "permissions": permissions,
        "is_superuser": user.is_superuser,
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user.id)})

    logger.info(f"User logged in: {user.email}")

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=user_response,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Register a new user account.

    Args:
        request: Registration data.
        db: Database session.

    Returns:
        UserResponse: Created user information.

    Raises:
        HTTPException: If email is already registered.
    """
    # Check if email exists
    result = await db.execute(
        select(UserEntity).where(UserEntity.email == request.email)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    user = UserEntity(
        id=uuid7(),
        email=request.email,
        hashed_password=get_password_hash(request.password),
        full_name=request.full_name,
        status="active",
        is_superuser=False,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"New user registered: {user.email}")

    # Return user response without roles (new users have no roles)
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        is_superuser=user.is_superuser,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
        roles=[],
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> RefreshTokenResponse:
    """
    Refresh access token using refresh token.

    Args:
        request: Refresh token.
        db: Database session.

    Returns:
        RefreshTokenResponse: New access token.

    Raises:
        HTTPException: If refresh token is invalid.
    """
    token_data = decode_token(request.refresh_token)

    if token_data is None or token_data.token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Get user to refresh permissions
    result = await db.execute(
        select(UserEntity)
        .options(selectinload(UserEntity.roles).selectinload(RoleEntity.permissions))
        .where(UserEntity.id == token_data.sub)
    )
    user = result.scalar_one_or_none()

    if user is None or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Collect current permissions
    permissions = collect_permissions(user)
    roles = [role.name for role in user.roles]

    # Create new access token
    new_token_data = {
        "sub": str(user.id),
        "email": user.email,
        "roles": roles,
        "permissions": permissions,
        "is_superuser": user.is_superuser,
    }

    access_token = create_access_token(new_token_data)

    return RefreshTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Get current authenticated user information.

    Args:
        current_user: Token data from JWT.
        db: Database session.

    Returns:
        UserResponse: Current user information.
    """
    result = await db.execute(
        select(UserEntity)
        .options(selectinload(UserEntity.roles))
        .where(UserEntity.id == current_user.sub)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return build_user_response(user)


@router.post("/logout")
async def logout(
    current_user: TokenData = Depends(get_current_user),
) -> dict:
    """
    Logout current user.

    Note: JWT tokens are stateless. Client should discard tokens.

    Returns:
        dict: Logout confirmation.
    """
    logger.info(f"User logged out: {current_user.email}")
    return {"message": "Successfully logged out"}
