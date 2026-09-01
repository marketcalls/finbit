"""Admin password hashing with argon2id (contract 2, section 3.8).

argon2-cffi's defaults are used deliberately: they are chosen by people who
follow the parameter guidance, and a hand-tuned cost here would age badly. The
parameters travel inside the hash string, so raising them later only means
needs_rehash starts returning True on the next successful login.

verify_password never raises. A malformed or truncated hash in the database is
a failed login, not a 500 that tells the caller the row exists.
"""

from __future__ import annotations

import logging

from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHashError, VerifyMismatchError

logger = logging.getLogger(__name__)

# Section 3.8 sets the floor. Short passwords are refused at the door rather
# than hashed, so a weak one never reaches the database.
MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher()

# Hashing the same throwaway password every time an unknown username is tried
# keeps the wrong-username and wrong-password paths comparable in cost, so the
# response time does not say which of the two was wrong.
_DUMMY_PASSWORD = "finbit-timing-equaliser"
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    """Hash a password with argon2id. Raises ValueError when it is too short."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"the password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str | None) -> bool:
    """True when the password matches the stored hash. Never raises.

    Every argon2 failure, including a hash string that is not argon2 at all,
    comes back as False.
    """
    if not password_hash or password is None:
        return False
    try:
        return bool(_hasher.verify(password_hash, password))
    except VerifyMismatchError:
        return False
    except (InvalidHashError, HashingError, TypeError, ValueError):
        # Never log the hash or the password, only that the row is unusable.
        logger.warning("an admin password hash could not be verified")
        return False


def needs_rehash(password_hash: str | None) -> bool:
    """True when a stored hash predates the current argon2 parameters.

    Call it after a successful login and rewrite the row when it says yes.
    """
    if not password_hash:
        return False
    try:
        return bool(_hasher.check_needs_rehash(password_hash))
    except (InvalidHashError, TypeError, ValueError):
        return True


def dummy_verify() -> None:
    """Burn one argon2 verification, for the unknown username path.

    Costs the same as a real check, so an attacker cannot separate an unknown
    username from a wrong password by timing the response.
    """
    global _dummy_hash
    try:
        if _dummy_hash is None:
            _dummy_hash = _hasher.hash(_DUMMY_PASSWORD)
        _hasher.verify(_dummy_hash, _DUMMY_PASSWORD)
    except Exception:  # noqa: BLE001 - a timing equaliser must never fail a login
        return


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "dummy_verify",
    "hash_password",
    "needs_rehash",
    "verify_password",
]
