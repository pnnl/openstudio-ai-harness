"""Inventory, preflight and apply a reviewed supply-fan performance edit."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.fan_edit import inventory, plan, edit, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("edit_supply_fan_performance", plan, edit, validate_model, inventory)
    )
