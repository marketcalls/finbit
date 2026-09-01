"""App keys and device secret derivation (contract 2, sections 3.2 and 3.3).

Two ideas live here.

The app key tells the API which of the two clients is calling, so either can be
rotated without touching the other. It is a build-time public value: it raises
the cost of calling the API from a script, it does not prove app identity.

The device secret is never stored. It is derived from the device id with the
master key on every use, so a copy of the database holds nothing that can sign
a request. Rotating DEVICE_MASTER_KEY invalidates every device at once, which
is the intended emergency lever.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from base64 import b64encode
from dataclasses import dataclass

from app.config import get_settings

APP_ID_MOBILE = "mobile"
APP_ID_WEB = "web"
APP_IDS: tuple[str, ...] = (APP_ID_MOBILE, APP_ID_WEB)

PLATFORMS: tuple[str, ...] = ("ios", "android", "web")

# Which platforms each client may register. A web bundle claiming to be an iOS
# device is either a mistake or someone poking at the API.
PLATFORMS_BY_APP_ID: dict[str, tuple[str, ...]] = {
    APP_ID_MOBILE: ("ios", "android"),
    APP_ID_WEB: ("web",),
}


@dataclass(frozen=True)
class DeviceSecret:
    """A derived device secret in both forms.

    raw signs on the server. b64 is the standard base64 text handed to the
    client once, at registration, and never again.
    """

    raw: bytes
    b64: str


def app_id_for_key(app_key: str | None) -> str | None:
    """Return the app id an X-App-Key header belongs to, or None.

    Compared in constant time against every configured key. An unset or
    placeholder key is not in the map at all, so an empty header can never
    match one.
    """
    presented = (app_key or "").strip()
    if not presented:
        return None
    candidate = presented.encode("utf-8")
    matched: str | None = None
    for configured, app_id in get_settings().app_keys.items():
        if hmac.compare_digest(candidate, configured.encode("utf-8")):
            matched = app_id
    return matched


def is_valid_app_key(app_key: str | None) -> bool:
    """True when the header matches one of the configured app keys."""
    return app_id_for_key(app_key) is not None


def is_known_app_id(app_id: str | None) -> bool:
    """True for 'mobile' or 'web', the only two clients in this build."""
    return (app_id or "").strip().lower() in APP_IDS


def platform_allowed(app_id: str, platform: str) -> bool:
    """True when this client is allowed to register on that platform."""
    allowed = PLATFORMS_BY_APP_ID.get((app_id or "").strip().lower(), ())
    return (platform or "").strip().lower() in allowed


def master_key_bytes() -> bytes:
    """The device master key as bytes, exactly as configured.

    The value is taken verbatim and utf-8 encoded rather than decoded as hex or
    base64. One unambiguous rule matters more than a compact key here: the
    master key never leaves the server, so nothing else has to agree with this
    interpretation.
    """
    settings = get_settings()
    key = settings.device_master_key.encode("utf-8")
    if not key:
        raise RuntimeError(
            "DEVICE_MASTER_KEY is not set. Device secrets cannot be derived "
            "without it. Set it in the .env file at the repo root."
        )
    return key


def derive_device_secret(device_id: str) -> DeviceSecret:
    """hmac_sha256(DEVICE_MASTER_KEY, device_id), in raw and base64 form.

    Deterministic, so the same device id always derives the same secret and the
    server can verify a signature while storing nothing.
    """
    identifier = (device_id or "").strip()
    if not identifier:
        raise ValueError("device_id is required to derive a device secret")
    raw = hmac.new(
        master_key_bytes(), identifier.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    return DeviceSecret(raw=raw, b64=b64encode(raw).decode("ascii"))


def new_device_id() -> str:
    """A fresh opaque device id.

    A uuid4 in hex: 32 characters, no separators, safe in a header and in a URL,
    and carrying nothing about the device it names.
    """
    return uuid.uuid4().hex


__all__ = [
    "APP_IDS",
    "APP_ID_MOBILE",
    "APP_ID_WEB",
    "PLATFORMS",
    "PLATFORMS_BY_APP_ID",
    "DeviceSecret",
    "app_id_for_key",
    "derive_device_secret",
    "is_known_app_id",
    "is_valid_app_key",
    "master_key_bytes",
    "new_device_id",
    "platform_allowed",
]
