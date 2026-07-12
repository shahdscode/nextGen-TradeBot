"""
Symmetric encryption for secrets at rest (e.g. per-user Alpaca API keys).

Stored ciphertext is prefixed with "enc:" so we can transparently read legacy
plaintext values that predate encryption and re-encrypt them on next write.

Key source:
  * SECRET_ENCRYPTION_KEY (a urlsafe-base64 32-byte Fernet key) if provided, else
  * derived deterministically from JWT_SECRET_KEY (SHA-256 -> base64).
Set a dedicated SECRET_ENCRYPTION_KEY in production; rotating the JWT secret would
otherwise make existing ciphertext unreadable.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:"


def _fernet() -> Fernet:
    key = (settings.secret_encryption_key or "").strip()
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    # Derive a stable Fernet key from the JWT secret.
    digest = hashlib.sha256(settings.jwt_secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    """Encrypt a secret for storage. Returns 'enc:<token>' or None for empty."""
    if not plain:
        return None
    token = _fernet().encrypt(plain.encode()).decode()
    return _PREFIX + token


def decrypt_secret(stored: Optional[str]) -> Optional[str]:
    """
    Decrypt a stored secret. Legacy plaintext (no 'enc:' prefix) is returned
    as-is so existing values keep working until re-saved.
    """
    if not stored:
        return None
    if not stored.startswith(_PREFIX):
        return stored  # legacy plaintext
    try:
        return _fernet().decrypt(stored[len(_PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        logger.error("Failed to decrypt a stored secret (wrong key?)")
        return None
