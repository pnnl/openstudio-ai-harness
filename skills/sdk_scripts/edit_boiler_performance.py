"""Inventory, preflight and apply reviewed in-place hot-water boiler edits."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.boiler_edit import inventory, plan, edit, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("edit_boiler_performance", plan, edit, validate_model, inventory)
    )
