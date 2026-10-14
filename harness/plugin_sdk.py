"""One plugin-local SDK payload, fixed skill launchers and export size evidence."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

SDK_DIRECTORY = "sdk"
SDK_PACKAGING_GUIDANCE = (
    "\nBundled SDK commands share the installed plugin's `sdk/` library. Keep the "
    "complete plugin together, including `sdk/` and `skills/`; a skill folder alone "
    "is not an installable SDK bundle. Run the owning skill's `scripts/doctor.py` "
    "with host Python before local SDK modeling. A `plugin_incomplete` result "
    "requires restoring the complete plugin from its repository, not installing "
    "another Python library. This layout adds no setup dependency or runtime "
    "service. Export size evidence is in `sdk/PACKAGING.json`.\n"
    "Unexpected execution failures route to `report-openstudio-failure`, which "
    "automatically submits allowlisted sanitized diagnostics to "
    "https://github.com/pnnl/openstudio-ai-harness using existing GitHub CLI "
    "authentication. Issues are created under your own authenticated GitHub account. "
    "Models, companions and transcripts are excluded. Missing "
    "authentication/network retains local drafts. Run its independent "
    "`scripts/report_failure.py doctor` for optional reporting readiness and "
    "`policy disabled` to disable submission for this project. Reporting never "
    "gates modeling, and installation sends no incidents.\n"
)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def launcher(entry, bundle_id):
    # Fixed paths only. No environment lookup, source checkout or runtime import.
    return f'''"""Run this skill's entrypoint from the complete OpenStudio AI plugin."""
import hashlib
import json
from pathlib import Path
import runpy
import sys

try:
    library = Path(__file__).resolve().parents[3] / "{SDK_DIRECTORY}"
    bundle = json.loads((library / "bundle.json").read_text(encoding="utf-8"))
    files = bundle["files"]
    identity = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if bundle.get("layout_version") != 1 or identity != {bundle_id!r} or bundle.get("bundle_id") != identity:
        raise ValueError("SDK library does not match this skill launcher")
    for relative, expected in files.items():
        payload = library / relative
        if payload.is_symlink() or not payload.resolve().is_relative_to(library.resolve()) or hashlib.sha256(payload.read_bytes()).hexdigest() != expected:
            raise ValueError("SDK library file is missing or mismatched: " + relative)
except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
    print(json.dumps({{"ok": False, "ready": False, "status": "plugin_incomplete", "error": str(exc)[:400], "next_action": "Restore or reinstall the complete OpenStudio AI plugin, including sdk/; do not copy a skill alone."}}))
    raise SystemExit(2)
sys.path.insert(0, str(library))
runpy.run_path(str(library / {entry!r}), run_name="__main__")
'''


def plan_resources(resources, workspace_root, plugin_dir, host, budget, factory):
    sources = workspace_root / "skills/sdk_scripts"
    declarations = [
        (r, [o for o in r["owners"] if host in o["hosts"]])
        for r in resources
        if r.get("scope") == "plugin-sdk"
    ]
    declarations = [(r, owners) for r, owners in declarations if owners]
    if not declarations:
        return []
    payloads = {}
    baseline_bytes = baseline_copies = 0
    for resource, owners in declarations:
        source = (workspace_root / resource["source"]).resolve()
        if not source.is_relative_to(sources) or not source.is_file():
            raise ValueError(
                "Shared SDK resource must be a file inside skills/sdk_scripts"
            )
        baseline_copies += len(owners)
        baseline_bytes += source.stat().st_size * len(owners)
        if source.suffix in {".py", ".json"}:
            payloads[source.relative_to(sources).as_posix()] = source
    if "compatibility.json" not in payloads:
        raise ValueError("Shared SDK library requires its compatibility contract")
    hashes = {
        relative: hashlib.sha256(source.read_bytes()).hexdigest()
        for relative, source in sorted(payloads.items())
    }
    bundle_id = hashlib.sha256(encoded(hashes)).hexdigest()
    exports = [
        factory(source, plugin_dir / SDK_DIRECTORY / relative, "")
        for relative, source in sorted(payloads.items())
    ]
    entry_count = 0
    for resource, owners in declarations:
        source = (workspace_root / resource["source"]).resolve()
        for owner in owners:
            relative = Path(owner["path"])
            target = plugin_dir / "skills" / owner["skill"] / relative
            if relative.parts[0] == "references":
                exports.append(factory(source, target, owner["skill"]))
            elif len(relative.parts) == 2 and relative.suffix == ".py":
                if source.parent != sources:
                    raise ValueError("Skill entrypoints must be top-level SDK scripts")
                exports.append(
                    factory(
                        source, target, owner["skill"], launcher(source.name, bundle_id)
                    )
                )
                entry_count += 1
    source = next(iter(payloads.values()))
    from openstudio_ai_mcp.compatibility import package_version

    marker = {
        "layout_version": 1,
        "bundle_id": bundle_id,
        "files": hashes,
        "plugin_version": package_version(),
    }
    exports.append(
        factory(
            source,
            plugin_dir / SDK_DIRECTORY / "bundle.json",
            "",
            json.dumps(marker, indent=2) + "\n",
        )
    )
    current_bytes = sum(
        len(x.content.encode()) if x.content is not None else x.source.stat().st_size
        for x in exports
    )
    report = dict(
        schema_version=1,
        scope="sdk_resources",
        bundle_id=bundle_id,
        baseline_copies=baseline_copies,
        baseline_bytes=baseline_bytes,
        shared_payload_files=len(payloads),
        launchers=entry_count,
        resource_bytes_excluding_report=current_bytes,
        saved_bytes=baseline_bytes - current_bytes,
        reduction_fraction=1 - current_bytes / baseline_bytes,
        max_bytes=budget,
    )
    content = json.dumps(report, indent=2) + "\n"
    if current_bytes + len(content.encode()) > budget:
        raise ValueError(
            f"Shared SDK resource budget exceeded ({budget} bytes); review growth before export"
        )
    exports.append(
        factory(source, plugin_dir / SDK_DIRECTORY / "PACKAGING.json", "", content)
    )
    return exports


def write_resources(exports, plugin_dir):
    for export in exports:
        export.target.parent.mkdir(parents=True, exist_ok=True)
        if export.content is None:
            shutil.copy2(export.source, export.target)
        else:
            export.target.write_text(export.content, encoding="utf-8")
    report_path = plugin_dir / SDK_DIRECTORY / "PACKAGING.json"
    if not report_path.is_file():
        return
    report = json.loads(report_path.read_text())
    # Exclude this evidence file so totals do not depend on their own encoding.
    files = [p for p in plugin_dir.rglob("*") if p.is_file() and p != report_path]
    contents = Counter()
    sizes = {}
    for path in files:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        contents[digest] += 1
        sizes[digest] = len(data)
    total = sum(sizes[h] * n for h, n in contents.items())
    unique = sum(sizes.values())
    report["plugin_excluding_report"] = dict(
        files=len(files),
        total_bytes=total,
        unique_content_bytes=unique,
        duplicate_bytes=total - unique,
    )
    content = json.dumps(report, indent=2) + "\n"
    if (
        report["resource_bytes_excluding_report"] + len(content.encode())
        > report["max_bytes"]
    ):
        raise ValueError(
            "Shared SDK resource budget exceeded including packaging evidence"
        )
    report_path.write_text(content, encoding="utf-8")
