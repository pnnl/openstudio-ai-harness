"""Inventory, preflight and apply explicit heat-recovery attachment or editing."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.heat_recovery import inventory, plan, execute, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("manage_heat_recovery", plan, execute, validate_model, inventory)
    )
