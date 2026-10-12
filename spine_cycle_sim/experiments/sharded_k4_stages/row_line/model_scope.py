"""Separate frozen smoke bounds from the explicitly pinned resident graph matrix."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResidentCase:
    name: str
    vertices: int
    partitions: int
    rounds: int
    fixture_sha256: str
    values_sha256: str


RESIDENT_CASES = (
    ResidentCase("au", 515281, 8, 2,
                 "7dce4b07f5eae3d556cf5b9699c199fa55392bc802bc6f514d01e9b727cdd11a",
                 "0a51baed88066630c0162cdc2645cf929ce8f75b56cca3cb759abdee53aac768"),
    ResidentCase("su", 567316, 9, 2,
                 "02a19b038fc1c78e7c2b27ae7486f0e37816da8a7acf1192637cfd98b8677fb0",
                 "1b64fbed80a4bd506579583e4672ceeafbfa5d70a12c7e10ccf81959ae519b23"),
    ResidentCase("wk", 1140149, 18, 1,
                 "9b4b1f7ea62fa0f5509b3997666f29021afc3bf97fbe9833d0fc5264c0dda003",
                 "bacf28a1074678929e10c293b6d621eea4b8c86208bde1e958d0ce16c57a0280"),
)


@dataclass(frozen=True)
class StudyScope:
    name: str
    claim: str
    max_fixture_bytes: int
    max_vertices: int
    max_cycles: int
    cases: tuple[ResidentCase, ...] = ()

    @property
    def limits(self) -> dict:
        return {"timeout_seconds": 180, "max_cycles": self.max_cycles, "tree_memory_gib": 3,
                "reserve_gib": 16, "affinity": "112-113", "parallel_workers": 1}

    @property
    def inventory_limits(self) -> dict:
        return {"max_fixture_bytes": self.max_fixture_bytes, "max_vertices": self.max_vertices}

    def case_id(self, index: int) -> str:
        return self.cases[index].name if self.cases else f"case{index + 1}"

    def require_cases(self, declarations: list[dict]) -> None:
        expected_count = len(self.cases)
        if (not 1 <= len(declarations) <= 4 or (expected_count and len(declarations) != expected_count)
                or [row["id"] for row in declarations] != [self.case_id(i) for i in range(len(declarations))]):
            raise ValueError("declared model matrix differs")
        for expected, row in zip(self.cases, declarations):
            if (any(row["geometry"][key] != getattr(expected, key) for key in ("vertices", "partitions", "rounds"))
                    or row["fixture"]["sha256"] != expected.fixture_sha256
                    or row["expected_values"]["sha256"] != expected.values_sha256):
                raise ValueError("resident graph identity, scope or convergence differs")


SMOKE = StudyScope("smoke_v1", "bounded_whole_line_SST_smoke_not_FPGA_calibration_or_A4_comparison",
                   64 * 1024**2, 300000, 1000000)
RESIDENT = StudyScope("resident_matrix_v1", "pinned_resident_graph_prediction_not_FPGA_calibration_or_A4_comparison",
                      256 * 1024**2, 2000000, 100000000, RESIDENT_CASES)


def study_scope(name: str) -> StudyScope:
    for scope in (SMOKE, RESIDENT):
        if name == scope.name:
            return scope
    raise ValueError("unknown whole-line study scope")
