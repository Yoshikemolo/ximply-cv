"""
Database configuration and session management.

Provides async SQLAlchemy engine and session factories for PostgreSQL.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, selectinload
from uuid_extensions import uuid7

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""

    pass


def create_engine() -> AsyncEngine:
    """
    Create async SQLAlchemy engine.

    Returns:
        AsyncEngine: Configured async database engine.
    """
    return create_async_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_pre_ping=False,  # Disabled to avoid greenlet issues with asyncpg
        echo=settings.debug,
    )


# Global engine instance
engine = create_engine()

# Session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency injection for database sessions.

    Yields:
        AsyncSession: Database session for the request.

    Example:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Use this when not in a request context.

    Yields:
        AsyncSession: Database session.

    Example:
        async with get_db_context() as db:
            result = await db.execute(query)
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.

    Creates all tables defined in the models.
    Should be called on application startup.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")


async def close_db() -> None:
    """
    Close database connections.

    Should be called on application shutdown.
    """
    await engine.dispose()
    logger.info("Database connections closed")


async def seed_initial_data() -> None:
    """
    Seed initial data: permissions, roles, and admin user.

    Creates default permissions, admin role, and admin user if they don't exist.
    Should be called on application startup after init_db().
    """
    # Import here to avoid circular imports
    from app.core.security import get_password_hash
    from app.models.entities import PermissionEntity, RoleEntity, UserEntity
    from app.models.enums import Permission

    async with async_session_factory() as session:
        try:
            # 1. Create all permissions if they don't exist
            all_permissions = []
            for perm in Permission:
                result = await session.execute(
                    select(PermissionEntity).where(PermissionEntity.code == perm.value)
                )
                existing = result.scalar_one_or_none()

                if existing is None:
                    # Parse permission code to get category and name
                    parts = perm.value.split(":")
                    category = parts[0] if len(parts) > 0 else "general"
                    action = parts[1] if len(parts) > 1 else perm.value

                    new_perm = PermissionEntity(
                        id=uuid7(),
                        code=perm.value,
                        name=f"{category.title()} {action.title()}",
                        description=f"Permission to {action} {category}",
                        category=category,
                    )
                    session.add(new_perm)
                    all_permissions.append(new_perm)
                    logger.info(f"Created permission: {perm.value}")
                else:
                    all_permissions.append(existing)

            await session.flush()

            # 2. Create admin role if it doesn't exist
            result = await session.execute(
                select(RoleEntity)
                .options(selectinload(RoleEntity.permissions))
                .where(RoleEntity.name == "admin")
            )
            admin_role = result.scalar_one_or_none()

            if admin_role is None:
                admin_role = RoleEntity(
                    id=uuid7(),
                    name="admin",
                    description="Administrator with full access",
                    is_system=True,
                )
                session.add(admin_role)
                await session.flush()
                logger.info("Created admin role")

            # 3. Assign all permissions to admin role using direct SQL
            # This avoids greenlet issues with async relationship loading

            # Get admin role ID
            result = await session.execute(
                select(RoleEntity.id).where(RoleEntity.name == "admin")
            )
            admin_role_id = result.scalar_one()

            # Get all permission IDs
            result = await session.execute(select(PermissionEntity.id))
            all_perm_ids = result.scalars().all()

            # Get existing role_permission entries for admin role
            existing_result = await session.execute(
                text("SELECT permission_id FROM role_permissions WHERE role_id = :role_id"),
                {"role_id": admin_role_id}
            )
            existing_perm_ids = {row[0] for row in existing_result.fetchall()}

            # Insert missing permissions
            for perm_id in all_perm_ids:
                if perm_id not in existing_perm_ids:
                    await session.execute(
                        text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :perm_id)"),
                        {"role_id": admin_role_id, "perm_id": perm_id}
                    )
                    logger.info(f"Assigned permission to admin role")

            await session.flush()

            # 4. Create or update admin user
            admin_email = settings.admin_email if hasattr(settings, 'admin_email') else "admin@ximply.com"
            admin_password = settings.admin_password if hasattr(settings, 'admin_password') else "Admin1234"

            result = await session.execute(
                select(UserEntity).where(UserEntity.email == admin_email)
            )
            admin_user = result.scalar_one_or_none()

            if admin_user is None:
                admin_user = UserEntity(
                    id=uuid7(),
                    email=admin_email,
                    hashed_password=get_password_hash(admin_password),
                    full_name="Administrator",
                    status="active",
                    is_superuser=True,
                )
                session.add(admin_user)
                await session.flush()
                logger.info(f"Created admin user: {admin_email}")
            else:
                # Ensure admin is superuser and has correct password
                updated = False
                if not admin_user.is_superuser:
                    admin_user.is_superuser = True
                    updated = True
                    logger.info(f"Updated {admin_email} to superuser")

                # Update password to ensure it matches expected value
                admin_user.hashed_password = get_password_hash(admin_password)
                updated = True

                if updated:
                    await session.flush()
                    logger.info(f"Updated admin user credentials: {admin_email}")

            # 5. Assign admin role to admin user using direct SQL
            admin_user_id = admin_user.id
            existing_role_result = await session.execute(
                text("SELECT role_id FROM user_roles WHERE user_id = :user_id AND role_id = :role_id"),
                {"user_id": admin_user_id, "role_id": admin_role_id}
            )
            if existing_role_result.fetchone() is None:
                await session.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                    {"user_id": admin_user_id, "role_id": admin_role_id}
                )
                logger.info(f"Assigned admin role to {admin_email}")

            await session.commit()
            logger.info("Initial data seeding complete")

        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to seed initial data: {e}")
            raise
