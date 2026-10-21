"""Plan and relocate model resources with hashes and a portable companion OSW."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


# Metadata is omitted, while secret-like files in referenced resources fail closed.
METADATA = {".git", ".hg", ".svn", ".github", ".gitkeep", ".DS_Store", "__pycache__"}
MAX_RESOURCE_BYTES = 256 * 1024 * 1024


def inspect(model, source, output, sdk):
    directory = output.with_suffix("")
    if directory.exists() or directory.is_symlink():
        raise ValueError(f"Companion output already exists: {directory}")
    roots = list(
        dict.fromkeys(
            p.resolve()
            for p in (source.with_suffix(""), source.with_name(source.stem + "_files"))
            if p.is_dir()
        )
    )
    workflows = list(
        dict.fromkeys(
            p.resolve()
            for p in [source.with_suffix(".osw")]
            + [r / n for r in roots for n in ("in.osw", "workflow.osw")]
            if p.is_file()
        )
    )
    if len(workflows) > 1:
        raise ValueError(
            "Multiple companion workflows; select/consolidate one before local editing"
        )
    from common.input_validation import read_json

    workflow = read_json(workflows[0]) if workflows else {"steps": []}
    lookup = sdk.WorkflowJSON(str(workflows[0])) if workflows else sdk.WorkflowJSON()
    if not workflows:
        lookup.setOswPath(str(source.with_suffix(".osw")))
    resources, skipped, warnings = {}, [], []
    total_bytes = 0
    workflow_ready = True

    def find(value, measure=False):
        result = (
            lookup.findMeasure(str(value)) if measure else lookup.findFile(str(value))
        )
        return Path(str(result.get())).resolve() if result.is_initialized() else None

    def add(path, target):
        nonlocal total_bytes
        if any(part in METADATA for part in target.parts):
            skipped.append(str(target))
            return
        name = path.name.lower()
        if (
            name.startswith((".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"))
            or name in {"credentials", "credentials.json"}
            or name.endswith((".pem", ".key"))
        ):
            raise ValueError(
                f"Sensitive files are outside companion-copy scope: {path}"
            )
        if path.is_symlink():
            raise ValueError(f"Symlink in referenced companion resource: {path}")
        if path.is_dir():
            for item in sorted(path.iterdir()):
                add(item, target / item.name)
            return
        if not path.is_file():
            raise ValueError(f"Missing companion: {path}")
        if str(target) in resources:
            if resources[str(target)]["source"] != str(path):
                raise ValueError(f"Companion destination collision: {target}")
            return
        total_bytes += path.stat().st_size
        if total_bytes > MAX_RESOURCE_BYTES:
            raise ValueError(
                "Referenced companions exceed the 256 MiB copy limit; reduce resources before editing"
            )
        resources[str(target)] = {
            "source": str(path),
            "target": str(target),
            "sha256": digest(path),
        }

    def copy_file(path):
        target = Path("files") / (digest(path)[:12] + "-" + path.name)
        add(path, target)
        return str(target)

    # Only referenced measures and explicit file arguments are carried forward.
    for step in workflow.get("steps", []):
        measure_name = step.get("measure_dir_name")
        if measure_name:
            measure = find(measure_name, measure=True)
            if measure is None:
                warnings.append(
                    f"Referenced measure is unavailable: {measure_name}; Model editing can proceed, workflow execution remains pending"
                )
                workflow_ready = False
                continue
            else:
                add(measure, Path("measures") / measure.name)
                step["measure_dir_name"] = measure.name
        for key, value in step.get("arguments", {}).items():
            if (
                not value
                or key.startswith(("output_", "report_"))
                or key.endswith("_dir")
            ):
                continue
            if isinstance(value, str) and (
                key.endswith(("_file", "_path")) or key == "file_name"
            ):
                resource = find(value)
                if resource is None or not resource.is_file():
                    warnings.append(
                        f"Workflow input is unavailable: {key}={value}; Model editing can proceed, workflow execution remains pending"
                    )
                    workflow_ready = False
                else:
                    step["arguments"][key] = copy_file(resource)

    weather = None
    candidates = [workflow.get("weather_file")]
    wf = model.getWeatherFile().path()
    candidates.append(str(wf.get()) if wf.is_initialized() else None)
    for value in candidates:
        if not value:
            continue
        resolved = find(value)
        if resolved is None:
            warnings.append(
                f"Weather resource is unavailable: {value}; Model editing can proceed, but simulation requires resolved weather"
            )
        elif weather and resolved != weather:
            raise ValueError(
                "Model and companion workflow select different weather files"
            )
        else:
            weather = resolved
    external = []
    for obj in model.getExternalFiles():
        path = find(obj.fileName())
        if path is None:
            raise ValueError(
                f"OpenStudio could not resolve external file: {obj.fileName()}"
            )
        target = copy_file(path)
        external.append({"handle": str(obj.handle()), "path": Path(target).name})
    weather_target = copy_file(weather) if weather else None
    if weather_target:
        workflow["weather_file"] = weather_target
    else:
        workflow.pop("weather_file", None)
    workflow["seed_file"] = str(Path("..") / output.name)
    workflow["file_paths"] = ["files"]
    workflow["measure_paths"] = ["measures"]
    workflow.pop("root", None)
    for key in (
        "completed_at",
        "started_at",
        "current_step",
        "completed_status",
        "out_path",
        "run_options",
    ):
        workflow.pop(key, None)
    return {
        "directory": str(directory),
        "resources": sorted(resources.values(), key=lambda x: x["target"]),
        "workflow": workflow,
        "weather_path": (
            str(Path(output.stem) / weather_target) if weather_target else None
        ),
        "weather_resource": weather_target,
        "external_files": external,
        "warnings": warnings,
        "simulation_ready": weather is not None and workflow_ready,
        "skipped_metadata": sorted(set(skipped)),
        "total_bytes": total_bytes,
        "workflow_source": (
            {"source": str(workflows[0]), "sha256": digest(workflows[0])}
            if workflows
            else None
        ),
    }


def verify(planned):
    dependencies = planned["resources"] + (
        [planned["workflow_source"]] if planned.get("workflow_source") else []
    )
    for item in dependencies:
        if digest(Path(item["source"])) != item["sha256"]:
            raise ValueError(f"Companion changed since preflight: {item['source']}")


def stage(model, sdk, planned, staging):
    verify(planned)
    staging.mkdir()
    for item in planned["resources"]:
        source = Path(item["source"])
        if digest(source) != item["sha256"]:
            raise ValueError(f"Companion changed since preflight: {source}")
        target = staging / item["target"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if digest(target) != item["sha256"]:
            raise ValueError(f"Companion copy hash mismatch: {source}")
    (staging / "workflow.osw").write_text(
        json.dumps(planned["workflow"], indent=2) + "\n"
    )
    if planned["weather_path"]:
        weather = Path(planned["weather_path"])
        relative = Path(planned["weather_resource"])
        result = sdk.model.WeatherFile.setWeatherFile(
            model, sdk.EpwFile(str(staging / relative))
        )
        if not result.is_initialized():
            raise RuntimeError("SDK rejected companion weather file")
        # Resolve the IDD Url field rather than depending on its numeric position.
        obj = result.get()
        index = next(
            i
            for i in range(obj.numFields())
            if obj.iddObject().getField(i).get().name() == "Url"
        )
        if not obj.setString(index, str(weather)):
            raise RuntimeError("SDK rejected relocated weather path")
    for reference in planned["external_files"]:
        obj = model.getExternalFile(sdk.toUUID(reference["handle"])).get()
        # ExternalFile has no file-path setter in this SDK; use its IDD field.
        index = next(
            i
            for i in range(obj.numFields())
            if "File Name" in obj.iddObject().getField(i).get().name()
        )
        if not obj.setString(index, reference["path"]):
            raise RuntimeError("SDK rejected relocated external file")


def external_file_status(model):
    """Translation errors do not detect empty Schedule:File filenames."""
    files = []
    for obj in model.getExternalFiles():
        path = Path(str(obj.filePath()))
        files.append(
            {"name": obj.fileName(), "path": str(path), "resolved": path.is_file()}
        )
    return {"ok": all(item["resolved"] for item in files), "files": files}
