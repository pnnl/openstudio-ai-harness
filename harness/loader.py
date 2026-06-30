from __future__ import annotations

from pathlib import Path

from harness.artifact_types import HarnessAssets
from harness.registry import discover_harness_assets


def load_harness_assets(root: str | Path) -> HarnessAssets:
    return discover_harness_assets(Path(root))

