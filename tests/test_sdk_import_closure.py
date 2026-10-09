"""Bundled local SDK imports must resolve inside each independently moved skill."""

import ast
from pathlib import Path
import pytest
from harness.asset_manifest import resource_exports_for_host


@pytest.mark.parametrize("host", ["claude", "codex"])
def test_sdk_bundle_local_import_closure(tmp_path, host):
    root = Path.cwd()
    exports = resource_exports_for_host(root, tmp_path, host)
    sources = root / "skills/sdk_scripts"
    modules = {
        ".".join(path.relative_to(sources).with_suffix("").parts)
        for path in sources.rglob("*.py")
    }
    targets = {item.target for item in exports}
    for item in exports:
        if item.source.suffix != ".py" or not item.source.is_relative_to(sources):
            continue
        tree = ast.parse(item.source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = [node.module] if not node.level else []
                # from common import foo imports a sibling module, when one exists.
                imported += [(node.module or "") + "." + x.name for x in node.names]
            elif isinstance(node, ast.Import):
                imported = [x.name for x in node.names]
            else:
                continue
            for name in imported:
                if name not in modules:
                    continue
                relative = Path(*name.split(".")).with_suffix(".py")
                # All resource destinations preserve the scripts module root.
                script_root = next(
                    parent for parent in item.target.parents if parent.name == "scripts"
                )
                assert (
                    script_root / relative in targets
                ), f"{item.target}: missing local import {name}"
