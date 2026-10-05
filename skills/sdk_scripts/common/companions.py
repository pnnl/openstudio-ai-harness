"""Plan and relocate model resources with hashes and a portable companion OSW."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_path(value, bases):
    path = Path(str(value))
    if path.is_absolute():
        candidates = [path]
    else:
        candidates = [base / path for base in bases]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise ValueError(f"Missing companion resource: {value}")


def inspect(model, source, output):
    directory = output.with_name(output.stem + "_files")
    if directory.exists() or directory.is_symlink():
        raise ValueError(f"Companion output already exists: {directory}")
    roots = [
        p
        for p in (source.with_suffix(""), source.with_name(source.stem + "_files"))
        if p.is_dir()
    ]
    workflows = [
        p
        for p in [source.with_suffix(".osw")]
        + [r / n for r in roots for n in ("in.osw", "workflow.osw")]
        if p.is_file()
    ]
    if len(workflows) > 1:
        raise ValueError(
            "Multiple companion workflows; select/consolidate one before local editing"
        )
    workflow = json.loads(workflows[0].read_text()) if workflows else {"steps": []}
    bases = (
        ([workflows[0].parent] if workflows else [])
        + roots
        + [source.parent, source.parent / "files"]
    )
    resources = {}
    paths = {}

    def add(path, target):
        path = path.resolve()
        if path.is_dir():
            for item in sorted(path.rglob("*")):
                relative = item.relative_to(path)
                if relative.parts[0] in {"run", "reports"} or item.name == ".DS_Store":
                    continue
                if item.is_file():
                    add(item, target / relative)
            return
        if not path.is_file():
            raise ValueError(f"Missing companion: {path}")
        if path.name == ".env" or any(part.startswith(".") for part in target.parts):
            raise ValueError(
                f"Sensitive files are outside companion-copy scope: {path}"
            )
        if str(target) in resources and resources[str(target)]["source"] != str(path):
            raise ValueError(f"Companion destination collision: {target}")
        resources[str(target)] = {
            "source": str(path),
            "target": str(target),
            "sha256": digest(path),
        }
        paths[str(path)] = str(directory / target)

    for i, root in enumerate(roots):
        add(root, Path("original") / str(i))
    file_paths = [
        resolve_path(value, bases) for value in workflow.get("file_paths", [])
    ]
    search = bases + file_paths
    measure_roots = []
    for i, value in enumerate(workflow.get("measure_paths", [])):
        root = resolve_path(value, bases)
        target = Path("measures") / str(i)
        add(root, target)
        measure_roots.append(str(target))
    # OSW's default measures directory may not appear explicitly in measure_paths.
    for base in bases:
        root = base / "measures"
        if root.is_dir() and str(root.resolve()) not in [
            str(resolve_path(v, bases)) for v in workflow.get("measure_paths", [])
        ]:
            target = Path("measures") / str(len(measure_roots))
            add(root, target)
            measure_roots.append(str(target))
    for i, root in enumerate(file_paths):
        add(root, Path("search") / str(i))
    weather = None
    if workflow.get("weather_file"):
        weather = resolve_path(workflow["weather_file"], search)
    wf = model.getWeatherFile().path()
    model_weather = resolve_path(str(wf.get()), search) if wf.is_initialized() else None
    if weather and model_weather and weather != model_weather:
        raise ValueError("Model and companion workflow select different weather files")
    weather = weather or model_weather
    external = []
    for obj in model.getExternalFiles():
        path = resolve_path(obj.fileName(), search)
        target = Path("files") / (digest(path)[:12] + "-" + path.name)
        add(path, target)
        external.append({"handle": str(obj.handle()), "path": str(directory / target)})
    if weather:
        target = Path("files") / (digest(weather)[:12] + "-" + weather.name)
        add(weather, target)
        workflow["weather_file"] = str(target)
    else:
        workflow.pop("weather_file", None)
    workflow["seed_file"] = str(Path("..") / output.name)
    workflow["file_paths"] = (
        ["files"]
        + [f"search/{i}" for i in range(len(file_paths))]
        + [f"original/{i}" for i in range(len(roots))]
    )
    workflow["measure_paths"] = measure_roots
    # A new workflow must not inherit stale run state or completion artifacts.
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
        "weather_path": paths.get(str(weather)) if weather else None,
        "external_files": external,
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
        relative = weather.relative_to(planned["directory"])
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
