"""Inspect CSR compatibility without changing the declared logical graph."""

from array import array
from pathlib import Path
import sys


def duplicate_edges(directory):
    def words(name):
        result = array("I")
        result.frombytes((Path(directory) / name).read_bytes())
        if sys.byteorder != "little":
            result.byteswap()
        return result

    offsets = words("csr_offsets.u32le")
    destinations = words("csr_destinations.u32le")
    if not offsets or offsets[0] != 0 or offsets[-1] != len(destinations):
        raise ValueError("CSR endpoint mismatch")
    duplicates = 0
    for start, end in zip(offsets, offsets[1:]):
        if end < start or end > len(destinations):
            raise ValueError("invalid CSR row bounds")
        row = destinations[start:end]
        duplicates += len(row) - len(set(row))
    return duplicates
