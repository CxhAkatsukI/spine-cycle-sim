"""Host-memory lifecycle helpers for large execution-driven runs."""

from __future__ import annotations

import ctypes
import gc


def release_process_heap() -> bool:
    """Collect Python objects and return free glibc arenas to the operating system."""

    gc.collect()
    try:
        trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return False
    trim.argtypes = (ctypes.c_size_t,)
    trim.restype = ctypes.c_int
    return bool(trim(0))
