"""Generate a stable, unique machine fingerprint."""
from __future__ import annotations
import hashlib
import platform
import uuid


def get_machine_id() -> str:
    """Return a stable 16-char hex fingerprint for this machine."""
    components = []

    # MAC address of the primary network interface
    mac = uuid.getnode()
    components.append(str(mac))

    # Platform identifiers
    components.append(platform.node())        # hostname
    components.append(platform.machine())     # architecture (x86_64, arm64)
    components.append(platform.processor())   # CPU description

    raw = "|".join(components).encode()
    digest = hashlib.sha256(raw).hexdigest()
    return digest[:16].upper()
