"""Exact field-wise original search-memory and dispatch packet admission."""

import struct

from .layout import EMPTY, locate, route


def verify(payload: bytes, binary, offsets, updates):
    if len(payload) % 4 or not 16 <= len(payload) <= 64 * 1024**2: raise ValueError("G host protocol extent")
    magic, version, count, requests = struct.unpack_from("<4I", payload)
    if (magic, version, count) != (0x47485031, 1, len(updates)) or len(payload) != 16 + 24 * (count + requests):
        raise ValueError("G host protocol header/extent")
    position = 16

    def consume(expected, diagnostic):
        nonlocal position
        if position + 24 > len(payload) or struct.unpack_from("<6I", payload, position) != expected: raise ValueError(diagnostic)
        position += 24

    for edge in updates:
        segment = locate(binary, offsets, edge)
        consume((edge & 0xffffffff, edge >> 32, segment * 16, edge & 0xffffffff, edge >> 32, route(segment)), "G host packet mismatch")
    observed = 0
    for kernel in range(4):
        for lane in range(64):
            for i in range(kernel + lane * 4, len(updates), 256):
                edge = updates[i] & (EMPTY - 1); source = edge >> 32
                value = (offsets[source] << 32) | offsets[source + 1]
                consume((kernel, lane, 0, source, value & 0xffffffff, value >> 32), "G host offset request mismatch"); observed += 1
                begin, end = offsets[source] // 16, offsets[source + 1] // 16
                while (mid := (begin + end) // 2) != begin:
                    value = binary[mid]
                    consume((kernel, lane, 1, mid, value & 0xffffffff, value >> 32), "G host binary request mismatch"); observed += 1
                    if value <= edge: begin = mid
                    else: end = mid
    if requests != observed or position != len(payload): raise ValueError("G host protocol trailing requests")
    return observed
