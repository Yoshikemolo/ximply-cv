"""
Integration tokens.

Credentials issued to one external client each: an agent, a script, a webhook
receiver that also needs to read back. They exist because the alternatives are
worse. A shared password cannot be revoked without locking everyone out, and a
session token expires in half an hour, which is fine for a browser and useless
for a service.

Only a hash is stored. The value is shown once, at creation, and never again:
a credential that can be read back out of the database is one that leaks through
every screen, log and backup that touches it. A short prefix is kept in the
clear so a person can tell two tokens apart in a list, which is the only thing
they need to see afterwards.
"""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.entities import IntegrationTokenEntity

logger = get_logger(__name__)

# Tokens are recognisable on sight, so one pasted into the wrong field or
# committed to a repository can be spotted and revoked.
TOKEN_PREFIX = "xvt_"


def generate_token() -> Tuple[str, str, str]:
    """
    Create a token, returning the value, its hash and its display prefix.

    Returns:
        Tuple of (token, sha256 hex digest, prefix shown in listings).
    """
    value = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return value, hash_token(value), value[: len(TOKEN_PREFIX) + 6]


def hash_token(value: str) -> str:
    """
    Hash a token for storage and lookup.

    A plain SHA-256 rather than a password hash on purpose. A token is 32 bytes
    of randomness, so there is nothing to brute force and no dictionary to
    resist; the slow hash a password needs would only make every request slower.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def resolve_token(db: AsyncSession, value: str) -> Optional[IntegrationTokenEntity]:
    """
    Find the token behind a presented value, if it is usable.

    Args:
        db: Database session.
        value: The token as presented by the client.

    Returns:
        The token record, or None when unknown, inactive or expired.
    """
    if not value or not value.startswith(TOKEN_PREFIX):
        return None

    result = await db.execute(
        select(IntegrationTokenEntity).where(
            IntegrationTokenEntity.token_hash == hash_token(value)
        )
    )
    token = result.scalar_one_or_none()

    if token is None or not token.is_active:
        return None

    if token.expires_at is not None and token.expires_at < datetime.now(timezone.utc):
        return None

    # Recording the last use is what makes an unused token identifiable, which
    # is the first step in removing one nobody remembers issuing.
    token.last_used_at = datetime.now(timezone.utc)

    return token


def token_allows(token: IntegrationTokenEntity, permission: str) -> bool:
    """
    Whether a token may exercise a permission.

    An empty scope list means the token carries whatever its owner carries,
    which is the convenient default and the reason narrowing it is offered.
    """
    scopes: List[str] = token.scopes or []
    if not scopes:
        return True
    return permission in scopes
