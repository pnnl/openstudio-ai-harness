"""Reviewed plant topology operation; preserve the input model."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.plant_operations import (
    removal_plan,
    remove_plants,
    validate_removal,
    inventory,
)

if __name__ == "__main__":
    raise SystemExit(
        cli(
            "remove_unused_plants",
            removal_plan,
            remove_plants,
            validate_removal,
            inventory,
        )
    )
