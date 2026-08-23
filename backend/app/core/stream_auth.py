"""
Authentication for the streaming endpoints.

The stream is the first place an integration token reaches a route outside the
protocol mounts, so this is where the two kinds of credential meet. A session
token identifies a person using the interface; an `xvt_` value identifies a
machine client, and is held to the same scope rules the protocol applies.

The credential is read from the Authorization header and from nowhere else.
Accepting it in the query string would make an `img` tag work in exchange for
putting a live credential into browser history, proxy logs and referrer
headers, which SEC-0011 declines to trade.
"""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import async_session_factory
from app.core.logging import get_logger
from app.core.security import decode_token, has_any_permission
from app.models.enums import Permission
from app.services.integration_token_service import TOKEN_PREFIX, resolve_token

logger = get_logger(__name__)

security = HTTPBearer(auto_error=False)


@dataclass
class StreamPrincipal:
    """
    Whoever is reading a stream.

    Attributes:
        owner_id: The account whose records the stream carries.
        kind: Either "session" or "token".
        label: The email of the person, or the prefix of the token, for logs.
    """

    owner_id: UUID
    kind: str
    label: str


def token_scope_allows(scopes: list, permission: Permission, explicit: bool) -> bool:
    """
    Whether a scope list carries a permission.

    Kept as a function of its own so the rule can be tested without a request,
    a database or a token.

    Args:
        scopes: The scopes written on the token.
        permission: The permission being asked for.
        explicit: Whether an empty list is allowed to imply it.

    Returns:
        True when the permission is granted.
    """
    if explicit:
        return permission.value in (scopes or [])
    return not scopes or permission.value in scopes


def require_stream_scope(permission: Permission, explicit: bool = False):
    """
    Build a dependency that admits a session or an integration token.

    Args:
        permission: The scope the caller needs.
        explicit: When true, an integration token must list the scope by name.
            An empty scope list means "whatever the owner holds" for reading
            and must never mean that for looking through a camera, which is
            the rule ADR-0021 set for control and ADR-0023 extends to viewing.

    Returns:
        A FastAPI dependency returning the principal.
    """

    async def dependency(
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> StreamPrincipal:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        value = credentials.credentials
        if value.startswith(TOKEN_PREFIX):
            return await _from_integration_token(value, permission, explicit)
        return _from_session(value, permission)

    return dependency


async def _from_integration_token(
    value: str, permission: Permission, explicit: bool
) -> StreamPrincipal:
    """
    Resolve an integration token and check its scopes.

    The session is opened and closed here rather than injected, because a
    stream holds its request open for as long as somebody is watching and a
    pooled connection must not be held with it.

    Args:
        value: The raw token value.
        permission: The scope the caller needs.
        explicit: Whether the scope must be listed by name.

    Returns:
        The principal behind the token.

    Raises:
        HTTPException: When the token is unknown, inactive, expired, or does
            not carry the scope.
    """
    async with async_session_factory() as db:
        token = await resolve_token(db, value)
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        owner_id = token.owner_id
        prefix = token.prefix
        scopes = list(token.scopes or [])
        await db.commit()

    if not token_scope_allows(scopes, permission, explicit):
        logger.warning(
            f"Stream refused for token {prefix}: {permission.value} not granted"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The token does not carry {permission.value}",
        )

    return StreamPrincipal(owner_id=owner_id, kind="token", label=prefix)


def _from_session(value: str, permission: Permission) -> StreamPrincipal:
    """
    Resolve a session token and check the permission behind it.

    Args:
        value: The raw JWT value.
        permission: The permission the caller needs.

    Returns:
        The principal behind the session.

    Raises:
        HTTPException: When the token is invalid, of the wrong type, or the
            account does not hold the permission.
    """
    token_data = decode_token(value)
    if token_data is None or token_data.token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not has_any_permission(token_data, [permission.value]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    return StreamPrincipal(
        owner_id=UUID(token_data.sub), kind="session", label=token_data.email
    )


__all__ = ["StreamPrincipal", "require_stream_scope", "token_scope_allows"]
