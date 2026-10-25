"""IDs (LLD-0 §3.5, L0-8). Every primary key is made in Python, never by the database,
so a retried request reuses the same ID through its idempotency record.

uuid7 (RFC 9562): 48 bits of Unix milliseconds, then random bits, so IDs sort by
creation time and index well. Python's own uuid.uuid7 arrives only in 3.14.
"""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    value = (ms & ((1 << 48) - 1)) << 80 | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 9562 variant
    return uuid.UUID(int=value)
