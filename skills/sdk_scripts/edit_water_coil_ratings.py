"""Inventory, preflight and apply a reviewed water-coil operation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.water_coil import inventory, plan_edit, change, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("edit_water_coil_ratings", plan_edit, change, validate_model, inventory)
    )
