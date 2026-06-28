"""License validation — runs inside the distributed app."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
from pathlib import Path

from licensing.machine_id import get_machine_id

# Embedded secret for runtime validation inside the packaged app.
# key_gen.py (gitignored) uses the same value via env var for key generation.
_SECRET = b"c3178ad9489dda948f34deaff34b2b0a37d7461173019e995045a2e87d8f6fd4"

_LICENSE_FILE = Path.home() / ".ifs_merge_license.json"


def _verify_key(device_id: str, license_key: str) -> bool:
    device_id = device_id.strip().upper()
    sig = hmac.new(_SECRET, device_id.encode(), hashlib.sha256).hexdigest()
    raw = sig[:20].upper()
    expected = "-".join(raw[i:i+4] for i in range(0, 20, 4))
    return hmac.compare_digest(
        expected.replace("-", "").lower(),
        license_key.replace("-", "").lower()
    )


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
    data = load_stored_license()
    if not data:
        return False
    device_id = get_machine_id()
    if data.get("device_id") != device_id:
        return False
    return _verify_key(device_id, data.get("license_key", ""))


def activate(license_key: str) -> tuple[bool, str]:
    device_id = get_machine_id()
    if _verify_key(device_id, license_key):
        save_license(device_id, license_key)
        return True, "License activated successfully."
    return False, "Invalid license key for this machine."
