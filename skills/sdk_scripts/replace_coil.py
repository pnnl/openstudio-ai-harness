"""Inventory, preflight and apply a reviewed genuine coil class conversion."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.water_coil import inventory
from common.coil_conversion import plan, convert, validate_model

if __name__ == "__main__":
    raise SystemExit(cli("replace_coil", plan, convert, validate_model, inventory))
