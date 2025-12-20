"""
User management API routes.

Provides CRUD operations for users (admin only).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from uuid_extensions import uuid7

from app.core.database import get_db
from app.core.dependencies import require_permissions
from app.core.logging import get_logger
from app.core.security import TokenData, get_password_hash
from app.models.entities import RoleEntity, UserEntity
from app.models.enums import Permission
from app.models.schemas import (
    MessageResponse,
    PaginatedResponse,
    RoleResponse,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])


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


@router.get("", response_model=PaginatedResponse[UserListResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: TokenData = Depends(require_permissions([Permission.USERS_READ])),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[UserListResponse]:
    """
    List all users with pagination.

    Args:
        page: Page number.
        page_size: Items per page.
        search: Search by email or name.
        status_filter: Filter by status.
        current_user: Authenticated admin user.
        db: Database session.

    Returns:
        PaginatedResponse: Paginated user list.
    """
    query = select(UserEntity)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            (UserEntity.email.ilike(search_term))
            | (UserEntity.full_name.ilike(search_term))
        )

    if status_filter:
        query = query.where(UserEntity.status == status_filter)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(UserEntity.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    users = result.scalars().all()

    items = [
        UserListResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            status=user.status,
            created_at=user.created_at,
        )
        for user in users
    ]

    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    current_user: TokenData = Depends(require_permissions([Permission.USERS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Create a new user.

    Args:
        data: User creation data.
        current_user: Authenticated admin user.
        db: Database session.

    Returns:
        UserResponse: Created user.
    """
    # Check if email exists
    result = await db.execute(
        select(UserEntity).where(UserEntity.email == data.email)
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    user = UserEntity(
        id=uuid7(),
        email=data.email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name,
        status="active",
        is_superuser=False,
    )

    # Assign roles if provided
    if data.role_ids:
        result = await db.execute(
            select(RoleEntity).where(RoleEntity.id.in_(data.role_ids))
        )
        roles = result.scalars().all()
        user.roles = list(roles)

    db.add(user)
    await db.commit()
    await db.refresh(user, ["roles"])

    logger.info(f"User created: {user.email} by admin {current_user.sub}")

    return build_user_response(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.USERS_READ])),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Get a user by ID.

    Args:
        user_id: User UUID.
        current_user: Authenticated admin user.
        db: Database session.

    Returns:
        UserResponse: User details.
    """
    result = await db.execute(
        select(UserEntity)
        .options(selectinload(UserEntity.roles))
        .where(UserEntity.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return build_user_response(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    data: UserUpdate,
    current_user: TokenData = Depends(require_permissions([Permission.USERS_WRITE])),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Update a user.

    Args:
        user_id: User UUID.
        data: Update data.
        current_user: Authenticated admin user.
        db: Database session.

    Returns:
        UserResponse: Updated user.
    """
    result = await db.execute(
        select(UserEntity)
        .options(selectinload(UserEntity.roles))
        .where(UserEntity.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Check email uniqueness if changing
    if data.email and data.email != user.email:
        email_result = await db.execute(
            select(UserEntity).where(UserEntity.email == data.email)
        )
        if email_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )

    # Update fields
    update_data = data.model_dump(exclude_unset=True, exclude={"role_ids"})
    for field, value in update_data.items():
        if hasattr(user, field):
            setattr(user, field, value)

    # Update roles if provided
    if data.role_ids is not None:
        result = await db.execute(
            select(RoleEntity).where(RoleEntity.id.in_(data.role_ids))
        )
        roles = result.scalars().all()
        user.roles = list(roles)

    await db.commit()
    await db.refresh(user, ["roles"])

    logger.info(f"User updated: {user.email} by admin {current_user.sub}")

    return build_user_response(user)


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: UUID,
    current_user: TokenData = Depends(require_permissions([Permission.USERS_DELETE])),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """
    Delete a user.

    Args:
        user_id: User UUID.
        current_user: Authenticated admin user.
        db: Database session.

    Returns:
        MessageResponse: Deletion confirmation.
    """
    result = await db.execute(
        select(UserEntity).where(UserEntity.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent self-deletion
    if str(user_id) == current_user.sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    # Prevent superuser deletion
    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete superuser",
        )

    await db.delete(user)
    await db.commit()

    logger.info(f"User deleted: {user_id} by admin {current_user.sub}")

    return MessageResponse(message="User deleted successfully")
