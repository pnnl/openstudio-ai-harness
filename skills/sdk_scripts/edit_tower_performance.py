"""Inventory, preflight and apply reviewed variable-speed tower performance edits."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.tower_edit import inventory, plan, edit, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli("edit_tower_performance", plan, edit, validate_model, inventory)
    )
