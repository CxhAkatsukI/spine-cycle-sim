from hashlib import sha256
import json
from pathlib import Path

import pytest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cc_au_collect


ROOT = Path("/data/chuxiao/cc-build")
UNIT = "cc-build.service"
INVOCATION = "a" * 32
ABI = "b" * 64


@pytest.fixture
def journal():
    common = dict(USER_UNIT=UNIT, USER_INVOCATION_ID=INVOCATION, _BOOT_ID="boot",
                  _SYSTEMD_USER_UNIT="init.scope", _EXE="/usr/lib/systemd/systemd")
    return [
        dict(common, MESSAGE_ID=cc_au_collect.START, __MONOTONIC_TIMESTAMP="10",
             MESSAGE=f'Started {UNIT} - /bin/bash -c "\\n    root={ROOT}\\n    exec make\\n".'),
        dict(common, MESSAGE_ID=cc_au_collect.TEARDOWN, __MONOTONIC_TIMESTAMP="20"),
    ]


def test_retired_checks_exact_journal(journal):
    cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT)
    with pytest.raises(ValueError, match="different launch"):
        cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT / "different")


@pytest.mark.parametrize("mutation", [
    {"USER_INVOCATION_ID": "different"}, {"JOB_TYPE": "stop"}, {"JOB_RESULT": "timeout"},
    {"EXIT_STATUS": "1"}, {"_EXE": "/usr/bin/bash"},
])
def test_retired_rejects_dirty_teardown(journal, mutation):
    journal[1].update(mutation)
    with pytest.raises(ValueError, match="clean exact-invocation"):
        cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT)


@pytest.fixture
def route():
    hook = ROOT / "temp/vivado/bus_skew_routed.rpt"
    files = {
        cc_au_collect.IMAGE + ".weighted-manifest": f"build_sha256 {ABI}\n",
        "build.log": f"g++ -DSPINE_WEIGHTED_BUILD_SHA256='\"{ABI}\"'\ncheck.py --expected {ABI}\n",
    }

    def content(path):
        return files.get(path.name, f"sample {path.name}\n")

    def command(argv, *, timeout=40):
        if argv[0] == "find":
            return str(hook) + "\n"
        assert argv[:2] == ["sha256sum", "--"]
        return "".join(f"{sha256(content(path).encode()).hexdigest()}  {path}\n" for path in argv[2:])

    def transfer(paths, output):
        for path in paths:
            (output / path.name).write_text(content(path))

    return command, transfer


def test_collect_pins_all_files_and_expected_abi(route, tmp_path):
    candidate = cc_au_collect.collect(*route, ROOT, tmp_path / "valid", ABI)
    assert candidate["abi"] == ABI
    assert candidate["linked_image"] == str(ROOT / "xclbin" / cc_au_collect.IMAGE)
    assert len(candidate["build"]["sha256"]) == 64
    with pytest.raises(ValueError, match="frozen source"):
        cc_au_collect.collect(*route, ROOT, tmp_path / "wrong-abi", "c" * 64)


def test_collect_rejects_files_modified_in_transit(route, tmp_path):
    command, transfer = route

    def modified(paths, output):
        transfer(paths, output)
        (output / "build.log").write_text("different build log\n")

    with pytest.raises(ValueError, match="changed during transfer"):
        cc_au_collect.collect(command, modified, ROOT, tmp_path / "tampered", ABI)


def test_engine_filename_and_traversal(route):
    command, _ = route
    name = 'spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin'
    paths = cc_au_collect.select_files(command, ROOT, image_name=name)
    assert paths['image'].name == name
    assert paths['link'].name == f'v++_{name.removesuffix(".xclbin")}.log'
    with pytest.raises(ValueError, match='basename'):
        cc_au_collect.select_files(command, ROOT, image_name='../different.hw.xclbin')


def test_resume_journal_requires_exact_launch(journal):
    output, script = Path('/data/chuxiao/resume-v1'), Path('/data/chuxiao/resume.sh')
    journal[0]['MESSAGE'] = (f'Started {UNIT} - /usr/bin/python3 -m '
        f'spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.build_resume '
        f'--script {script} --output {output}.')
    cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT, resume=(output, script))
    with pytest.raises(ValueError, match='different launch'):
        cc_au_collect.retired(journal, UNIT, INVOCATION, ROOT, resume=(Path('/data/chuxiao/resume-v'), script))


@pytest.mark.parametrize('profile', ['104g-v1', '192g-v1'])
def test_collect_resumed_build_keeps_original_and_resume_evidence(tmp_path, profile):
    resume = Path('/data/chuxiao/resume-v1/execution.json')
    original = Path('/data/chuxiao/archive/original-build.log')
    name = 'spine_partitioned_split_e2e.engine-4-1-2-2-1.hw.xclbin'
    files = {
        original.name: f"g++ -DSPINE_WEIGHTED_BUILD_SHA256='\"{ABI}\"'\ncheck.py --expected {ABI}\n",
        name + '.weighted-manifest': f'build_sha256 {ABI}\n',
        'resume.sh': f'#!/bin/bash\nroot={ROOT}\nexec make\n',
        'build.log': 'resumed link completed\n',
        'build_resume.py': '# frozen supervisor\n',
    }
    def pin(path):
        content = files[Path(path).name].encode()
        return dict(path=path, sha256=sha256(content).hexdigest(), bytes=len(content))
    record = dict(status='BUILD_COMPLETED_NOT_BOARD_ADMITTED', returncode=0,
                  policy=cc_au_collect.build_resume.MEMORY_PROFILES[profile],
                  script=pin('/data/chuxiao/resume.sh'), build_log=pin(str(resume.parent / 'build.log')),
                  supervisor=pin('/data/chuxiao/source/build_resume.py'))
    if profile != '104g-v1':
        record['memory_profile'] = profile
    files['execution.json'] = json.dumps(record)
    def content(path):
        return files.get(path.name, 'sample\n')
    def command(argv, *, timeout=40):
        if argv[0] == 'cat':
            return files['execution.json']
        if argv[0] == 'find':
            return str(ROOT / 'temp/bus_skew_routed.rpt') + '\n'
        return ''.join(f'{sha256(content(path).encode()).hexdigest()}  {path}\n' for path in argv[2:])
    def transfer(paths, output):
        for path in paths:
            (output / path.name).write_text(content(path))
    result = cc_au_collect.collect(command, transfer, ROOT, tmp_path / 'route', ABI,
        image_name=name, resume=resume, original_log=original, resume_memory_profile=profile)
    assert Path(result['build']['path']).name == original.name
    assert Path(result['resume_log']['path']).name == 'build.log'
    assert result['resume_script']['sha256'] == record['script']['sha256']
    other_profile = '192g-v1' if profile == '104g-v1' else '104g-v1'
    with pytest.raises(ValueError, match='successful guarded execution'):
        cc_au_collect.collect(command, transfer, ROOT, tmp_path / 'wrong-profile', ABI,
            image_name=name, resume=resume, original_log=original, resume_memory_profile=other_profile)
    files['resume.sh'] += '# changed after execution\n'
    with pytest.raises(ValueError, match='completed execution'):
        cc_au_collect.collect(command, transfer, ROOT, tmp_path / 'tampered', ABI,
            image_name=name, resume=resume, original_log=original, resume_memory_profile=profile)
