"""Inventory, preflight and apply one reviewed in-place economizer edit."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.economizer_edit import inventory, plan, edit, validate_model

if __name__ == "__main__":
    raise SystemExit(cli("edit_economizer", plan, edit, validate_model, inventory))
