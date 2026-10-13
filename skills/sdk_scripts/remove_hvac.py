"""Remove explicitly selected HVAC systems in a validated copied model."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.hvac_remove import plan, remove, validate_model, inventory

if __name__ == "__main__":
    raise SystemExit(cli("remove_hvac", plan, remove, validate_model, inventory))
