"""Inventory, preflight and attach an explicit direct outdoor-air system."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.outdoor_air_attach import inventory, plan, execute, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("attach_outdoor_air", plan, execute, validate_model, inventory)
    )
