"""IDs (LLD-0 §3.5, L0-8). Every primary key is made in Python, never by the database,
so a retried request reuses the same ID through its idempotency record.

uuid7 (RFC 9562): 48 bits of Unix milliseconds, then random bits, so IDs sort by
creation time and index well. Python's own uuid.uuid7 arrives only in 3.14.

Within one process the IDs are also strictly increasing, even inside one millisecond (RFC 9562 section 6.2, "increment the
random part"): rows written in one transaction share a timestamp, and the lists that sort by `(time, id)` rely on the id
to put them in the order they were made. Across processes the order inside one millisecond is still arbitrary.
"""

import secrets
import threading
import time
import uuid

_RANDOM_BITS = 74  # 12 bits after the version nibble and 62 after the variant bits
_lock = threading.Lock()
_last: tuple[int, int] = (0, 0)  # (milliseconds, random part) of the last ID made


def uuid7() -> uuid.UUID:
    global _last
    ms = time.time_ns() // 1_000_000
    with _lock:
        last_ms, last_random = _last
        if ms > last_ms:
            random = secrets.randbits(_RANDOM_BITS)
        else:  # the same millisecond, or the clock stepped back: keep counting up from the last ID
            ms = last_ms
            random = last_random + 1
            if random >> _RANDOM_BITS:  # the random part is used up: move to the next millisecond
                ms, random = ms + 1, 0
        _last = (ms, random)
    rand_a, rand_b = random >> 62, random & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0x2 << 62 | rand_b
    return uuid.UUID(int=value)
