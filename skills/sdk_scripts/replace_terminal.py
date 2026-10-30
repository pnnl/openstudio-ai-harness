"""Inventory, review and replace one no-reheat terminal's equipment class."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.terminal_replacement import inventory, plan, replace, validate_model

if __name__ == "__main__":
    raise SystemExit(cli("replace_terminal", plan, replace, validate_model, inventory))
