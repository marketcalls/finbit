"""Runtime settings the admin can change without a restart (contract 2, section 5).

The .env file is the floor and the app_settings table is the override: a row
here wins over the value that came from the environment, so the schedule can be
retuned from the admin screens while the process keeps serving. Only the six
keys in models.PIPELINE_SETTING_KEYS are overridable, and no secret is one of
them on purpose. A database row must never be able to change how a request is
authenticated, so anything that would weaken authentication stays in .env where
it takes a deployment to move it.

Values are stored as JSON text, so a bool comes back a bool and the query set
comes back a list rather than the string "True". The decoded overrides are
cached in memory because effective() is read on every scheduler tick; every
writer in this module clears that cache, so a PATCH is visible to the next read
without a restart.

The query set is the one key with two shapes. app_settings holds the full nine
query definitions (key, label, prompt, category_hint, enabled), because that is
what app.pipeline.queries needs to run a cycle. The admin pipeline payload
exposes it as the list of enabled keys, which is what PipelineSettings declares.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable, Mapping
from typing import Any

from app import repo
from app.config import get_settings
from app.db import get_db_path
from app.models import CATEGORY_KEYS, PIPELINE_SETTING_KEYS

logger = logging.getLogger(__name__)

OVERRIDABLE_KEYS: tuple[str, ...] = PIPELINE_SETTING_KEYS
"""The only names set_setting accepts. Anything else raises KeyError."""

KEY_INGEST_ENABLED = "ingest_enabled"
KEY_INGEST_INTERVAL_MINUTES = "ingest_interval_minutes"
KEY_INGEST_QUERIES_PER_CYCLE = "ingest_queries_per_cycle"
KEY_INGEST_MAX_STORIES_PER_QUERY = "ingest_max_stories_per_query"
KEY_RESCORE_INTERVAL_MINUTES = "rescore_interval_minutes"
KEY_QUERY_SET = "query_set"

_BOOL_KEYS: frozenset[str] = frozenset({KEY_INGEST_ENABLED})
_INT_KEYS: frozenset[str] = frozenset(
    {
        KEY_INGEST_INTERVAL_MINUTES,
        KEY_INGEST_QUERIES_PER_CYCLE,
        KEY_INGEST_MAX_STORIES_PER_QUERY,
        KEY_RESCORE_INTERVAL_MINUTES,
    }
)

# Upper bounds on the numeric keys. They are not arbitrary tidiness: an
# interval of zero would busy loop the scheduler and a huge queries-per-cycle
# would spend real money on one PATCH, so both ends are clamped here rather
# than trusted from the request body.
_INT_BOUNDS: dict[str, tuple[int, int]] = {
    KEY_INGEST_INTERVAL_MINUTES: (1, 24 * 60),
    KEY_INGEST_QUERIES_PER_CYCLE: (1, 9),
    KEY_INGEST_MAX_STORIES_PER_QUERY: (1, 20),
    KEY_RESCORE_INTERVAL_MINUTES: (1, 24 * 60),
}

MAX_PROMPT_LENGTH = 400
MAX_LABEL_LENGTH = 60
MAX_KEY_LENGTH = 40

# The cache carries the database it was read from. Tests point the process at
# a fresh temporary file per case, so a cache that remembered only the values
# would hand one test the overrides another test wrote.
_cache: tuple[str, dict[str, Any]] | None = None
_cache_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def clear_cache() -> None:
    """Drop the decoded overrides so the next read goes to the database."""
    global _cache
    with _cache_lock:
        _cache = None


def overrides() -> dict[str, Any]:
    """Every stored override, decoded, keyed by setting name.

    A row that does not decode as JSON is skipped rather than raising: one bad
    row must never take the scheduler or the admin screens down.
    """
    global _cache
    path = str(get_db_path())
    with _cache_lock:
        if _cache is not None and _cache[0] == path:
            return dict(_cache[1])
    stored = repo.all_app_settings()
    decoded: dict[str, Any] = {}
    for name, raw in stored.items():
        if name not in OVERRIDABLE_KEYS:
            continue
        try:
            decoded[name] = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("app_settings row %s is not valid JSON, ignoring it", name)
    with _cache_lock:
        _cache = (path, decoded)
    return dict(decoded)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def effective(name: str, default: Any = None) -> Any:
    """The value in force right now: app_settings, else .env, else default.

    This is what the scheduler and the admin screens read. It never raises on
    an unknown name so a caller can ask for anything and get the default back.
    """
    stored = overrides()
    if name in stored:
        return _coerce(name, stored[name], fallback=default)
    settings = get_settings()
    if hasattr(settings, name):
        return getattr(settings, name)
    return default


def pipeline_settings() -> dict[str, Any]:
    """The six overridable settings, shaped for models.PipelineSettings.

    query_set comes back as the list of enabled query keys, which is the shape
    the admin API declares, while the database row behind it holds the full
    definitions.
    """
    settings = get_settings()
    return {
        KEY_INGEST_ENABLED: bool(
            effective(KEY_INGEST_ENABLED, settings.ingest_enabled)
        ),
        KEY_INGEST_INTERVAL_MINUTES: int(
            effective(KEY_INGEST_INTERVAL_MINUTES, settings.ingest_interval_minutes)
        ),
        KEY_INGEST_QUERIES_PER_CYCLE: int(
            effective(KEY_INGEST_QUERIES_PER_CYCLE, settings.ingest_queries_per_cycle)
        ),
        KEY_INGEST_MAX_STORIES_PER_QUERY: int(
            effective(
                KEY_INGEST_MAX_STORIES_PER_QUERY,
                settings.ingest_max_stories_per_query,
            )
        ),
        KEY_RESCORE_INTERVAL_MINUTES: int(
            effective(KEY_RESCORE_INTERVAL_MINUTES, settings.rescore_interval_minutes)
        ),
        KEY_QUERY_SET: enabled_query_keys(),
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def set_setting(name: str, value: Any, actor: str | None = None) -> Any:
    """Store one override and invalidate the cache. Returns the stored value.

    Raises KeyError for a name outside OVERRIDABLE_KEYS. That is the guard that
    keeps a secret out of the database: there is no path from an HTTP body to
    an app_settings row this function will not check first.
    """
    if name not in OVERRIDABLE_KEYS:
        raise KeyError(f"{name} is not an overridable setting")
    coerced = _coerce(name, value)
    repo.set_app_setting(name, json.dumps(coerced), actor=actor)
    clear_cache()
    return coerced


def apply_patch(patch: Mapping[str, Any], actor: str | None = None) -> dict[str, Any]:
    """Store every present override from a patch body. Returns what changed.

    A None value means the field was absent from the request, so it is skipped
    rather than written as null. query_set is a list of keys to enable, and is
    applied to the stored definitions rather than replacing them.
    """
    applied: dict[str, Any] = {}
    for name in OVERRIDABLE_KEYS:
        if name not in patch:
            continue
        value = patch[name]
        if value is None:
            continue
        if name == KEY_QUERY_SET:
            applied[name] = set_enabled_query_keys(value, actor=actor)
            continue
        applied[name] = set_setting(name, value, actor=actor)
    return applied


# ---------------------------------------------------------------------------
# The query set
# ---------------------------------------------------------------------------


def default_query_definitions() -> list[dict[str, Any]]:
    """The nine hardcoded queries, every one enabled.

    Imported lazily so app.pipeline.queries can read this module back without
    an import cycle.
    """
    from app.pipeline import queries as queries_module

    return [
        {
            "key": entry["key"],
            "label": entry.get("label", entry["key"]),
            "prompt": entry.get("prompt", ""),
            "category_hint": entry.get("category_hint"),
            "enabled": True,
        }
        for entry in queries_module.QUERIES
    ]


def query_definitions() -> list[dict[str, Any]]:
    """The query set in force: the stored one when present, else the default."""
    stored = overrides().get(KEY_QUERY_SET)
    cleaned = _clean_definitions(stored)
    return cleaned if cleaned else default_query_definitions()


def set_query_definitions(
    definitions: Iterable[Any], actor: str | None = None
) -> list[dict[str, Any]]:
    """Replace the whole query set. Returns what was stored.

    An empty or unusable payload is refused rather than silently stored,
    because a query set of nothing would leave the pipeline with no way back
    from the admin screen that emptied it.
    """
    cleaned = _clean_definitions(definitions)
    if not cleaned:
        raise ValueError("the query set must hold at least one usable query")
    repo.set_app_setting(KEY_QUERY_SET, json.dumps(cleaned), actor=actor)
    clear_cache()
    return cleaned


def enabled_query_keys() -> list[str]:
    """The keys of every enabled query, in rotation order."""
    return [entry["key"] for entry in query_definitions() if entry.get("enabled", True)]


def set_enabled_query_keys(
    keys: Iterable[Any], actor: str | None = None
) -> list[str]:
    """Turn exactly these query keys on and every other one off.

    The definitions themselves are left alone, so a prompt an admin wrote
    survives being switched off and on again.
    """
    wanted = {
        str(key).strip().lower() for key in keys or () if str(key).strip()
    }
    definitions = [dict(entry) for entry in query_definitions()]
    for entry in definitions:
        entry["enabled"] = entry["key"] in wanted
    repo.set_app_setting(KEY_QUERY_SET, json.dumps(definitions), actor=actor)
    clear_cache()
    return [entry["key"] for entry in definitions if entry["enabled"]]


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------


def _coerce(name: str, value: Any, fallback: Any = None) -> Any:
    """Force a stored or submitted value into the shape the setting expects."""
    if name in _BOOL_KEYS:
        return _as_bool(value)
    if name in _INT_KEYS:
        low, high = _INT_BOUNDS[name]
        return max(low, min(high, _as_int(value, low)))
    if name == KEY_QUERY_SET:
        cleaned = _clean_definitions(value)
        return cleaned if cleaned else (fallback or default_query_definitions())
    return value


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_definitions(value: Any) -> list[dict[str, Any]]:
    """Normalize a query set payload, dropping anything unusable.

    Accepts the full definition dicts and also a bare list of keys, which is
    what the pipeline PATCH body carries, so both callers land on the same
    stored shape.
    """
    if not isinstance(value, (list, tuple)):
        return []
    if value and all(isinstance(entry, str) for entry in value):
        return _definitions_from_keys(value)

    known = {entry["key"]: entry for entry in default_query_definitions()}
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        key = str(entry.get("key") or "").strip().lower()[:MAX_KEY_LENGTH]
        if not key or key in seen:
            continue
        fallback = known.get(key, {})
        label = str(entry.get("label") or fallback.get("label") or key).strip()
        prompt = str(entry.get("prompt") or fallback.get("prompt") or "").strip()
        if not prompt:
            continue
        hint = entry.get("category_hint", fallback.get("category_hint"))
        hint_text = str(hint).strip().lower() if hint else ""
        seen.add(key)
        cleaned.append(
            {
                "key": key,
                "label": label[:MAX_LABEL_LENGTH] or key,
                "prompt": prompt[:MAX_PROMPT_LENGTH],
                "category_hint": hint_text if hint_text in CATEGORY_KEYS else None,
                "enabled": _as_bool(entry.get("enabled", True)),
            }
        )
    return cleaned


def _definitions_from_keys(keys: Iterable[Any]) -> list[dict[str, Any]]:
    """Turn a bare list of keys into definitions with those keys enabled."""
    wanted = {str(key).strip().lower() for key in keys if str(key).strip()}
    definitions = default_query_definitions()
    for entry in definitions:
        entry["enabled"] = entry["key"] in wanted
    return definitions


__all__ = [
    "KEY_INGEST_ENABLED",
    "KEY_INGEST_INTERVAL_MINUTES",
    "KEY_INGEST_MAX_STORIES_PER_QUERY",
    "KEY_INGEST_QUERIES_PER_CYCLE",
    "KEY_QUERY_SET",
    "KEY_RESCORE_INTERVAL_MINUTES",
    "OVERRIDABLE_KEYS",
    "apply_patch",
    "clear_cache",
    "default_query_definitions",
    "effective",
    "enabled_query_keys",
    "overrides",
    "pipeline_settings",
    "query_definitions",
    "set_enabled_query_keys",
    "set_query_definitions",
    "set_setting",
]
