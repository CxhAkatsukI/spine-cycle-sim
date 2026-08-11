"""Load calibration scales that were committed before holdout execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .current_fpga import PositiveScaleModel


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_frozen_scale_models(
    frozen_dir: Path,
    *,
    kind: str,
    contract_id: str,
    contract_sha256: str,
    cases_sha256: str,
    plugin_sha256: str,
) -> tuple[dict[tuple[str, ...], PositiveScaleModel], dict[str, Any]]:
    """Load one immutable scale bundle and verify its complete identity chain."""

    if kind not in {"total", "component"}:
        raise ValueError(f"unsupported frozen scale kind: {kind}")
    frozen_dir = frozen_dir.resolve()
    manifest_path = frozen_dir / "calibration_freeze_manifest.json"
    models_path = frozen_dir / f"frozen_{kind}_models.json"
    if not manifest_path.is_file() or not models_path.is_file():
        raise FileNotFoundError(frozen_dir)
    manifest = _read_json(manifest_path)
    payload = _read_json(models_path)
    for document, label in ((manifest, "manifest"), (payload, "model bundle")):
        if document.get("status") != "FROZEN_BEFORE_HOLDOUT":
            raise ValueError(f"{label} was not frozen before holdout")
        if document.get("contract_id") != contract_id:
            raise ValueError(f"{label} contract id mismatch")
        if document.get("contract_sha256") != contract_sha256:
            raise ValueError(f"{label} contract hash mismatch")
        if document.get("cases_sha256") != cases_sha256:
            raise ValueError(f"{label} case hash mismatch")
        if document.get("plugin_sha256") != plugin_sha256:
            raise ValueError(f"{label} plugin hash mismatch")
    path_key = f"frozen_{kind}_models"
    if Path(manifest.get(path_key, "")).resolve() != models_path:
        raise ValueError(f"{kind} model path mismatch")
    if manifest.get(f"{path_key}_sha256") != _sha256_file(models_path):
        raise ValueError(f"{kind} model hash mismatch")
    if manifest.get("holdout_result_files_present_at_freeze") != []:
        raise ValueError("freeze manifest contains pre-existing holdout results")

    models: dict[tuple[str, ...], PositiveScaleModel] = {}
    for row in payload.get("models", []):
        if row.get("fit_role") != "calibration_only" or row.get(
            "holdout_used_for_fit"
        ) is not False:
            raise ValueError("frozen model admits non-calibration fitting")
        calibration_datasets = tuple(row.get("calibration_datasets", ()))
        if calibration_datasets != ("au", "su"):
            raise ValueError("frozen model must use exactly AU/SU calibration")
        component = row.get("component")
        if kind == "total" and component is not None:
            raise ValueError("total model unexpectedly names a component")
        if kind == "component" and not component:
            raise ValueError("component model is missing its component identity")
        model = PositiveScaleModel(
            architecture=str(row["architecture"]),
            algorithm=str(row["algorithm"]),
            component=None if component is None else str(component),
            scale=float(row["scale"]),
            calibration_datasets=calibration_datasets,
        )
        key: tuple[str, ...] = (
            model.architecture,
            model.algorithm,
            str(row["profile_id"]),
        )
        if kind == "component":
            key += (str(model.component),)
        if key in models:
            raise ValueError(f"duplicate frozen model: {key}")
        models[key] = model
    if not models:
        raise ValueError(f"empty frozen {kind} model bundle")
    return models, {
        "manifest": str(manifest_path),
        "manifest_sha256": _sha256_file(manifest_path),
        "models": str(models_path),
        "models_sha256": _sha256_file(models_path),
    }
