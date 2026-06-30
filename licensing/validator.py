"""License validation — runs inside the distributed app."""
from __future__ import annotations
import hashlib
import hmac
import json
from datetime import date, datetime
from pathlib import Path

from licensing.machine_id import get_machine_id

_SECRET      = b"c3178ad9489dda948f34deaff34b2b0a37d7461173019e995045a2e87d8f6fd4"
_TRIAL_DAYS  = 30
_LICENSE_FILE = Path.home() / ".ifs_merge_license.json"


# ── Key verification ──────────────────────────────────────────────────────────

def _sign(payload: str) -> str:
    sig = hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    raw = sig[:20].upper()
    return "-".join(raw[i:i+4] for i in range(0, 20, 4))


def _keys_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(
        a.replace("-", "").lower(),
        b.replace("-", "").lower()
    )


def is_trial_key(license_key: str) -> bool:
    return _keys_equal(_sign("TRIAL-30-DAYS"), license_key)


def is_full_key(device_id: str, license_key: str) -> bool:
    return _keys_equal(_sign(device_id.strip().upper()), license_key)


# ── License file ──────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        return json.loads(_LICENSE_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    _LICENSE_FILE.write_text(json.dumps(data))


# ── Public API ────────────────────────────────────────────────────────────────

def license_status() -> dict:
    """
    Returns a dict with keys:
      licensed: bool
      type: 'none' | 'trial' | 'full'
      days_left: int | None   (only for trial)
      expired: bool
    """
    data = _load()
    if not data:
        return {"licensed": False, "type": "none", "days_left": None, "expired": False}

    kind = data.get("type")

    if kind == "full":
        device_id = get_machine_id()
        if data.get("device_id") != device_id:
            return {"licensed": False, "type": "none", "days_left": None, "expired": False}
        if not is_full_key(device_id, data.get("license_key", "")):
            return {"licensed": False, "type": "none", "days_left": None, "expired": False}
        return {"licensed": True, "type": "full", "days_left": None, "expired": False}

    if kind == "trial":
        if not is_trial_key(data.get("license_key", "")):
            return {"licensed": False, "type": "none", "days_left": None, "expired": False}
        activated = datetime.fromisoformat(data.get("activated_at", "2000-01-01")).date()
        days_used = (date.today() - activated).days
        days_left = max(0, _TRIAL_DAYS - days_used)
        expired   = days_left == 0
        return {"licensed": not expired, "type": "trial", "days_left": days_left, "expired": expired}

    return {"licensed": False, "type": "none", "days_left": None, "expired": False}


def is_licensed() -> bool:
    return license_status()["licensed"]


def activate(license_key: str) -> tuple[bool, str, str]:
    """
    Try to activate with the given key.
    Returns (success, message, type) where type is 'trial' | 'full' | ''.
    """
    device_id = get_machine_id()

    if is_trial_key(license_key):
        existing = _load()
        # Don't reset trial if already activated
        activated_at = existing.get("activated_at") if existing.get("type") == "trial" else date.today().isoformat()
        _save({"type": "trial", "license_key": license_key, "activated_at": activated_at})
        days_used = (date.today() - date.fromisoformat(activated_at)).days
        days_left = max(0, _TRIAL_DAYS - days_used)
        return True, f"Trial activated — {days_left} days remaining.", "trial"

    if is_full_key(device_id, license_key):
        _save({"type": "full", "device_id": device_id, "license_key": license_key})
        return True, "License activated successfully.", "full"

    return False, "Invalid license key. Please check and try again.", ""
