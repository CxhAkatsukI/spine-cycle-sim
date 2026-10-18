"""Independent one-superstep PR arithmetic; no device timing prediction."""

import array
import math
import statistics
import struct

from .. import oracle

EXACT_INTEGER = 2**24


def binary32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def csr_sums(offsets, destinations, initial, vertices):
    if (not 0 < vertices <= len(initial) or len(offsets) != vertices + 1 or offsets[0] != 0 or
            offsets[-1] != len(destinations) or any(initial[vertices:])):
        raise ValueError("complete zero-padded CSR state required")
    sums = array.array("Q", [0]) * len(initial)
    for source in range(vertices):
        if not 0 <= offsets[source] <= offsets[source + 1] <= len(destinations) or \
                not 0 <= initial[source] <= oracle.LIMIT:
            raise ValueError("nonnegative bounded CSR and signed initial values required")
        for index in range(offsets[source], offsets[source + 1]):
            destination = destinations[index]
            if not 0 <= destination < vertices:
                raise ValueError("destination outside logical graph")
            sums[destination] += initial[source]
    return sums


def compare(sums, divisors, vertices):
    if (not 0 < vertices <= len(sums) or len(sums) != len(divisors) or
            any(sums[vertices:]) or any(divisors[vertices:])):
        raise ValueError("matching complete zero-padded arithmetic domains required")
    fixed, overflow = oracle.apply(sums, divisors)
    if overflow:
        raise ValueError("signed fixed-point overflow prevents this arithmetic comparison")
    # With nonnegative integer contributions and sums <= 2^24, every partial
    # integer sum is exactly representable, independently of reduction order.
    exact_gather = max(sums, default=0) <= EXACT_INTEGER
    if not exact_gather or max(divisors, default=0) > EXACT_INTEGER:
        raise ValueError("binary32 exact integer-gather/divisor domain exceeded")
    words = array.array("I")
    relative, different, zero_changed = [], 0, 0
    max_absolute, max_rounding, max_bound, bound_failures = 0.0, 0.0, 0.0, 0
    for total, divisor, integer in zip(sums[:vertices], divisors[:vertices], fixed[:vertices]):
        ideal = (108 * total) / (128 * divisor) if divisor else 0.0
        candidate = binary32(binary32((108 / 128) * binary32(total)) / binary32(divisor)) if divisor else 0.0
        words.append(struct.unpack("<I", struct.pack("<f", candidate))[0])
        delta = abs(candidate - integer)
        different += candidate != integer
        zero_changed += integer == 0 and candidate != 0
        if integer:
            relative.append(delta / integer)
        max_absolute = max(max_absolute, delta)
        max_rounding = max(max_rounding, abs(candidate - ideal))
        # The original truncates both the damped score and reciprocal before
        # truncating the product. This bound excludes binary32 rounding.
        bound = 1 + 1 / divisor + ((108 * total) // 128) / 65536 if divisor else 0.0
        gap = ideal - integer
        bound_failures += not (-math.ulp(ideal) <= gap <= bound + math.ulp(bound))
        max_bound = max(max_bound, bound)
    if bound_failures:
        raise ValueError("independent fixed-point quantization bound failed")
    return {"vertices": vertices, "max_gather_sum": max(sums),
            "binary32_integer_gather_exact_any_order": exact_gather,
            "signed_overflow_vertices": overflow, "different_output_vertices": different,
            "fixed_zero_float_nonzero_vertices": zero_changed,
            "nonzero_fixed_vertices": len(relative),
            "median_relative_difference_nonzero_fixed": statistics.median(relative) if relative else None,
            "max_relative_difference_nonzero_fixed": max(relative, default=None),
            "max_absolute_difference": max_absolute,
            "max_binary32_difference_from_unrounded_formula": max_rounding,
            "max_original_quantization_bound": max_bound,
            "original_quantization_bound_passed": True,
            "fixed_aligned_sha256": oracle.digest(fixed),
            "float_logical_bits_sha256": oracle.digest(words),
            "numeric_outputs_equal": different == 0,
            "output_encoding_different": True}
