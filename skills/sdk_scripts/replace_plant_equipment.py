"""Reviewed plant topology operation; preserve the input model."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.plant_operations import (
    replacement_plan,
    replace_source,
    validate_replacement,
    inventory,
)

if __name__ == "__main__":
    raise SystemExit(
        cli(
            "replace_plant_equipment",
            replacement_plan,
            replace_source,
            validate_replacement,
            inventory,
        )
    )
