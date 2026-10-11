"""Structured XRT parsing must preserve pairs, units and dependency evidence."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.runtime_trace import parse_vtf, trace_transfers


TRACE = """HEADER
Resolution,ms
STRUCTURE
MAPPING
1,pma_to_regraph_adapter
2,HBM[0]
EVENTS
1,0,1,1,WRITE_BUFFER,16,0x100,2,thread
2,1,2,1,WRITE_BUFFER
3,0,10,1,WRITE_BUFFER,16,0x100,2,thread
4,3,11,1,WRITE_BUFFER
5,0,11.001,2,KERNEL_ENQUEUE,1
6,5,20,2,KERNEL_ENQUEUE
DEPENDENCIES
4,5
"""


class RuntimeTraceTests(unittest.TestCase):
    def test_pairs_dependencies_and_same_bo_are_not_double_dma_proof(self):
        board = dict(result=dict(vertices="1"), events=[dict(stage="adapter", round=0, shard=0,
                      worker=0, start_ns=11001000, end_ns=20000000),
                      dict(stage="adapter", round=0, shard=1, worker=1,
                           start_ns=9000000, end_ns=21000000)])
        # Include both kernel invocations so the window begins before the transfer.
        extra = "7,0,9,2,KERNEL_ENQUEUE,1\n8,7,21,2,KERNEL_ENQUEUE\n"
        trace = parse_vtf(TRACE.replace("DEPENDENCIES", extra + "DEPENDENCIES"))
        report = trace_transfers(trace, board)
        self.assertEqual(report["compute_write_count"], 1)
        self.assertEqual(report["compute_write_bytes"], 16)
        self.assertEqual(report["writes"][0]["earlier_same_bo_write_ids"], [1])
        self.assertEqual(report["writes"][0]["dependent_kernels"][0]["shard"], 0)
        self.assertNotIn("total_dma_penalty_ms", report)

    def test_reject_unknown_units_orphans_and_duplicate_pairs(self):
        for text in (TRACE.replace("Resolution,ms", "Resolution,ns"),
                     TRACE.replace("6,5,20", "6,55,20"),
                     TRACE.replace("6,5,20", "6,5,nan"),
                     TRACE.replace("DEPENDENCIES", "9,5,21,2,KERNEL_ENQUEUE\nDEPENDENCIES"),
                     TRACE.replace("4,5\n", "4,999\n"),
                     TRACE.replace("6,5,20,2,KERNEL_ENQUEUE\n", "")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_vtf(text)


if __name__ == "__main__":
    unittest.main()
