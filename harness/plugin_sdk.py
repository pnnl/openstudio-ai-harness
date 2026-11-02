"""One plugin-local SDK payload, fixed skill launchers and export size evidence."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
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


def reference_aliases(resources, workspace_root, host):
    """Map declared skill-local SDK reference aliases to plugin-local files."""
    sources = workspace_root.resolve() / "skills/sdk_scripts"
    result = {}
    for resource in resources:
        source = (workspace_root / resource["source"]).resolve()
        if resource.get("scope") != "plugin-sdk" or source.suffix == ".py":
            continue
        target = "../../sdk/" + source.relative_to(sources).as_posix()
        for owner in resource["owners"]:
            if host not in owner["hosts"]:
                continue
            aliases = {owner["path"]}
            if owner["path"].startswith("scripts/references/"):
                aliases.add(owner["path"].removeprefix("scripts/"))
            elif owner["path"].startswith("references/"):
                aliases.add("scripts/" + owner["path"])
            aliases.update("./" + alias for alias in list(aliases))
            mapping = result.setdefault(owner["skill"], {})
            for alias in aliases:
                if alias in mapping and mapping[alias] != target:
                    raise ValueError("Conflicting shared SDK reference alias")
                mapping[alias] = target
    return result


def _reference_pattern(aliases):
    paths = "|".join(re.escape(x) for x in sorted(aliases, key=len, reverse=True))
    # Do not rewrite substrings of another filename or an already shared path.
    # A sentence-ending period is punctuation; .backup is a filename suffix.
    return re.compile(r"(?<![\w./-])(?:" + paths + r")(?![\w/-]|\.\w)")


def rewrite_reference_paths(content, aliases):
    """Rewrite complete path tokens, including links and inline code, once."""
    if not aliases:
        return content
    return _reference_pattern(aliases).sub(
        lambda match: aliases[match.group()], content
    )


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
        if source.suffix in {".py", ".json", ".md"}:
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
            if len(relative.parts) == 2 and relative.suffix == ".py":
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
    categories = {
        key: dict(files=0, bytes=0)
        for key in ("payload", "launchers", "references", "metadata")
    }
    for export in exports:
        relative = export.target.relative_to(plugin_dir)
        if relative.parts[0] != SDK_DIRECTORY:
            category = "launchers"
        elif relative.name == "bundle.json":
            category = "metadata"
        elif relative.parts[1] in {"references", "schemas"}:
            category = "references"
        else:
            category = "payload"
        categories[category]["files"] += 1
        categories[category]["bytes"] += (
            len(export.content.encode())
            if export.content is not None
            else export.source.stat().st_size
        )
    current_bytes = sum(x["bytes"] for x in categories.values())
    report = dict(
        schema_version=2,
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
        categories=categories,
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


def write_resources(exports, plugin_dir, *, aliases=None):
    # Adapters have already copied local skill files and host-specific references.
    # Inspect those actual files too, rather than relying only on manifest paths.
    for skill, mapping in (aliases or {}).items():
        for alias in mapping:
            target = plugin_dir / "skills" / skill / alias
            if (
                target.exists()
                or target.is_symlink()
                or any(target == export.target for export in exports)
            ):
                raise ValueError(f"SDK reference alias destination collision: {alias}")
    for export in exports:
        export.target.parent.mkdir(parents=True, exist_ok=True)
        if export.content is None:
            shutil.copy2(export.source, export.target)
        else:
            export.target.write_text(export.content, encoding="utf-8")
    for skill, mapping in (aliases or {}).items():
        path = plugin_dir / "skills" / skill / "SKILL.md"
        content = path.read_text(encoding="utf-8")
        rewritten = rewrite_reference_paths(content, mapping)
        if mapping and _reference_pattern(mapping).search(rewritten):
            raise ValueError(f"Unrewritten SDK reference alias in {skill}/SKILL.md")
        path.write_text(rewritten, encoding="utf-8")
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
