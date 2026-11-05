"""Collect one exact Spine CC route and run the AU replacement diagnostic."""

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    FIELDS, route_finished,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote.terminal_link import (
    unloaded,
)

from . import build_resume, cc_au_revision as revision
from .runtime import check_memory, identity, save
from ..board_execution import memory_policy


IMAGE = "spine_partitioned_split_e2e.cc_repair.hw.xclbin"
TIMING = "impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt"
START, TEARDOWN = "39f53479d3a045ac8e11786248231fbf", "ae8f7b866b0347b9af31fe1c80b127c0"


def retired(records, unit, invocation, root, *, resume=None):
    starts = [row for row in records if row.get("MESSAGE_ID") == START]
    finishes = [row for row in records if row.get("MESSAGE_ID") == TEARDOWN]
    if (len(starts) != 1 or len(finishes) != 1 or any(
            row.get("USER_UNIT") != unit or row.get("USER_INVOCATION_ID") != invocation
            or row.get("_SYSTEMD_USER_UNIT") != "init.scope" or row.get("JOB_TYPE") == "stop"
            or row.get("_EXE") not in ("/usr/lib/systemd/systemd", "/lib/systemd/systemd")
            or row.get("JOB_RESULT", "done") != "done"
            or row.get("UNIT_RESULT", "success") != "success" or row.get("EXIT_STATUS", "0") != "0"
            for row in records)):
        raise ValueError("collected build has no clean exact-invocation journal")
    start, end = starts[0], finishes[0]
    launch = start["MESSAGE"].replace("\\n", "\n").splitlines()
    named_launch = ([line.strip() for line in launch if line.strip().startswith("root=")] == [f"root={root}"]
                    if resume is None else all(re.search(re.escape(token) + r'(?=\s|[".]|$)', start["MESSAGE"])
                        for token in ('source_retention.build_resume', f'--output {resume[0]}',
                                      f'--script {resume[1]}')))
    if (start["_BOOT_ID"] != end["_BOOT_ID"]
            or int(start["__MONOTONIC_TIMESTAMP"]) >= int(end["__MONOTONIC_TIMESTAMP"])
            or not named_launch):
        raise ValueError("build journal names a different launch or output")


def select_files(command, root, *, image_name=IMAGE, build_log=None):
    if (Path(image_name).name != image_name or not re.fullmatch(r"[A-Za-z0-9_.-]+\.hw\.xclbin", image_name)):
        raise ValueError("an explicit hardware image basename is required")
    image = root / "xclbin" / image_name
    hooks = command(["find", root / "temp", "-type", "f", "-name", "bus_skew_routed.rpt"]).splitlines()
    if len(hooks) != 1 or not Path(hooks[0]).is_relative_to(root / "temp"):
        raise ValueError("expected one post-route skew-hook report in this build")
    return dict(host=root / "host_cc_repair", image=image, manifest=Path(str(image) + ".weighted-manifest"),
                timing=root / "reports/link/imp" / TIMING,
                skew=Path(hooks[0]), link=root / "logs" / f"v++_{image_name.removesuffix('.xclbin')}.log",
                build=root / "build.log" if build_log is None else build_log)


def collect(command, transfer, root, output, expected_abi, *, image_name=IMAGE, resume=None,
            original_log=None, resume_memory_profile='104g-v1'):
    paths = select_files(command, root, image_name=image_name, build_log=original_log)
    if resume is not None:
        record = json.loads(command(["cat", "--", resume]))
        if (record.get("status") != "BUILD_COMPLETED_NOT_BOARD_ADMITTED" or record.get("returncode") != 0
                or record.get("memory_profile", '104g-v1') != resume_memory_profile
                or record.get("policy") != build_resume.MEMORY_PROFILES[resume_memory_profile]
                or original_log is None):
            raise ValueError("resume must have its own successful guarded execution and original log")
        paths.update(resume_execution=resume, resume_script=Path(record["script"]["path"]),
                     resume_log=Path(record["build_log"]["path"]),
                     resume_supervisor=Path(record["supervisor"]["path"]))
    if len({path.name for path in paths.values()}) != len(paths):
        raise ValueError("route files must have distinct names")
    digests = {}
    for line in command(["sha256sum", "--", *paths.values()], timeout=120).splitlines():
        sha, separator, name = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", sha) or Path(name) in digests:
            raise ValueError("invalid remote route digest")
        digests[Path(name)] = sha
    if set(digests) != set(paths.values()):
        raise ValueError("remote route digest set differs from the requested files")
    output.mkdir()
    transfer(paths.values(), output)
    pins = {key: identity(output / path.name) for key, path in paths.items()}
    if any(pins[key]["sha256"] != digests[path] for key, path in paths.items()):
        raise ValueError("remote route file changed during transfer")
    if resume is not None:
        for key in ("script", "build_log", "supervisor"):
            pin = pins[{"script": "resume_script", "build_log": "resume_log",
                        "supervisor": "resume_supervisor"}[key]]
            if (pin['sha256'], pin['bytes']) != (record[key]['sha256'], record[key]['bytes']):
                raise ValueError("resume artifact differs from its completed execution")
        script = Path(pins['resume_script']['path']).read_text()
        if [line for line in script.splitlines() if line.startswith('root=')] != [f'root={root}']:
            raise ValueError('resume script names a different original build')
    manifest = Path(pins["manifest"]["path"]).read_text()
    abi, = re.findall(r"^build_sha256 ([a-f0-9]{64})$", manifest, re.MULTILINE)
    if abi != expected_abi:
        raise ValueError("collected route ABI differs from the frozen source and configuration")
    build = Path(pins["build"]["path"]).read_text()
    if f"SPINE_WEIGHTED_BUILD_SHA256='\"{abi}\"'" not in build or f"--expected {abi}" not in build:
        raise ValueError("the captured make log does not bind host and link to the same source ABI")
    return dict(**pins, linked_image=str(paths["image"]), abi=abi)


