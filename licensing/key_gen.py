"""
License key generator — run this locally to issue keys to customers.

Setup (one-time):
  export IFS_LICENSE_SECRET="c3178ad9489dda948f34deaff34b2b0a37d7461173019e995045a2e87d8f6fd4"

Usage:
  python3 licensing/key_gen.py <device_id>
"""
from __future__ import annotations
import hashlib
import hmac
import os
import sys


def _get_secret() -> bytes:
    secret = os.environ.get("IFS_LICENSE_SECRET", "")
    if not secret:
        raise RuntimeError(
            "IFS_LICENSE_SECRET environment variable is not set.\n"
            "Export it before running: export IFS_LICENSE_SECRET=<your-secret>"
        )
    return secret.encode()


def generate_key(device_id: str) -> str:
    device_id = device_id.strip().upper()
    sig = hmac.new(_get_secret(), device_id.encode(), hashlib.sha256).hexdigest()
    raw = sig[:20].upper()
    return "-".join(raw[i:i+4] for i in range(0, 20, 4))


def verify_key(device_id: str, license_key: str) -> bool:
    expected = generate_key(device_id)
    return hmac.compare_digest(
        expected.replace("-", "").lower(),
        license_key.replace("-", "").lower()
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 licensing/key_gen.py <DEVICE_ID>")
        sys.exit(1)
    device_id = sys.argv[1]
    key = generate_key(device_id)
    print(f"\nDevice ID  : {device_id}")
    print(f"License Key: {key}\n")
