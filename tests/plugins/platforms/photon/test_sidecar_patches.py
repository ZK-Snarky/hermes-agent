from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


PATCH_SCRIPT = (
    Path(__file__).parents[4]
    / "plugins"
    / "platforms"
    / "photon"
    / "sidecar"
    / "patch-spectrum-catchup-rate-limit.mjs"
)
TARGET = "var isCursorRejectedIMessageError = (error) => error instanceof ValidationError;"


def _fake_sidecar_root(tmp_path: Path) -> Path:
    root = tmp_path / "sidecar"
    dist = root / "node_modules" / "spectrum-ts" / "dist"
    dist.mkdir(parents=True)
    (dist / "chunk-WMG36LHW.js").write_text(
        "class ValidationError extends Error {}\n"
        f"{TARGET}\n"
        "export { isCursorRejectedIMessageError };\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_catchup_rate_limit_patch_is_idempotent(tmp_path: Path) -> None:
    root = _fake_sidecar_root(tmp_path)

    first = subprocess.run(
        ["node", str(PATCH_SCRIPT), str(root)],
        check=True,
        text=True,
        capture_output=True,
    )
    assert "patched" in first.stderr

    second = subprocess.run(
        ["node", str(PATCH_SCRIPT), str(root)],
        check=True,
        text=True,
        capture_output=True,
    )
    assert " ok:" in second.stderr

    source = (root / "node_modules" / "spectrum-ts" / "dist" / "chunk-WMG36LHW.js").read_text(
        encoding="utf-8"
    )
    assert "catchUpEvents concurrency limit" in source
    assert source.count("isCursorRejectedIMessageError") == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_catchup_rate_limit_patch_fails_closed_on_sdk_drift(tmp_path: Path) -> None:
    root = tmp_path / "sidecar"
    dist = root / "node_modules" / "spectrum-ts" / "dist"
    dist.mkdir(parents=True)
    (dist / "chunk-WMG36LHW.js").write_text("export const changed = true;\n", encoding="utf-8")

    proc = subprocess.run(
        ["node", str(PATCH_SCRIPT), str(root)],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 1
    assert "could not find isCursorRejectedIMessageError" in proc.stderr
