"""Canonical request string and HMAC signature (contract 2, section 3.4).

packages/shared/src/signing.ts builds the same string in TypeScript and both
sides must produce identical bytes, otherwise a request signed by the app fails
here with no useful diagnostic. Every rule that could silently break that is
spelled out below and pinned by fixed vectors in tests/test_security.py.

Nothing here touches the database, the clock or the network. Pure bytes in,
pure text out, which is exactly what makes it comparable to the TypeScript
implementation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

# sha256 of zero bytes. A GET carries no body, so this constant is what the
# digest line holds on most requests. Written out rather than computed so a
# mismatch with the TypeScript side is visible by reading the two files.
EMPTY_BODY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Nonce is 16 random bytes, base64url without padding, so 22 characters. The
# bounds are generous on purpose: they reject an abusive header, not a client
# that pads or trims differently.
MIN_NONCE_LENGTH = 8
MAX_NONCE_LENGTH = 256


def body_digest(body: bytes | None) -> str:
    """Lowercase hex sha256 of the exact bytes sent.

    The client serialises its body once, digests that string and sends that
    same string. Re-serialising the parsed body here would change whitespace
    and key order, so the raw bytes are the only valid input.
    """
    return hashlib.sha256(body or b"").hexdigest()


def canonical_string(
    *,
    timestamp: str,
    nonce: str,
    method: str,
    path_with_query: str,
    digest: str,
) -> str:
    """The five newline separated lines that get signed.

    timestamp is unix seconds as a decimal string with no fraction. method is
    uppercased here so a client sending "get" still verifies. path_with_query
    starts with a slash and carries the query string exactly as sent, with no
    reordering and no re-encoding, because the client signed what it typed.
    """
    return "\n".join(
        [
            str(timestamp),
            nonce,
            method.upper(),
            path_with_query,
            digest,
        ]
    )


def sign_canonical(secret: bytes, canonical: str) -> str:
    """Standard base64 of hmac sha256 over the utf-8 canonical string."""
    mac = hmac.new(secret, canonical.encode("utf-8"), digestmod=hashlib.sha256)
    return base64.b64encode(mac.digest()).decode("ascii")


def sign_request(
    *,
    secret: bytes,
    timestamp: str,
    nonce: str,
    method: str,
    path_with_query: str,
    body: bytes | None = None,
) -> str:
    """Build the canonical string for a request and sign it.

    Used by tests and by any server side client. Real requests arrive already
    signed and go through verify_request instead.
    """
    canonical = canonical_string(
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path_with_query=path_with_query,
        digest=body_digest(body),
    )
    return sign_canonical(secret, canonical)


def verify_signature(*, secret: bytes, canonical: str, signature: str) -> bool:
    """Constant time comparison of a presented signature.

    Both sides are compared as bytes rather than as text: compare_digest
    refuses a str holding anything outside ASCII, and the presented value comes
    from an attacker controlled header.
    """
    expected = sign_canonical(secret, canonical)
    return hmac.compare_digest(
        expected.encode("ascii"), (signature or "").encode("utf-8", "ignore")
    )


def verify_request(
    *,
    secret: bytes,
    timestamp: str,
    nonce: str,
    method: str,
    path_with_query: str,
    body: bytes | None,
    signature: str,
) -> bool:
    """Rebuild the canonical string from the request and compare signatures."""
    canonical = canonical_string(
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path_with_query=path_with_query,
        digest=body_digest(body),
    )
    return verify_signature(secret=secret, canonical=canonical, signature=signature)


def looks_like_nonce(nonce: str | None) -> bool:
    """Cheap shape check so a junk header never reaches the nonce table."""
    text = (nonce or "").strip()
    return MIN_NONCE_LENGTH <= len(text) <= MAX_NONCE_LENGTH


__all__ = [
    "EMPTY_BODY_DIGEST",
    "MAX_NONCE_LENGTH",
    "MIN_NONCE_LENGTH",
    "body_digest",
    "canonical_string",
    "looks_like_nonce",
    "sign_canonical",
    "sign_request",
    "verify_request",
    "verify_signature",
]