def run(args):
    with memory_policy.scope(getattr(args, "memory_profile", memory_policy.DEFAULT)):
        return _run(args)


def _run(args):
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+", args.remote)
            or not 1 <= args.port <= 65535
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", args.unit)
            or not re.fullmatch(r"[a-f0-9]{32}", args.invocation)
            or not re.fullmatch(r"[a-f0-9]{64}", args.abi)
            or not re.fullmatch(r"/data/chuxiao/[A-Za-z0-9_.-]+", str(args.root))
            or not 1 <= args.wait_seconds <= 64800):
        raise ValueError("explicit remote build identity and bounded wait required")
    resume, original_log = getattr(args, 'resume', None), getattr(args, 'original_log', None)
    if ((resume is None) != (original_log is None) or any(
            not re.fullmatch(r'/data/chuxiao/[A-Za-z0-9_./-]+', str(path)) or '..' in path.parts
            for path in (resume, original_log) if path is not None)):
        raise ValueError('resumed builds require both explicit safe execution and original-log paths')
    anchor = revision.pinned_arg(args.anchor)
    check_memory(24, require_live_reserve=False)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status="WAITING_FOR_ROUTE", anchor=anchor, root=str(args.root),
                  unit=args.unit, invocation=args.invocation, expected_abi=args.abi, runner=identity(__file__),
                  memory_profile=memory_policy.selected())

    def checkpoint():
        save(args.output / "results.json", report)

    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
           "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10",
           "-o", "ServerAliveCountMax=3", "-p", str(args.port)]

    def command(argv, *, timeout=40):
        proc = subprocess.run([*ssh, args.remote, shlex.join(map(str, argv))],
                              capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 255:
            raise ConnectionError(proc.stderr[-2000:])
        proc.check_returncode()
        return proc.stdout

    def transfer(paths, output):
        subprocess.run(["rsync", "-a", "--protect-args", "--timeout=120", "-e", shlex.join(ssh),
                        *(f"{args.remote}:{path}" for path in paths), str(output) + "/"],
                       check=True, timeout=600)

    try:
        deadline = time.monotonic() + args.wait_seconds
        while True:
            check_memory(24, require_live_reserve=False)
            try:
                state = dict(line.split("=", 1) for line in command(
                    ["systemctl", "--user", "show", args.unit, "--property=" + ",".join(FIELDS)]).splitlines())
                report.update(route_state=state, observer_error=None)
                if unloaded(state):
                    journal = command(["journalctl", "--user", "--boot", "--no-pager", "-o", "json",
                                       f"USER_UNIT={args.unit}", f"USER_INVOCATION_ID={args.invocation}"])
                    report["terminal_journal"] = [json.loads(line) for line in journal.splitlines()]
                    if resume is None:
                        retired(report["terminal_journal"], args.unit, args.invocation, args.root)
                    else:
                        record = json.loads(command(['cat', '--', resume]))
                        save(args.output / 'remote-resume-execution.json', record)
                        retired(report["terminal_journal"], args.unit, args.invocation, args.root,
                                resume=(resume.parent, Path(record['script']['path'])))
                    break
                if route_finished(state, args.invocation):
                    break
            except (ConnectionError, subprocess.TimeoutExpired) as error:
                report["observer_error"] = repr(error)
            checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("route wait expired without an admitted build")
            time.sleep(min(30, remaining))

        report["status"] = "COLLECTING_ROUTE"
        checkpoint()
        candidate = collect(command, transfer, args.root, args.output / "route", args.abi,
                            image_name=getattr(args, 'image_name', IMAGE), resume=resume, original_log=original_log,
                            resume_memory_profile=getattr(args, 'resume_memory_profile', '104g-v1'))
        spec = args.output / "candidate.json"
        save(spec, candidate)
        prepared = revision.preflight(anchor, identity(spec))
        save(args.output / "preflight.json", prepared)
        report.update(status="AU_SPINE_BOARD_REQUESTED", candidate=identity(spec))
        checkpoint()
        smoke = args.output / "spine"
        revision.spine_smoke.run(argparse.Namespace(
            host=Path(candidate["host"]["path"]), image=Path(candidate["image"]["path"]),
            output=smoke, memory_gib=24, admission_wait_seconds=3600,
            input_manifest=Path(prepared["inputs"]["path"]), resident_wall=True,
            memory_profile=memory_policy.selected()))
        result = revision.replay(prepared, identity(smoke / "results.json"))
        save(args.output / "comparison.json", result)
        report.update(status=result["status"], comparison=identity(args.output / "comparison.json"))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("remote", "unit", "invocation", "abi"):
        parser.add_argument("--" + name, required=True)
    for name in ("root", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--anchor", nargs=2, required=True, metavar=("JSON", "SHA256"))
    parser.add_argument("--wait-seconds", type=int, default=64800)
    parser.add_argument('--image-name', default=IMAGE)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--original-log', type=Path)
    parser.add_argument('--resume-memory-profile', choices=build_resume.MEMORY_PROFILES, default='104g-v1')
    parser.add_argument('--memory-profile', choices=memory_policy.PROFILES, default=memory_policy.DEFAULT)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
