"""External AXI conservation and immutable production-RTL package gates."""

from pathlib import Path
import tempfile
import unittest
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.analysis import (
    AR, CASE, CONFIG, R, ROW_BASE, TRIALS, parse_trace,
)
from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.study import (
    RTL_PREFIX, extract_rtl, require_execution, require_route_reference,
)


def transcript() -> str:
    lines = []
    for trial, config in enumerate(TRIALS):
        case = dict(zip(CONFIG, config))
        count, placement, length, latency, stall = config
        occupied = sum(placement == 0 or placement == 1 and source + 1 == count
                       or placement == 2 and source == 0 or placement == 3 and source % 7 == 0
                       for source in range(count))
        start = 100 + trial * 10000
        addresses = [(ROW_BASE, 8)] if count else []
        addresses += [(0x10000 + index * 64, 64) for index in range(occupied * length)]
        for index, (address, size) in enumerate(addresses):
            issue = start + index * (latency + 3) + 1
            lines.append("AXI_AR " + " ".join(f"{key}={value}" for key, value in
                         zip(AR, (trial, issue, address, 1, size))))
            lines.append("AXI_R " + " ".join(f"{key}={value}" for key, value in
                         zip(R, (trial, issue + latency + 1, address, size, 1))))
        packets = 2 * occupied * length
        first = start + max(10, len(addresses) * (latency + 3), stall + 1)
        last = first + packets - 1
        done = last + 1 if packets else start + 10
        case.update(trial=trial, start=start, cycles=done-start, done=done,
                    row_requests=int(bool(count)), row_beats=int(bool(count)), row_transfer_bytes=8*bool(count),
                    pma_requests=occupied*length, pma_beats=occupied*length, pma_transfer_bytes=64*occupied*length,
                    packets=packets, first_packet=first if packets else -1, last_packet=last if packets else -1)
        lines.append("AXI_CASE " + " ".join(f"{key}={case[key]}" for key in CASE))
    return "\n".join(lines) + "\nADAPTER_AXI_PASS cases=12\n"


class TraceTests(unittest.TestCase):
    def test_complete_matrix_without_fitted_cycles(self):
        rows = parse_trace(transcript())
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[5]["row_transfer_bytes"], 8)
        self.assertEqual(rows[5]["maximum_outstanding"], 1)

    def test_no_missing_case_or_fatal_is_accepted(self):
        for text in (transcript().replace("ADAPTER_AXI_PASS cases=12", ""),
                     transcript() + "Fatal: payload mismatch\n",
                     transcript().replace("AXI_CASE trial=11", "WRONG trial=11")):
            with self.subTest(text=text[-60:]), self.assertRaises(ValueError):
                parse_trace(text)

    def test_configuration_and_packets_are_checked(self):
        for old, new in (("stall=1000", "stall=150"), ("packets=34", "packets=33"),
                         ("vertices=17", "vertices=18")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_trace(transcript().replace(old, new, 1))

    def test_beat_size_and_request_accounting_are_checked(self):
        for old, new in (("row_transfer_bytes=8", "row_transfer_bytes=64"),
                         ("row_beats=1", "row_beats=2"),
                         ("row_requests=1", "row_requests=2"), ("beats=1 size=8", "beats=1 size=3")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_trace(transcript().replace(old, new, 1))

    def test_response_identity_last_and_latency_are_checked(self):
        for old, new in (("AXI_R trial=1 cycle=10103", "AXI_R trial=1 cycle=10102"),
                         ("size=8 last=1", "size=8 last=0"),
                         (f"size=8 last=1", "size=64 last=1")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_trace(transcript().replace(old, new, 1))

    def test_no_unmapped_or_malformed_requests(self):
        for old, new in ((f"address={ROW_BASE}", "address=32"),
                         ("AXI_AR trial=1", "AXI_AR trial=100"),
                         ("beats=1 size=8", "beats=one size=8")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_trace(transcript().replace(old, new, 1))

    def test_no_packet_can_precede_ready(self):
        lines = transcript().splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("AXI_CASE trial=11 "))
        line = lines[index]
        start = int(line.split("start=")[1].split()[0])
        value = line.split("first_packet=")[1].split()[0]
        lines[index] = line.replace("first_packet=" + value, f"first_packet={start+999}")
        with self.assertRaisesRegex(ValueError, "sink"):
            parse_trace("\n".join(lines) + "\n")


class ExtractionTests(unittest.TestCase):
    def test_rejects_a_similar_but_unrouted_XO(self):
        pin = {"path": "/route/safe_index/adapter.xo", "sha256": "frozen"}
        route = {"command": ["v++", "--link", pin["path"]], "pins": [pin], "clock_mhz": 150}
        require_route_reference(pin, route)
        for changed in (pin | {"path": "/route/other/adapter.xo"}, pin | {"sha256": "wrong"}):
            with self.assertRaises(ValueError):
                require_route_reference(changed, route)

    def test_extracts_flat_production_rtl_and_includes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xo = root / "adapter.xo"
            with zipfile.ZipFile(xo, "w") as archive:
                archive.writestr(RTL_PREFIX + "pma_to_regraph_adapter.v", "module pma_to_regraph_adapter; endmodule")
                archive.writestr(RTL_PREFIX + "monitor.vh", "// include")
                archive.writestr("not_rtl/ignored.v", "ignored")
            directory = root / "rtl"
            directory.mkdir()
            self.assertEqual(len(extract_rtl(xo, directory)), 2)
            with self.assertRaises(FileExistsError):
                extract_rtl(xo, directory)

    def test_rejects_nested_or_missing_top(self):
        for member in (RTL_PREFIX + "../escaped.v", RTL_PREFIX + "nested/file.v", RTL_PREFIX + "other.v"):
            with self.subTest(member=member), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with zipfile.ZipFile(root / "adapter.xo", "w") as archive:
                    archive.writestr(member, "// test")
                with self.assertRaises(ValueError):
                    extract_rtl(root / "adapter.xo", root)

    def test_resource_gate_does_not_trust_exit_code_alone(self):
        record = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                  "minimum_available_bytes": 20 * 1024**3, "peak_tree_rss_kib": 1024,
                  "tree_memory_gib": 4, "reserve_gib": 16, "timeout_seconds": 120}
        require_execution(record)
        for key, value in (("exit_code", 1), ("stop_reason", "timeout"),
                           ("minimum_available_bytes", 15*1024**3), ("cleanup_snapshot_error", "failed"),
                           ("tree_memory_gib", 2), ("peak_tree_rss_kib", 5*1024**2)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_execution(record | {key: value})


if __name__ == "__main__":
    unittest.main()
