"""Continue a measured AU screen with a disclosed R retention miss."""

import argparse
import json
from pathlib import Path
import re

from . import active_min_admission as admission, active_min_resident as resident
from . import cc_resident_wall as wall, cc_warm_matrix, resident_matrix as matrix
from .follow import unchanged
from .runtime import identity, save


def read_au(path, digest, algorithm, gate, controls):
    pin = identity(path)
    row = json.loads(path.read_text())
    cc = algorithm == "cc"
    if (pin["sha256"] != digest or
            (row["status"], row["algorithm"], row["dataset"], row["boundary"], row["attempts"],
             row["repetitions_per_arm"], row["warmups"], row["stage_gates"], row["additional_r_gates"]) != (
                matrix.MEASURED, algorithm, "AU", wall.BOUNDARY if cc else resident.BOUNDARY,
                ["gr"] if cc else ["spine", "gr"], 1, 0, gate, controls)):
        raise ValueError("AU anchor is not the declared one-pass comparison with the same controls")
    unchanged([pin, row["comparison_log"]])
    return row, pin


def run(args):
    cc = args.algorithm == "cc"
    controls_arg = args.cc_warm_r_controls if cc else args.sssp_r_controls
    layouts = {ds: (Path(receipt).resolve(), Path(inputs).resolve()) for ds, receipt, inputs in args.layout}
    if (args.dataset != "AU" or not args.au_r_diagnostic_sha256 or controls_arg is None
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", args.child_prefix)
            or args.cc_warm_au_receipt or args.cc_warm_layout
            or not 0 <= args.wait_seconds <= 21600
            or (cc and (args.cc_wall_packet is None or args.balanced_host is None
                        or set(layouts) != set(cc_warm_matrix.DATASETS) or len(args.layout) != len(layouts)))
            or (not cc and (args.cc_wall_packet is not None or layouts or args.balanced_host))):
        raise ValueError("provide exact diagnostic controls, an AU anchor and the algorithm-specific matrix template")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "matrix.json"
    rows = {ds: {"status": "NOT_REQUESTED"} for ds in resident.DATASETS}
    report = dict(status="REPLAYING_CONTROLS", algorithm=args.algorithm, cases=rows,
                  warmups=0, repetitions_per_arm=1, r_retention_all_controls_pass=False)
    save(journal, report)
    try:
        gate = admission.admit(args.algorithm, args.route, args.host, args.r_report,
                               args.r_inputs, args.g_report, args.g_reference)
        controls, pins = resident.replay_controls(args, gate, warm_cc=cc)
        path, digest = args.measured_au
        au, pin = read_au(Path(path).resolve(), digest, args.algorithm, gate, controls)
        pins += [pin, gate["host"], gate["image"], gate["g"]["report"], gate["g"]["reference"], gate["r"]["report"]]
        pins += [identity(module.__file__) for module in (admission, resident, wall, matrix)]
        pins.append(identity(__file__))
        rows["AU"].update(status=matrix.MEASURED, result=pin, attempts=au["attempts"], reused=True)
        report.update(status="RUNNING_SINGLE_PASS", baseline=gate, additional_r_gates=controls,
                      boundary=au["boundary"], runner_pins=pins)
        if cc:
            packet_pin = identity(args.cc_wall_packet)
            template = json.loads(args.cc_wall_packet.read_text())
            if any(template[name] != au["case"][name] for name in ("spine_binary", "gr_host", "spine_host")):
                raise ValueError("CC template differs from the measured AU hosts or Spine image")
            template["spine_host"] = str(args.balanced_host)
            pins += [packet_pin, identity(args.balanced_host)]
        for ds in cc_warm_matrix.DATASETS:
            row = rows[ds]
            case, frozen = resident.frozen_case(args.previous, args.algorithm, ds)
            packet, extra_args = None, []
            if cc:
                layout, inputs = layouts[ds]
                try:
                    packet = args.output / f"{ds.lower()}.packet.json"
                    save(packet, dict(template, inputs=str(inputs)))
                    case, added = wall.configure(argparse.Namespace(
                        algorithm="cc", cc_wall_packet=packet, cc_warm_layout=layout), case, frozen)
                    frozen += added
                except (OSError, ValueError) as error:
                    row.update(status="LAYOUT_NOT_ADMITTED", error=str(error))
                    save(journal, report)
                    continue
                extra_args = ["--cc-warm-layout", str(layout)]
            unchanged([*pins, *frozen])
            output = args.output / ds.lower()
            command = matrix.child_command(args, ds, case["memory_gib"], output, packet=packet)
            command += [*extra_args, "--cc-warm-r-controls" if cc else "--sssp-r-controls",
                        *map(str, controls_arg), "--au-r-diagnostic-sha256", args.au_r_diagnostic_sha256]
            row.update(status="REQUESTED", command=command, pins=frozen)
            save(journal, report)
            row.update(matrix.run_child(command, args.output / f"{ds.lower()}.service.log", output,
                                        ds, gate, au["boundary"], controls=controls))
            save(journal, report)
        report["status"] = ("MEASURED_DIAGNOSTIC_MATRIX" if all(row["status"] == matrix.MEASURED
                                                              for row in rows.values()) else "MATRIX_WITH_FAILURES")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def arguments(parser):
    parser.add_argument("--measured-au", nargs=2, metavar=("RESULT", "SHA256"), required=True)
    parser.add_argument("--layout", nargs=3, action="append", default=[], metavar=("DATASET", "RECEIPT", "INPUTS"))
    parser.add_argument("--balanced-host", type=lambda value: Path(value).resolve())
    parser.add_argument("--child-prefix", required=True)


if __name__ == "__main__":
    status = run(resident.parse_arguments(extend=arguments))["status"]
    print(status, flush=True)
    raise SystemExit(0 if status == "MEASURED_DIAGNOSTIC_MATRIX" else 1)
