"""Persistent key/value settings store for IFS Merge Resolver."""
from __future__ import annotations
import json
from pathlib import Path

STORE_PATH = Path.home() / ".ifs_merge_settings.json"


def _load() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_setting(key: str, default=None):
    return _load().get(key, default)


def set_setting(key: str, value) -> None:
    data = _load()
    data[key] = value
    _save(data)
