"""Optimizer search settings and room priority config persistence."""
from typing import Optional

from save_parser import ROOM_KEYS

from mewgenics.utils.config import (
    _load_app_config, _save_app_config, _coerce_int, _coerce_float,
    _set_optimizer_flag,
)
from mewgenics.utils.planner_state import (
    _load_planner_state_value, _save_planner_state_value,
    ROOM_OPTIMIZER_MODES,
)


_OPTIMIZER_SEARCH_SETTINGS_KEY = "optimizer_search_settings"
_ROOM_CONFIG_VERSION = 4  # bump to force all users back to defaults
_OPTIMIZER_SEARCH_DEFAULTS = {
    "temperature": 8.0,
    "neighbors": 120,
}


def _normalize_optimizer_search_settings(data: dict | None) -> dict:
    data = data if isinstance(data, dict) else {}
    return {
        "temperature": _coerce_float(
            data.get("temperature"),
            _OPTIMIZER_SEARCH_DEFAULTS["temperature"],
            min_value=0.0,
        ),
        "neighbors": _coerce_int(
            data.get("neighbors"),
            _OPTIMIZER_SEARCH_DEFAULTS["neighbors"],
            min_value=1,
        ),
    }


def _load_optimizer_search_settings() -> dict:
    data = _load_app_config()
    return _normalize_optimizer_search_settings(data.get(_OPTIMIZER_SEARCH_SETTINGS_KEY))


def _save_optimizer_search_settings(settings: dict) -> bool:
    normalized = _normalize_optimizer_search_settings(settings)
    data = _load_app_config()
    data[_OPTIMIZER_SEARCH_SETTINGS_KEY] = normalized
    _save_app_config(data)
    return True


def _saved_optimizer_search_temperature(default: float | None = None) -> float:
    settings = _load_optimizer_search_settings()
    fallback = _OPTIMIZER_SEARCH_DEFAULTS["temperature"] if default is None else default
    return float(settings.get("temperature", fallback))


def _saved_optimizer_search_neighbors(default: int | None = None) -> int:
    settings = _load_optimizer_search_settings()
    fallback = _OPTIMIZER_SEARCH_DEFAULTS["neighbors"] if default is None else default
    return int(settings.get("neighbors", fallback))


# ── Room priority config ─────────────────────────────────────────────────────

DEFAULT_MIN_COMFORT = 10
"""Comfort level breeding rooms are sized to keep (see RoomPriorityPanel)."""


def _default_room_priority_config() -> list[dict]:
    """Default room priority: all rooms as Best Pairs, last one as Fallback.

    Breeding rooms default to a Comfort floor of 10 rather than a headcount:
    Comfort drives the overnight fight roll, so sizing rooms by the Comfort
    they should keep beats guessing a capacity. Fallback rooms absorb the
    overflow and are not Comfort-limited.
    """
    keys = list(ROOM_KEYS)
    return [
        {
            "room": k,
            "type": "best_pairs" if i < len(keys) - 1 else "fallback",
            "min_comfort": DEFAULT_MIN_COMFORT if i < len(keys) - 1 else None,
        }
        for i, k in enumerate(keys)
    ]


