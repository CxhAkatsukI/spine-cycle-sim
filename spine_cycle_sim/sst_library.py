"""Resolve an exact SST element-library search path for reproducible runs."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def forced_sst_library_binding(sst: Path, plugin_dir: Path) -> dict[str, str]:
    """Return a search path that selects the requested plugin before SST elements."""

    sst = sst.resolve()
    plugin_dir = plugin_dir.resolve()
    plugin = plugin_dir / "libspine_cycle.so"
    if not plugin.is_file():
        raise ValueError(f"missing Spine SST plugin: {plugin}")
    prefix = sst.parent.parent
    candidates = (
        prefix / "lib/sst-elements-library",
        prefix / "lib64/sst-elements-library",
    )
    element_dir = next(
        (
            candidate
            for candidate in candidates
            if (candidate / "libmemHierarchy.so").is_file()
        ),
        None,
    )
    if element_dir is None:
        raise ValueError(f"cannot locate SST element libraries under {prefix}")
    search_path = os.pathsep.join((str(plugin_dir), str(element_dir)))
    return {
        "search_path": search_path,
        "command_option": f"--lib-path={search_path}",
        "plugin_path": str(plugin),
        "plugin_sha256": hashlib.sha256(plugin.read_bytes()).hexdigest(),
        "sst_element_path": str(element_dir),
    }
