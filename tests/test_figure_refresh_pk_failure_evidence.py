"""Keep the packaged capacity diagnostic distinct from accepted timing data."""

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / ('docs/experiments/comparisons/grasu_regraph_stage_validation/'
                  'evaluation_impact/figure7_11_preview_20261105/fresh_simulator/'
                  'portable_fig8/diagnostics/pk_capacity_v1')


def test_failed_receipt_and_raw_artifacts_remain_pinned():
    index = json.loads((PACKAGE / 'index.json').read_text())
    assert index['status'] == 'FAILED_RETAINED'
    assert index['accepted_fig8_pair'] is False
    for name, expected in index['files'].items():
        assert sha256((PACKAGE / name).read_bytes()).hexdigest() == expected
    report = json.loads((PACKAGE / 'results.json').read_text())
    assert report['status'] == 'FAILED_RETAINED'
    assert report['steps']['trace_spine']['exit_code'] != 0
    assert not report['steps']['trace_spine']['timed_out']
    assert set(report['rows']) == {'smoke_spine', 'smoke_gr'}
    for name in ('update.hpp', 'update_failure.hpp', 'update_failure_tests.cpp'):
        pin, = (pin for pin in report['pins'] if pin['path'].endswith(
            '/cpp/tests/evaluation_impact/figure_refresh/' + name))
        assert pin['sha256'] == index['files'][name]


def test_failure_snapshot_has_no_free_cold_carry_target():
    raw = (PACKAGE / 'raw/trace_spine.stderr.txt').read_text()
    first, *_ = raw.splitlines()
    assert first.startswith('WARM_BATCH_FAILURE ')
    state = json.loads(first.removeprefix('WARM_BATCH_FAILURE '))
    assert (state['batch_index'], state['updates'], state['batch_cycles']) == (3, 410, 74875)
    cold = state['cold']
    family = cold['physical_records_by_family_level'][0]
    assert family[2] == 32746
    assert all(family[level] > 0 for level in range(2, 11))
    assert family[3:] == cold['capacity_per_level'][3:]
    assert 'Spine cold level hierarchy has no capacity-safe free target' in raw
