"""Explicit, hash-indexed build/runtime paths without changing the cycle model."""

from dataclasses import dataclass
from pathlib import Path
import platform


@dataclass(frozen=True)
class Environment:
    compiler: Path
    sst: Path
    sst_include: Path
    dram: Path
    python_home: Path | None = None
    python_library: Path | None = None

    def inputs(self):
        paths = [self.compiler, self.sst, self.dram / "libdramsim3.so",
                 self.dram / "src/dramsim3.h"]
        headers = sorted(p for p in self.sst_include.rglob("*") if p.is_file())
        if not headers:
            raise ValueError("SST headers required")
        paths.extend(headers)
        if (self.python_home is None) != (self.python_library is None):
            raise ValueError("embedded Python home and shared library must be specified together")
        if self.python_home is not None:
            paths.append(self.python_library)
            paths.extend(sorted(p for p in self.python_home.rglob("*")
                                if p.is_file() and p.suffix == ".py"))
        if any(not p.is_file() for p in paths):
            raise ValueError("build/runtime dependency missing")
        return paths

    def prefix(self):
        libraries = [str(self.dram)]
        assignments = []
        if self.python_home is not None:
            libraries.append(str(self.python_library.parent))
            assignments.append("PYTHONHOME=" + str(self.python_home))
        return ["env", "LD_LIBRARY_PATH=" + ":".join(libraries), *assignments]

    def description(self):
        fields = {key: str(value) if value is not None else None
                  for key, value in vars(self).items()}
        cpu_fields = (line.partition(":") for line in Path("/proc/cpuinfo").read_text().splitlines())
        cpu_model = next((value.strip() for key, _, value in cpu_fields
                          if key.strip() == "model name"), platform.processor())
        return dict(host=platform.node(), platform=platform.platform(), paths=fields,
                    cpu_model=cpu_model,
                    host_timing_cohort="same host for both arms; do not pool across CPU hosts")
