"""Inventory, preflight and apply a genuine supply-fan class replacement."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.fan_edit import inventory
from common.fan_class_replacement import plan, replace, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("replace_supply_fan", plan, replace, validate_model, inventory)
    )
