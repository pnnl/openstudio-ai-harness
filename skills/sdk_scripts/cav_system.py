"""Inventory, preflight or apply a reviewed prototype CAV system."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.cav_system import plan, create, validate_model
from common.hvac_inventory import inventory

if __name__ == "__main__":
    raise SystemExit(cli("create_cav_system", plan, create, validate_model, inventory))
