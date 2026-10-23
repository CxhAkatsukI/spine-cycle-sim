"""SST resolves its native backend symbols; the core scheduler drives timing."""

import json
import sys
import sst

sst.setProgramOption("timebase", "1ps")
component = sst.Component("refresh", "figure_refresh.Refresh")
component.addParams(json.loads(open(sys.argv[1], encoding="utf-8").read()))
