"""Create reviewed hot/chilled/condenser plants through the skill bundle."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.model_transaction import cli
from common.plant_create import plan, create, validate_model

if __name__ == "__main__":
    raise SystemExit(
        cli(
            "create_plant_loops",
            plan,
            create,
            validate_model,
            lambda m: {
                "plant_loops": [
                    {
                        "name": p.nameString(),
                        "handle": str(p.handle()),
                        "type": p.sizingPlant().loopType(),
                    }
                    for p in m.getPlantLoops()
                ]
            },
        )
    )
