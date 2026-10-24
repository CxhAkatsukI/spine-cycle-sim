#!/usr/bin/env python3
"""Export the current hardware matrix without substituting historical values."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent
DATASETS = ('AU', 'SU', 'WK', 'SO', 'PK', 'LJ', 'LJ08', 'R19')
STYLES = (('respr', 'ResPR', '#F2C49B', '////////'),
          ('cc', 'CC', '#B9D5E6', '\\\\\\\\\\\\\\\\'),
          ('sssp', 'SSSP', '#BCDDAE', '||||||||'))
BOUNDARY = 'resident_update_to_final_readback_wall_including_host_relaunch'
TERMINAL = {'MATRIX_PASS', 'MATRIX_PARTIAL_RETAINED', 'FAILED_RETAINED'}


def collect(campaign):
    rows, reports, pins = [], {}, []
    for algorithm, _, _, _ in STYLES:
        path = campaign / algorithm / 'execution.json'
        if not path.exists():
            reports[algorithm] = {'status': 'NOT_STARTED'}
            continue
        payload = path.read_bytes()
        report = json.loads(payload)
        if report['boundary'] != BOUNDARY:
            raise ValueError('mixed timing boundaries')
        reports[algorithm] = report
        pins.append(dict(path=str(path), sha256=hashlib.sha256(payload).hexdigest()))
        seen = set()
        for row in report['rows']:
            dataset = row['dataset']
            if dataset not in DATASETS or dataset in seen:
                raise ValueError('unexpected or duplicate dataset')
            seen.add(dataset)
            if row['status'] != 'PASS':
                continue
            summary = row['summary']
            if summary['excluded_warmup_pairs'] != 1 or summary['measured_pairs'] != 3:
                raise ValueError('one warmup and three measured pairs required')
            gr = summary['walls']['gr']['median_ms']
            spine = summary['walls']['spine']['median_ms']
            if not all(math.isfinite(value) and value > 0 for value in (gr, spine)):
                raise ValueError('invalid measured wall time')
            ratio = gr / spine
            if not math.isclose(ratio, summary['speedup_ratio_of_median_walls']):
                raise ValueError('speedup does not match wall times')
            rows.append(dict(algorithm=algorithm, dataset=dataset, gr_median_ms=gr,
                             spine_median_ms=spine, speedup=ratio, measured_pairs=3,
                             gr_min_ms=summary['walls']['gr']['min_ms'],
                             gr_max_ms=summary['walls']['gr']['max_ms'],
                             spine_min_ms=summary['walls']['spine']['min_ms'],
                             spine_max_ms=summary['walls']['spine']['max_ms']))
    return rows, reports, pins


def render(rows, reports):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    preamble = (r'\usepackage{txfonts}\renewcommand{\rmdefault}{txtt}'
                r'\renewcommand{\sfdefault}{txtt}\renewcommand{\ttdefault}{txtt}'
                r'\renewcommand{\familydefault}{\ttdefault}')
    plt.rcParams.update({'text.usetex': True, 'text.latex.preamble': preamble,
        'font.family': 'monospace', 'font.size': 6.4, 'axes.labelsize': 6.6,
        'xtick.labelsize': 6, 'ytick.labelsize': 6, 'legend.fontsize': 6,
        'axes.linewidth': 0.7, 'hatch.linewidth': 0.38, 'pdf.fonttype': 42})
    figure, axis = plt.subplots(figsize=(3.55, 1.85))
    width = 0.24
    low = min((row['speedup'] for row in rows), default=1)
    high = max((row['speedup'] for row in rows), default=1)
    floor = min(0.1, 10 ** (math.ceil(math.log10(low)) - 1))
    for index, (algorithm, label, color, hatch) in enumerate(STYLES):
        selected = [row for row in rows if row['algorithm'] == algorithm]
        positions = [DATASETS.index(row['dataset']) + (index - 1) * width for row in selected]
        axis.bar(positions, [row['speedup'] - floor for row in selected], bottom=floor,
                 width=width, facecolor=color, edgecolor='black', linewidth=0.45,
                 hatch=hatch, zorder=3)
    axis.axhline(1, color='#202428', linestyle='--', linewidth=0.65, zorder=4)
    axis.set_yscale('log')
    axis.set_ylim(floor, max(2, 10 ** math.ceil(math.log10(high))))
    axis.set_xlim(-0.6, len(DATASETS) - 0.4)
    axis.set_xticks(range(len(DATASETS)), DATASETS)
    axis.set_ylabel('Speedup (G+R / Spine)')
    axis.tick_params(axis='x', length=0)
    axis.minorticks_off()
    axis.grid(axis='y', which='major', linestyle='--', linewidth=0.45, color='#D2D5D7')
    axis.set_axisbelow(True)
    for spine in axis.spines.values():
        spine.set_zorder(10)
    handles = [Patch(facecolor=color, edgecolor='black', linewidth=0.45, hatch=hatch,
                     label=label) for _, label, color, hatch in STYLES]
    axis.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 1.08),
                ncol=3, frameon=False, handlelength=1.25, columnspacing=0.8)
    pending = [label for algorithm, label, _, _ in STYLES
               if reports[algorithm]['status'] not in TERMINAL]
    note = ('In progress: ' + ', '.join(pending)) if pending else 'Completed hardware attempts'
    figure.text(0.53, 0.01, note, ha='center', va='bottom', fontsize=6)
    figure.subplots_adjust(left=0.17, right=0.995, top=0.77, bottom=0.18)
    figures = ROOT / 'figures'
    figures.mkdir(exist_ok=True)
    for suffix in ('pdf', 'png'):
        figure.savefig(figures / ('fig7_latest.' + suffix), dpi=300,
                       bbox_inches='tight', pad_inches=0.02)
    plt.close(figure)


def export(campaign):
    rows, reports, pins = collect(campaign)
    data = ROOT / 'data'
    data.mkdir(exist_ok=True)
    with (data / 'fig7_latest.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            'algorithm', 'dataset', 'gr_median_ms', 'spine_median_ms', 'speedup',
            'measured_pairs', 'gr_min_ms', 'gr_max_ms', 'spine_min_ms', 'spine_max_ms'))
        writer.writeheader()
        writer.writerows(rows)
    for algorithm, report in reports.items():
        (data / (algorithm + '_execution.json')).write_text(json.dumps(report, indent=2) + '\n')
        source = campaign / algorithm / 'manifest.json'
        if source.exists():
            payload = source.read_bytes()
            (data / (algorithm + '_manifest.json')).write_bytes(payload)
            pins.append(dict(path=str(source), sha256=hashlib.sha256(payload).hexdigest()))
    complete = len(rows) == 24 and all(report['status'] == 'MATRIX_PASS' for report in reports.values())
    (data / 'provenance.json').write_text(json.dumps(dict(
        status='COMPLETE_24_PAIRS' if complete else 'PARTIAL_NOT_FINAL',
        measured_rows=len(rows), expected_rows=24, boundary=BOUNDARY, source_pins=pins,
        convention='G+R median wall / Spine median wall; below one means G+R is faster',
        clock_policy='actual packaged clocks; no 450-MHz requirement or normalization',
        absent_data='pending or failed rows are absent, never replaced by historical/projected data'),
        indent=2) + '\n')
    render(rows, reports)
    return all(report['status'] in TERMINAL for report in reports.values())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    while True:
        done = export(args.campaign)
        if not args.watch or done:
            break
        time.sleep(30)
