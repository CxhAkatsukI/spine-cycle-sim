"""Resident compute-only SST entry, independent of the legacy v8 probe."""

import json
import os
from pathlib import Path
import sys

import sst

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import component_parameters

config = json.loads(Path(os.environ["ROUTED_K4_RUN_CONFIG"]).read_text())
probe = sst.Component("routed_k4_compute", "spine_cycle.RoutedReGraphProbe")
probe.addParams(component_parameters(ROOT, config))
