"""Preserve external data with absolute references in fixed runtime workspaces."""

from pathlib import Path
import hashlib
import json
import shutil


def copy_model_resources(
    source: Path,
    target: Path,
    *,
    max_resource_bytes: int = 256 * 1024 * 1024,
    copy_weather: bool = True,
) -> list[str]:
    """Copy CSVs with absolute references; resolve and size all resources first."""
    # Ordinary models must not gain a Python SDK dependency from an App workflow.
    if b"OS:External:File," not in source.read_bytes():
        return []
    import openstudio as sdk

    loaded = sdk.osversion.VersionTranslator().loadModel(str(source))
    if not loaded.is_initialized():
        raise ValueError(f"Could not load model resources: {source}")
    model = loaded.get()
    workflow = source.with_suffix("") / "workflow.osw"
    if workflow.is_file():
        model.setWorkflowJSON(sdk.WorkflowJSON(str(workflow)))
    else:
        model.workflowJSON().setOswPath(str(source.with_suffix(".osw")))
    directory = target.with_suffix("")
    files = directory / "files"
    planned, external = {}, []
    total_bytes = 0

    def plan_file(path):
        nonlocal total_bytes
        path = path.resolve()
        if not path.is_file():
            raise ValueError(
                f"External model data is missing: {path}; keep the OSM with its companion workflow and files"
            )
        if path in planned:
            return planned[path]
        total_bytes += path.stat().st_size
        if total_bytes > max_resource_bytes:
            raise ValueError(
                f"Model resources exceed remaining workspace quota ({max_resource_bytes} bytes)"
            )
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        prefix = digest.hexdigest()[:12] + "-"
        destination = files / (
            path.name if path.name.startswith(prefix) else prefix + path.name
        )
        planned[path] = destination
        return destination

    for obj in model.getExternalFiles():
        path = Path(str(obj.filePath()))
        if not path.is_file():
            raise ValueError(
                f"Cannot resolve external file {obj.fileName()!r} for {source}; attach the companion workflow or restore its files"
            )
        external.append((obj, plan_file(path)))
    weather = None
    if copy_weather:
        lookup = model.workflowJSON()
        if lookup.weatherFile().is_initialized():
            found = lookup.findFile(lookup.weatherFile().get())
            if found.is_initialized():
                weather = Path(str(found.get()))
        if weather is None:
            raw = model.getWeatherFile().path()
            if raw.is_initialized():
                candidate = Path(str(raw.get()))
                candidate = (
                    candidate if candidate.is_absolute() else source.parent / candidate
                )
                if candidate.is_file():
                    weather = candidate
    weather_target = plan_file(weather) if weather else None
    files.mkdir(parents=True, exist_ok=True)
    for path, destination in planned.items():
        shutil.copy2(path, destination)
    for obj, destination in external:
        index = next(
            i
            for i in range(obj.numFields())
            if "File Name" in obj.iddObject().getField(i).get().name()
        )
        if not obj.setString(index, str(destination.resolve())):
            raise ValueError("SDK rejected copied external filename")
    payload = {"seed_file": "../" + target.name, "file_paths": ["files"], "steps": []}
    if weather_target:
        obj = sdk.model.WeatherFile.setWeatherFile(
            model, sdk.EpwFile(str(weather_target))
        ).get()
        index = next(
            i
            for i in range(obj.numFields())
            if obj.iddObject().getField(i).get().name() == "Url"
        )
        if not obj.setString(index, str(weather_target.resolve())):
            raise ValueError("SDK rejected copied weather URL")
        payload["weather_file"] = "files/" + weather_target.name
    (directory / "workflow.osw").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    if not model.save(str(target), True):
        raise ValueError("SDK could not save model with copied resources")
    return [directory.name + "/files"]
