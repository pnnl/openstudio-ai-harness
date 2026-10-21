"""Read-only embedded SDK probe launched by the skill-local doctor."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# OpenStudio's embedded launcher does not add the script folder to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.version_guard import load_contract, require_sdk

PROBE_PREFIX = "OPENSTUDIO_SKILL_SDK_PROBE="


def main() -> int:
    try:
        sdk = require_sdk(load_contract())
        # Exercise the Python model binding, without reading/writing a user file.
        model = sdk.model.Model()
        report = {
            "ok": True,
            "sdk_version": str(sdk.openStudioVersion()),
            "sdk_module": str(getattr(sdk, "__file__", "embedded")),
            "python_version": sys.version.split()[0],
            "model_object_count": len(model.modelObjects()),
        }
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}
    print(PROBE_PREFIX + json.dumps(report))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
