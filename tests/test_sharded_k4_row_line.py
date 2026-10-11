"""Whole-line reads require exact production flags and conserved PMA work."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.validation import (
    BASE_FLAGS, FLAGS, compare_traffic, require_functional, require_xos,
)
from spine_cycle_sim.experiments.sharded_k4_stages.adapter_axi.analysis import ROW_BASE, TRIALS


def functional_log():
    return "\n".join("ROW_PREFETCH_EQUIVALENCE status=PASS cases=254 packets=1482 "
                      + suffix for suffix in ("skip_empty=0", "skip_empty=1",
                                              "skip_empty=1 row_line=1") for _ in range(3))


def traffic():
    rows = []
    for trial, (vertices, placement, length, latency, stall) in enumerate(TRIALS):
        sources = [src for src in range(vertices) if placement == 0
                   or placement == 1 and src + 1 == vertices
                   or placement == 2 and src == 0 or placement == 3 and src % 7 == 0]
        lines = [(vertices - 1) // 8, *range(sources[-1] // 8 + 1)] if vertices else []
        rows.append(dict(trial=trial, vertices=vertices, placement=placement, length=length,
                         latency=latency, stall=stall, packets=len(sources)*length*2,
                         pma_requests=len(sources)*length, pma_beats=len(sources)*length,
                         pma_transfer_bytes=len(sources)*length*64, cycles=100,
                         row_requests=len(lines), row_transfer_bytes=len(lines)*64,
                         requests=[dict(address=ROW_BASE+line*64, beats=1, size=64) for line in lines]))
    return rows


def xo(path: Path, flags: dict, offset="0x40"):
    options = " ".join(f"-D{key}={value}" for key, value in flags.items())
    xml = ('<root><kernel name="pma_to_regraph_adapter" hwControlProtocol="ap_ctrl_chain" '
           f'compileOptions="{options}"><ports/><args><arg name="row_offset" '
           f'type="void*" offset="{offset}"/></args></kernel></root>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("adapter/kernel.xml", xml)


class RowLineTests(unittest.TestCase):
    def test_all_functional_formats_required(self):
        require_functional(functional_log())
        for changed in (functional_log().replace("row_line=1", "row_line=0", 1),
                        functional_log().replace("packets=1482", "packets=1481", 1),
                        functional_log() + "\n" + functional_log().splitlines()[0]):
            with self.assertRaises(ValueError):
                require_functional(changed)

    def test_exact_external_ABI_without_C_type_assumption(self):
        with tempfile.TemporaryDirectory() as temporary:
            before, after = Path(temporary)/"old.xo", Path(temporary)/"new.xo"
            xo(before, BASE_FLAGS)
            xo(after, FLAGS)
            contract = require_xos(before, after)
            self.assertIn("padded", contract["row_memory_contract"])
            xo(after, FLAGS, "0x48")
            with self.assertRaises(ValueError):
                require_xos(before, after)

    def test_test_depth_or_missing_mode_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            before, after = Path(temporary)/"old.xo", Path(temporary)/"new.xo"
            xo(before, BASE_FLAGS)
            for changed in (BASE_FLAGS, FLAGS | {"GRASU_REGRAPH_COSIM_DEPTH": "1"},
                            FLAGS | {"GRASU_REGRAPH_ROW_LINE_READ": "0"}):
                xo(after, changed)
                with self.assertRaises(ValueError):
                    require_xos(before, after)

    def test_extent_read_is_charged_separately(self):
        result = compare_traffic(traffic(), traffic())
        self.assertEqual(result[4]["candidate_row_requests"], 4)
        self.assertEqual(result[9]["candidate_row_requests"], 2)
        self.assertEqual(result[0]["candidate_row_requests"], 0)

    def test_partial_last_block_is_charged_as_whole_line(self):
        self.assertEqual(compare_traffic(traffic(), traffic())[3]["candidate_row_bytes"], 192)

    def test_duplicate_narrow_or_missing_row_fetch_rejected(self):
        for kind in ("duplicate", "narrow", "missing", "address", "burst"):
            rows = traffic()
            if kind == "duplicate":
                rows[2]["requests"].append(rows[2]["requests"][-1])
            elif kind == "narrow":
                rows[2]["requests"][1]["size"] = 8
            elif kind == "missing":
                rows[2]["requests"].pop()
            elif kind == "address":
                rows[2]["requests"][1]["address"] += 64
            else:
                rows[2]["requests"][1]["beats"] = 2
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                compare_traffic(traffic(), rows)

    def test_algorithm_work_cannot_change(self):
        for key in ("packets", "pma_requests", "pma_beats", "pma_transfer_bytes", "latency"):
            rows = deepcopy(traffic())
            rows[4][key] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare_traffic(traffic(), rows)

    def test_no_fitted_cycle_acceptance_threshold(self):
        rows = traffic()
        for row in rows:
            row["cycles"] *= 1000
        self.assertEqual(compare_traffic(traffic(), rows)[4]["candidate_cycles"], 100000)


if __name__ == "__main__":
    unittest.main()
