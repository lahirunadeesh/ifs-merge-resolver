"""License validation — runs inside the distributed app."""
from __future__ import annotations
import json
import os
from pathlib import Path

from licensing.key_gen import verify_key
from licensing.machine_id import get_machine_id

_LICENSE_FILE = Path.home() / ".ifs_merge_license.json"


def load_stored_license() -> dict | None:
    try:
        return json.loads(_LICENSE_FILE.read_text())
    except Exception:
        return None


def save_license(device_id: str, license_key: str) -> None:
    _LICENSE_FILE.write_text(json.dumps({
        "device_id": device_id,
        "license_key": license_key,
    }))


def is_licensed() -> bool:
    """Return True if a valid license is stored for this machine."""
    data = load_stored_license()
    if not data:
        return False
    device_id = get_machine_id()
    # Must match both the stored device_id and this machine's fingerprint
    if data.get("device_id") != device_id:
        return False
    return verify_key(device_id, data.get("license_key", ""))


def activate(license_key: str) -> tuple[bool, str]:
    """
    Try to activate with the given key.
    Returns (success, message).
    """
    device_id = get_machine_id()
    if verify_key(device_id, license_key):
        save_license(device_id, license_key)
        return True, "License activated successfully."
    return False, "Invalid license key for this machine."
