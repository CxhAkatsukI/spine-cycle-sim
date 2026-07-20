#!/usr/bin/env python3
"""Run built-in HW maintenance calibration matrices."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration import (  # noqa: E402
    DEFAULT_FEATURES,
    aggregate_rows,
    build_hw_command,
    matrix_by_name,
    run_hw_case,
    write_json,
    write_rows_csv,
)
from spine_cycle_sim.calibration.maintenance import (  # noqa: E402
    DEFAULT_FREQ_MHZ,
    DEFAULT_HOST_EXE,
    DEFAULT_XRT_SETUP,
    RAW_FIELD_ORDER,
    SUMMARY_FIELD_ORDER,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xclbin", type=Path, required=True)
    parser.add_argument("--host-exe", type=Path, default=Path(DEFAULT_HOST_EXE))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument("--xrt-setup", type=Path, default=Path(DEFAULT_XRT_SETUP))
    parser.add_argument("--no-xrt-setup", action="store_true")
    parser.add_argument("--no-split-kernels", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument(
        "--matrix",
        choices=["phase2b", "phase2d_holdout", "phase4c_partition_spread"],
        default="phase2b",
        help="Select the built-in experiment matrix.",
    )
    parser.add_argument(
        "--only-sweep",
        action="append",
        help="Limit the selected matrix to one or more sweep groups.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    specs = matrix_by_name(args.matrix)
    if args.only_sweep:
        allowed = set(args.only_sweep)
        specs = [spec for spec in specs if spec.sweep in allowed]

    xrt_setup = None if args.no_xrt_setup else args.xrt_setup
    split_kernels = not args.no_split_kernels
    matrix_rows = [spec.to_row() for spec in specs]
    write_json(args.out_dir / "matrix.json", matrix_rows)
    write_json(
        args.out_dir / "metadata.json",
        {
            "xclbin": str(args.xclbin),
            "host_exe": str(args.host_exe),
            "repeats": args.repeats,
            "timeout_s": args.timeout,
            "freq_mhz": args.freq_mhz,
            "matrix": args.matrix,
            "xrt_setup": str(xrt_setup) if xrt_setup else "",
            "split_kernels": split_kernels,
            "features": DEFAULT_FEATURES,
        },
    )

    commands: list[str] = []
    for spec in specs:
        for repeat in range(1, args.repeats + 1):
            commands.append(
                build_hw_command(
                    spec,
                    host_exe=args.host_exe,
                    xclbin=args.xclbin,
                    timeout_s=args.timeout,
                    xrt_setup=xrt_setup,
                    split_kernels=split_kernels,
                )
            )
    command_script = args.out_dir / "commands.sh"
    command_script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        + "\n\n".join(commands)
        + "\n",
        encoding="utf-8",
    )
    command_script.chmod(0o755)

    if args.dry_run:
        print(f"wrote matrix: {args.out_dir / 'matrix.json'}")
        print(f"wrote commands: {command_script}")
        print(f"cases={len(specs)} repeats={args.repeats} total_runs={len(commands)}")
        return 0

    rows: list[dict] = []
    failures = 0
    for spec in specs:
        for repeat in range(1, args.repeats + 1):
            print(f"[{spec.case}] repeat {repeat}/{args.repeats}", flush=True)
            row, stdout, stderr = run_hw_case(
                spec,
                repeat=repeat,
                host_exe=args.host_exe,
                xclbin=args.xclbin,
                timeout_s=args.timeout,
                freq_mhz=args.freq_mhz,
                xrt_setup=xrt_setup,
                split_kernels=split_kernels,
            )
            raw_dir = args.out_dir / "raw" / spec.case
            raw_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = raw_dir / f"run_{repeat}.stdout"
            stderr_path = raw_dir / f"run_{repeat}.stderr"
            command_path = raw_dir / f"run_{repeat}.command.sh"
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
            command_path.write_text(row["command"] + "\n", encoding="utf-8")
            command_path.chmod(0o755)
            row["stdout_log"] = str(stdout_path)
            row["stderr_log"] = str(stderr_path)
            row["command_log"] = str(command_path)
            rows.append(row)
            if row.get("returncode") != 0 or row.get("status") == "FAIL":
                failures += 1
            print(
                f"  status={row.get('status')} returncode={row.get('returncode')} "
                f"maint_ms={row.get('maint_ms', '')}",
                flush=True,
            )

    write_rows_csv(args.out_dir / "runs.csv", rows, RAW_FIELD_ORDER)
    write_json(args.out_dir / "runs.json", rows)
    summary = aggregate_rows(rows, freq_mhz=args.freq_mhz)
    write_rows_csv(args.out_dir / "summary.csv", summary, SUMMARY_FIELD_ORDER)
    write_json(args.out_dir / "summary.json", summary)
    print(f"wrote runs: {args.out_dir / 'runs.csv'}")
    print(f"wrote summary: {args.out_dir / 'summary.csv'}")
    if failures and not args.allow_failures:
        print(f"failures={failures}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