def _normalize_room_priority_config(config: list[dict]) -> tuple[list[dict], bool]:
    """Normalize room priority config and migrate legacy default capacities."""
    normalized: list[dict] = []
    seen_rooms: set[str] = set()
    for slot in config or []:
        if not isinstance(slot, dict):
            continue
        room = slot.get("room")
        slot_type = str(slot.get("type", "best_pairs") or "best_pairs").strip().lower()
        if slot_type == "breeding":
            slot_type = "best_pairs"
        if room not in ROOM_KEYS or slot_type not in ROOM_OPTIMIZER_MODES:
            continue
        if room in seen_rooms:
            continue  # deduplicate — keep first occurrence only
        seen_rooms.add(room)
        entry = {
            "room": room,
            "type": slot_type,
            "base_stim": slot.get("base_stim", slot.get("stimulation")),
        }
        # Rooms are sized by the Comfort they should keep. Legacy configs
        # instead carried an explicit capacity; keep that key so nothing is
        # silently discarded, but Min Comfort takes precedence when present.
        if "min_comfort" in slot:
            entry["min_comfort"] = slot.get("min_comfort")
        else:
            entry["max_cats"] = slot.get("max_cats", slot.get("capacity"))
        normalized.append(entry)

    migrated = False
    for slot in normalized:
        if slot["type"] == "fallback":
            continue
        if "min_comfort" in slot:
            if slot.get("min_comfort") in (None, ""):
                slot["min_comfort"] = DEFAULT_MIN_COMFORT
                migrated = True
        elif slot.get("max_cats") in (None, ""):
            # Legacy slot with no capacity at all — adopt the Comfort floor
            # rather than inventing a headcount.
            slot.pop("max_cats", None)
            slot["min_comfort"] = DEFAULT_MIN_COMFORT
            migrated = True

    default_order = list(ROOM_KEYS)
    default_like = (
        len(normalized) == len(default_order)
        and [slot["room"] for slot in normalized] == default_order
        and all(slot["type"] == ("best_pairs" if idx < len(default_order) - 1 else "fallback") for idx, slot in enumerate(normalized))
        and all(
            slot.get("max_cats") in (None, "", 0) and "min_comfort" not in slot
            for slot in normalized
        )
    )
    if default_like:
        for slot in normalized:
            slot.pop("max_cats", None)
            if slot["type"] != "fallback":
                if slot.get("min_comfort") != DEFAULT_MIN_COMFORT:
                    slot["min_comfort"] = DEFAULT_MIN_COMFORT
                    migrated = True
            elif slot.get("min_comfort") is not None:
                slot["min_comfort"] = None
                migrated = True
    return normalized, migrated


def _load_room_priority_config(save_path: Optional[str] = None) -> list[dict]:
    # No save bound yet (panel init happens before a save is selected):
    # read the global default from app config WITHOUT running the version
    # check or writing anything. Running the version-reset path here would
    # stamp defaults into settings.json and, via the mirror-write on save,
    # clobber the user's real per-save room priority. The real load +
    # version check happens when set_save_path() is called with a valid
    # path, at which point the sidecar is the source of truth.
    if not save_path:
        try:
            cfg = _load_planner_state_value("room_priority_config", [], save_path=None)
            if isinstance(cfg, list) and cfg:
                valid, _ = _normalize_room_priority_config(cfg)
                if valid:
                    return valid
        except Exception:
            pass
        return _default_room_priority_config()
    try:
        stored_version = _load_planner_state_value(
            "room_priority_config_version", 0, save_path=save_path,
        )
        if stored_version != _ROOM_CONFIG_VERSION:
            # Version mismatch — reset to defaults and stamp new version
            defaults = _default_room_priority_config()
            _save_planner_state_value("room_priority_config", defaults, save_path=save_path)
            _save_planner_state_value("room_priority_config_version", _ROOM_CONFIG_VERSION, save_path=save_path)
            # Also reset SA/"More Depth" flags to off
            _set_optimizer_flag("use_sa", False)
            _set_optimizer_flag("perfect_planner_use_sa", False)
            return defaults
        cfg = _load_planner_state_value("room_priority_config", [], save_path=save_path)
        if isinstance(cfg, list) and cfg:
            valid, migrated = _normalize_room_priority_config(cfg)
            if valid:
                if migrated:
                    _save_planner_state_value("room_priority_config", valid, save_path=save_path)
                return valid
    except Exception:
        pass
    return _default_room_priority_config()


def _save_room_priority_config(config: list[dict], save_path: Optional[str] = None):
    try:
        cleaned: list[dict] = []
        seen_rooms: set[str] = set()
        for slot in config or []:
            if not isinstance(slot, dict):
                continue
            room = slot.get("room")
            slot_type = str(slot.get("type", "best_pairs") or "best_pairs").strip().lower()
            if slot_type == "breeding":
                slot_type = "best_pairs"
            if room not in ROOM_KEYS or slot_type not in ROOM_OPTIMIZER_MODES:
                continue
            if room in seen_rooms:
                continue  # deduplicate
            seen_rooms.add(room)
            entry = {
                "room": room,
                "type": slot_type,
                "base_stim": slot.get("base_stim", slot.get("stimulation")),
            }
            # Rooms are sized by Min Comfort; only fall back to the legacy
            # explicit capacity for configs that predate it.
            if "min_comfort" in slot:
                entry["min_comfort"] = slot.get("min_comfort")
            else:
                entry["max_cats"] = slot.get("max_cats", slot.get("capacity"))
            cleaned.append(entry)
        _save_planner_state_value("room_priority_config", cleaned, save_path=save_path)
        _save_planner_state_value("room_priority_config_version", _ROOM_CONFIG_VERSION, save_path=save_path)
    except Exception:
        pass
