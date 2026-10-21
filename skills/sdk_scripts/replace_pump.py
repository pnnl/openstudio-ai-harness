"""Inventory, preflight and apply a reviewed single-pump class replacement."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.pump_class_replacement import inventory, plan, replace, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("replace_pump_class", plan, replace, validate_model, inventory)
    )
