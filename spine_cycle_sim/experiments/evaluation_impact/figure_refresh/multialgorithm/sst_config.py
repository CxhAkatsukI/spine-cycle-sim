"""Thin SST loader; the core scheduler owns device time."""

import json
import sys
import sst

sst.setProgramOption("timebase", "1ps")
component = sst.Component("refresh", "figure_multi.Refresh")
component.addParams(json.loads(open(sys.argv[1], encoding="utf-8").read()))
