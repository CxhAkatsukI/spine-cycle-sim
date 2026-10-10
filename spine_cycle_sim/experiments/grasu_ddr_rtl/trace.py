"""Check every AXI request/service/response without inferring board timing."""

from collections import deque
import re

from .fixtures import encode, updates


def validate(stdout, result, case, contract):
    pending = {(operation, port): deque() for operation in ("AR", "AW", "W", "RACK", "BACK") for port in range(4)}
    events, inputs = [], []
    outstanding, hazards = {}, 0
    previous_cycle, previous_service = 0, -1
    for line in stdout.splitlines():
        if line.startswith("DDR_INPUT "):
            match = re.fullmatch(r"DDR_INPUT cycle=(\d+) data=([0-9a-f]{24})", line)
            if not match:
                raise ValueError("malformed DDR input trace")
            inputs.append({"cycle": int(match[1]), "packet": int(match[2], 16)})
            continue
        if not line.startswith("DDR_") or line.startswith("DDR_RTL_RESULT "):
            continue
        match = re.fullmatch(r"DDR_(AR|AW|W|READ|WRITE|RACK|BACK) cycle=(\d+) port=(\d+)(?: line=(\d+))?", line)
        if not match:
            raise ValueError("malformed DDR memory trace")
        operation, cycle, port, index = match.groups()
        cycle, port = int(cycle), int(port)
        index = None if index is None else int(index)
        read = operation in ("AR", "READ", "RACK")
        if (not result["start_cycle"] <= cycle <= result["drained_cycle"] or cycle < previous_cycle or
                not 0 <= port < 4 or read != (port < 2) or
                (operation == "W" and index is not None) or
                (operation != "W" and (index is None or not 0 <= index < contract["memory_lines"] or port % 2 != index % 2))):
            raise ValueError("DDR memory trace port/order/extent differs")
        previous_cycle = cycle
        event = {"operation": operation, "cycle": cycle, "port": port, "line": index}
        if operation in ("AR", "AW", "W"):
            pending[operation, port].append(event)
            if len(pending[operation, port]) > contract["queue_depth_per_port"]:
                raise ValueError("DDR request queue exceeds finite capacity")
        elif operation in ("READ", "WRITE"):
            if cycle <= previous_service:
                raise ValueError("DDR shared bus serviced more than one beat per cycle")
            previous_service = cycle
            request = pending["AR" if read else "AW", port]
            if not request:
                raise ValueError("DDR service has no preceding address")
            address = request.popleft()
            if address["line"] != index or cycle < address["cycle"] + case["latency"]:
                raise ValueError("DDR FIFO address order or minimum latency differs")
            if not read:
                data = pending["W", port]
                if not data or cycle < data.popleft()["cycle"] + case["latency"]:
                    raise ValueError("DDR write data/pairing latency differs")
            response = pending["RACK" if read else "BACK", port]
            if response:
                raise ValueError("DDR service overwrote a held response")
            response.append(event)
            if read:
                hazards += outstanding.get(index, 0) > 0
                outstanding[index] = outstanding.get(index, 0) + 1
            else:
                if not outstanding.get(index, 0):
                    raise ValueError("DDR write without preceding read")
                outstanding[index] -= 1
        else:
            response = pending[operation, port]
            if not response:
                raise ValueError("DDR acknowledgment has no response")
            service = response.popleft()
            if service["line"] != index or cycle <= service["cycle"]:
                raise ValueError("DDR acknowledgment order differs")
        events.append(event)
    packets = [encode(item) for item in updates(case["sequence"])] + [(1 << 64) - 1]
    if ([item["packet"] for item in inputs] != packets or any(pending.values()) or any(outstanding.values()) or
            any(not result["start_cycle"] <= item["cycle"] <= result["done_cycle"] for item in inputs) or
            any(right["cycle"] <= left["cycle"] for left, right in zip(inputs, inputs[1:])) or
            any(right["cycle"] - left["cycle"] < case["input_gap"] + 1
                for left, right in zip(inputs[:-2], inputs[1:-1]))):
        raise ValueError("DDR input/pacing or complete transaction sequence differs")
    for operation in ("AR", "AW", "W", "READ", "WRITE", "RACK", "BACK"):
        if sum(event["operation"] == operation for event in events) != len(packets) - 1:
            raise ValueError("DDR raw memory trace incomplete")
    return events, inputs, hazards
