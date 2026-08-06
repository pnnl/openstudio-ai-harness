from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openstudio_mcp.sdk_docs.lookup import (
    write_index_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a compact OpenStudio SDK doc index from YAML documentation."
    )
    parser.add_argument(
        "--docs-dir",
        required=True,
        help="Directory containing api/classes.yaml (e.g. openstudio_mcp/sdk_docs/docs).",
    )
    parser.add_argument(
        "--output",
        default=".sdk_doc_index.json",
        help="Output JSON path. The generated file is local cache material.",
    )
    args = parser.parse_args()

    output = write_index_file(
        docs_dir=Path(args.docs_dir),
        output_path=Path(args.output),
    )
    print(f"Wrote SDK doc index: {output}")


if __name__ == "__main__":
    main()
