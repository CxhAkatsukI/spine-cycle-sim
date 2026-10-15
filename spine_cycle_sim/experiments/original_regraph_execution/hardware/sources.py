"""Identify the reviewed author host without modifying its measurement logic."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.sources import verify_snapshot

REVISION = "365456826cef495285383d939907f847e05ad74b"

# These are literal review anchors at one clean revision, not a C++ parser.
ANCHORS = (
    ("apply_divisor_upload", "host/preprocess/partition_schedule.cpp",
     "partition_container.apply_src_prop_ptr.obj = partition_container.vertex_property.data();"),
    ("apply_divisor_argument", "host/host.cpp",
     "acc.apply_krnl.setArg(argvi++, partition_container.apply_src_prop_dev)"),
    ("host_verification_divisor", "host/verification/verify.cpp",
     "applyFunc((prop_t)dst_tmp_prop_verfication_e2e[i], (prop_t)partition_container.vertex_property[i], (prop_t)partition_container.vertex_property[i], 0)"),
    ("wall_clock_start", "host/host.cpp",
     "auto kernel_start = std::chrono::high_resolution_clock::now();"),
    ("last_task_enqueue", "host/host.cpp",
     "acc.big_gs_queue[krnl_id - LITTLE_KERNEL_NUM].enqueueTask"),
    ("verification_result_ignored", "host/host.cpp",
     "verifyResults(partition_container, acc, csr);"),
    ("verification_unconditional_return", "host/verification/verify.cpp", "return 1;"),
    ("device_iteration", "host/acc_setup/acc_setup.cpp",
     "for (unsigned int i = 0; i < devices.size(); i++)"),
    ("one_superstep", "host/host.cpp", "int num_super_step = 1;"),
    ("device_divisor_interface", "acc_template/kernel_apply/kernel_apply.cpp",
     "ap_uint<512>                    *outdegree,"),
    ("pr_signed_type", "acc_udfs/pr/l2.h", "#define prop_t int"),
)


def review(source: Path, pin: dict) -> dict:
    if pin["revision"] != REVISION:
        raise ValueError("author-host findings require the explicitly reviewed ReGraph revision")
    snapshot = verify_snapshot(source, pin)
    anchors, identities = {}, {}
    for name, relative, needle in ANCHORS:
        path = source / relative
        text = path.read_text()
        if text.count(needle) != 1:
            raise ValueError("reviewed author-host anchor changed: " + name)
        offset = text.index(needle)
        anchors[name] = {"path": relative, "line": text[:offset].count("\n") + 1,
                         "literal": needle, "byte_offset": offset}
        identities[relative] = {"path": str(path.resolve()), "sha256": sha256_file(path)}
    if anchors["wall_clock_start"]["byte_offset"] <= anchors["last_task_enqueue"]["byte_offset"]:
        raise ValueError("reviewed wall-clock observation no longer applies")
    return {"snapshot": snapshot, "anchors": anchors,
            "identities": list(identities.values()),
            "apply_divisor": "initial_vertex_property_not_csr_outdegree",
            "iterations": "one_static_PR_superstep_not_convergence",
            "wall_time": "starts_after_all_task_enqueues",
            "failure_status": "verification_return_is_ignored_and_verifier_returns_one",
            "board_selection": "tries_available_devices_not_one_exclusively_leased_BDF",
            "device_source_modified": False}
