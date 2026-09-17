#!/usr/bin/env python3
"""Rebuild Figure 10 from pinned v12 raw evidence, without refitting Figure 11."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from scripts.package_simulator_predicted_fig10 import (  # noqa: E402
    normalized_rows, validate_and_order_rows,
)
from spine_cycle_sim.experiments.rq3 import analyze_rq3_results  # noqa: E402
from spine_cycle_sim.experiments.shared_workloads import load_slice  # noqa: E402

SOURCE = Path('/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/package_with_vertices')
ZERO = Path('/data/tmp/chuxiao/fig10_v12_repair_20260917/zero_net_sssp_fallback')
SELECTION = (
    ('ZN', 'Syn', 'current_fpga_v12_zero_net_sssp'),
    ('SI', 'AU', 'current_fpga_v12_au_weighted_sssp_u8'),
    ('SI', 'SU', 'current_fpga_v12_su_weighted_sssp_u8'),
    ('SI', 'WK', 'current_fpga_v12_wk_weighted_sssp_u8'),
    ('Carry', 'L1', 'rq3_trace_carry_l1_e8'),
    ('Carry', 'L3', 'rq3_trace_carry_l3_e8'),
    ('Carry', 'L5', 'rq3_trace_carry_l5_e8'),
    ('PR-corr', 'FL', 'current_fpga_v12_flickr_respr_correction_u8'),
    ('PR-corr', 'SU', 'current_fpga_v12_su_thresholded_residual_pagerank_u8'),
    ('PR-corr', 'WK', 'current_fpga_v12_wk_thresholded_residual_pagerank_u8'),
    ('Del', 'Syn', 'current_fpga_v12_delete_fallback_sssp'),
)


def read(path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt') as source:
            return json.load(source)
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='ascii')


def write_csv(path, rows):
    with path.open('w', newline='', encoding='ascii') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plugin_identity():
    identities = {
        read(HERE / 'provenance/fig8.json')['frozen_identity']['spine_sst_plugin_sha256'],
        read(HERE / 'provenance/fig9.json')['plugins']['spine']['sha256'],
        read(HERE / 'provenance/fig11.json')['simulator']['plugin_sha256'],
    }
    require(len(identities) == 1, 'Figures 8, 9, and 11 disagree on Spine plugin')
    return identities.pop()


def check_zero_net(base, update):
    graph, batch = load_slice(base), load_slice(update)
    require(graph.vertices == batch.vertices, 'zero-net vertex domains differ')
    state = Counter()
    for edge in graph.records:
        state[(edge.src, edge.dst, edge.weight)] += edge.diff
    original = dict(state)
    for edge in batch.records:
        key = (edge.src, edge.dst, edge.weight)
        state[key] += edge.diff
        require(state[key] >= 0, 'zero-net trace removes a nonexistent edge')
    require(dict(state) == original, 'zero-net trace changes final graph')
    require(any(e.diff < 0 for e in batch.records), 'zero-net trace lacks deletion')
    require(any(e.diff > 0 for e in batch.records), 'zero-net trace lacks insertion')


def import_evidence(source, zero, plugin):
    evidence = HERE / 'evidence/fig10'
    evidence.mkdir(parents=True, exist_ok=True)
    for group, tick, execution_id in SELECTION:
        destination = evidence / execution_id
        destination.mkdir(exist_ok=True)
        if group == 'ZN':
            raw_path = zero / 'result.json'
            raw = read(raw_path)
            wrapper = {
                'status': 'pass', 'plugin_sha256': plugin,
                'case': {'execution_id': execution_id, 'dataset_id': 'synthetic_sssp_zero_net',
                         'system': 'spine', 'algorithm': 'weighted_sssp', 'scenario': 'weight_change',
                         'batch_size': 2, 'update': {'user_mutations': 2, 'physical_records': 4}},
                'row': {'cycles': raw['update_cycles'], 'dataset_kind': 'synthetic',
                        'measurement_window': 'dynamic_e2e_to_convergence',
                        'architecture_correctness_mismatches': 0, 'mathematical_correctness_mismatches': 0},
                'scalar_metrics': {'zero_net': True}, 'rq3_role': 'synthetic_calibration',
                'raw_result_path': str(raw_path), 'raw_result_sha256': digest(raw_path),
            }
            for filename, fixture in (
                ('base.slice', 'cc_zero_net_base.slice'),
                ('update.slice', 'cc_zero_net_delete_then_reinsert_u2.slice'),
            ):
                shutil.copyfile(REPO / 'tests/data/connected_components_formal' / fixture,
                                destination / filename)
        else:
            wrapper = read(source / 'runs' / execution_id / 'case_result.json')
            raw_path = Path(wrapper['raw_result_path'])
        require(wrapper['plugin_sha256'] == plugin, f'wrong plugin: {execution_id}')
        require(digest(raw_path) == wrapper['raw_result_sha256'], f'changed raw result: {execution_id}')
        summary_path = raw_path.parent / 'summary.json'
        summary = read(summary_path)
        require(summary.get('sst_plugin_sha256') == plugin, f'run identity mismatch: {execution_id}')
        expected_profile = ('spine_owner_fifo_respr_hls_v1' if group == 'PR-corr'
                            else 'spine_owner_fifo_sssp_hls_v1')
        require(summary.get('architecture_profile_id') == expected_profile,
                f'wrong architecture profile: {execution_id}')
        profile = REPO / 'configs/architectures' / f'{expected_profile}.json'
        require(digest(profile) == summary['architecture_profile_sha256'], 'profile changed')
        shutil.copyfile(profile, destination / 'architecture.json')
        for src, name in ((raw_path, 'result.json'), (summary_path, 'run_summary.json')):
            (destination / (name + '.gz')).write_bytes(gzip.compress(src.read_bytes(), mtime=0))
            (destination / name).unlink(missing_ok=True)
        wrapper['original_raw_result_path'] = wrapper['raw_result_path']
        wrapper['original_raw_result_sha256'] = wrapper['raw_result_sha256']
        wrapper['raw_result_path'] = str((destination / 'result.json.gz').relative_to(HERE))
        wrapper['raw_path_base'] = 'handoff_directory'
        wrapper['raw_result_sha256'] = digest(destination / 'result.json.gz')
        write(destination / 'case_result.json', wrapper)
    # Retain the failed CC attempt; it is not among the selected executions.
    rejected = zero.parent / 'zero_net_cc'
    if (rejected / 'run_manifest.json').exists():
        destination = evidence / 'rejected_zero_net_cc'
        destination.mkdir(exist_ok=True)
        (destination / 'result.json.gz').write_bytes(gzip.compress((rejected / 'result.json').read_bytes(), mtime=0))
        (destination / 'result.json').unlink(missing_ok=True)
        shutil.copyfile(rejected / 'run_manifest.json', destination / 'run_manifest.json')


def rebuild():
    plugin = plugin_identity()
    cases, sources = [], []
    for group, tick, execution_id in SELECTION:
        directory = HERE / 'evidence/fig10' / execution_id
        wrapper = read(directory / 'case_result.json')
        raw_path = directory / 'result.json.gz'
        raw, summary = read(raw_path), read(directory / 'run_summary.json.gz')
        require(wrapper['status'] == 'pass' and raw.get('success') is True,
                f'failed execution: {execution_id}')
        require(wrapper['plugin_sha256'] == summary.get('sst_plugin_sha256') == plugin,
                f'wrong plugin: {execution_id}')
        require(digest(raw_path) == wrapper['raw_result_sha256'], 'raw hash mismatch')
        require(hashlib.sha256(gzip.decompress(raw_path.read_bytes())).hexdigest()
                == wrapper['original_raw_result_sha256'], 'original raw hash mismatch')
        require(digest(directory / 'architecture.json') == summary['architecture_profile_sha256'],
                'architecture hash mismatch')
        require(raw.get('owner_scheduler_enabled') is True, 'owner scheduler disabled')
        correctness_keys = ('correctness_mismatches',) if group == 'Carry' else (
            'correctness_mismatches', 'architecture_correctness_mismatches',
            'mathematical_correctness_mismatches')
        for key in correctness_keys:
            require(raw.get(key) == 0, f'{execution_id}: {key}')
        if group == 'Carry':
            require(summary.get('status') == 'PASS', 'carry runner admission failed')
            for key in ('reader_protocol_status', 'compute_protocol_status',
                        'maintenance_carry_cursor_validation_failures'):
                require(raw.get(key) == 0, f'carry protocol failed: {key}')
        require(raw.get('maintenance_stage_ledger_closed') is True, 'open maintenance ledger')
        if group == 'ZN':
            check_zero_net(directory / 'base.slice', directory / 'update.slice')
            require(raw['cycles'] - raw['cold_cycles'] == raw['update_cycles'], 'bad update window')
            require(raw['dynamic_update_path'] == 'full_rebuild', 'changed zero-net behavior')
        wrapper['raw_result_path'] = str(raw_path)
        cases.append(wrapper)
        sources.append({'execution_id': execution_id, 'figure_group': group, 'figure_tick': tick,
                        'raw_result': str(raw_path.relative_to(HERE)), 'sha256': digest(raw_path),
                        'profile_id': summary['architecture_profile_id'],
                        'profile_sha256': summary['architecture_profile_sha256'],
                        'correctness_gate': ('carry fixture output/protocol checks' if group == 'Carry'
                                             else 'architecture and mathematical oracles'),
                        'residual_contract': raw.get('residual_contract'),
                        'iterations': raw.get('iterations', raw.get('rounds'))})
    analysis = analyze_rq3_results(cases, preferred_plugin_sha256=[plugin])
    by_id = {row['execution_id']: row for row in analysis['latency_rows']}
    rows = [{**by_id[execution_id], 'figure_group': group, 'figure_tick': tick}
            for group, tick, execution_id in SELECTION]
    stage_path = HERE / 'data/fig10_stage_rows.csv'
    write_csv(stage_path, rows)
    with stage_path.open(newline='') as stream:
        checked = validate_and_order_rows(list(csv.DictReader(stream)))
    output = HERE / 'data/fig10_normalized_breakdown_rows.csv'
    write_csv(output, normalized_rows(checked))
    summary_path = HERE / 'data/fig10_summary.json'
    write(summary_path, {
        'coverage': {row['case_class']: 'ready' for row in rows},
        'all_direct_ten_stage_ledgers_closed': all(r['ten_stage_ledger_closed'] for r in rows),
        'direct_ten_stage_rows': len(rows), 'preferred_plugin_sha256': [plugin],
    })
    evidence_files = sorted((HERE / 'evidence/fig10').rglob('*'))
    write(HERE / 'provenance/fig10.json', {
        'status': 'PASS_SIMULATOR_PREDICTED', 'rows': len(rows), 'plugin_sha256': plugin,
        'claim_scope': 'normalized execution-driven simulator stage attribution',
        'normalization': 'each bar independently sums to 100% of update-to-convergence device cycles',
        'sources': sources, 'data_csv_sha256': digest(stage_path),
        'outputs': {'normalized_breakdown_rows.csv': digest(output)},
        'stage_rows_sha256': digest(stage_path), 'summary_sha256': digest(summary_path),
        'evidence_sha256': {str(p.relative_to(HERE)): digest(p) for p in evidence_files if p.is_file()},
        'gates': {'single_plugin': True, 'matches_fig8_fig9_fig11_spine_plugin': True,
                  'source_correctness_admitted': True, 'stage_cycle_conservation': True,
                  'zero_net_snapshot_equivalence': True, 'complete_five_class_coverage': True},
        'limitations': [
            'Zero-net now uses SSSP; v12 takes a full-rebuild fallback. No no-repair claim.',
            'SU/WK PR correction has zero propagation rounds, verified from explicit work and owner counters.',
            'Drain includes measured completion/control gaps and synchronization outside component spans.',
            'FL uses the sink-free residual contract; SU/WK use the hardware warm dangling contract.',
            'Not FPGA per-stage calibration. Figure 11 remains its separately frozen diagnostic fit.',
        ],
    })
    for row in rows:
        print(row['figure_group'], row['figure_tick'], row['total_cycles'],
              'zero_round=' + str(row['observed_zero_round_correction']))
    print('FIG10_V12_PASS rows=11 plugin=' + plugin)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-sources', action='store_true')
    parser.add_argument('--source-root', type=Path, default=SOURCE)
    parser.add_argument('--zero-net-dir', type=Path, default=ZERO)
    args = parser.parse_args()
    if args.import_sources:
        import_evidence(args.source_root, args.zero_net_dir, plugin_identity())
    rebuild()


if __name__ == '__main__':
    main()
