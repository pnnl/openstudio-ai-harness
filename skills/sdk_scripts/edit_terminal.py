"""Inventory, preflight and apply one in-place VAV terminal-control edit."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.terminal_edit import inventory, plan, edit, validate_model

if __name__ == "__main__":
    raise SystemExit(cli("edit_terminal", plan, edit, validate_model, inventory))
