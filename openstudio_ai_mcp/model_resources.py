"""Preserve external model data in snapshots and isolated simulation workspaces."""

from pathlib import Path
import json
import shutil


def copy_model_resources(source: Path, target: Path) -> list[str]:
    """Never execute source measures. Return file lookup roots for the copied model."""
    workflow = source.with_suffix("") / "workflow.osw"
    if not workflow.is_file() and b"OS:External:File," not in source.read_bytes():
        return []
    import openstudio as sdk

    loaded = sdk.osversion.VersionTranslator().loadModel(str(source))
    if not loaded.is_initialized():
        raise ValueError(f"Could not load model resources: {source}")
    model = loaded.get()
    if workflow.is_file():
        model.setWorkflowJSON(sdk.WorkflowJSON(str(workflow)))
    else:
        model.workflowJSON().setOswPath(str(source.with_suffix(".osw")))
    directory = target.with_suffix("")
    files = directory / "files"
    copied = {}

    def copy(path):
        path = path.resolve()
        if not path.is_file():
            raise ValueError(
                f"External model data is missing: {path}; keep the OSM with its companion workflow and files"
            )
        destination = files / path.name
        if destination.name in copied and copied[destination.name] != path:
            raise ValueError(f"External model data filename collision: {path.name}")
        files.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied[destination.name] = path
        return destination

    for obj in model.getExternalFiles():
        path = Path(str(obj.filePath()))
        if not path.is_file():
            raise ValueError(
                f"Cannot resolve external file {obj.fileName()!r} for {source}; attach the companion workflow or restore its files"
            )
        destination = copy(path)
        index = next(
            i
            for i in range(obj.numFields())
            if "File Name" in obj.iddObject().getField(i).get().name()
        )
        if not obj.setString(index, destination.name):
            raise ValueError("SDK rejected copied external filename")
    weather = None
    if workflow.is_file():
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
    payload = {"seed_file": "../" + target.name, "file_paths": ["files"], "steps": []}
    if weather:
        destination = copy(weather)
        obj = sdk.model.WeatherFile.setWeatherFile(
            model, sdk.EpwFile(str(destination))
        ).get()
        index = next(
            i
            for i in range(obj.numFields())
            if obj.iddObject().getField(i).get().name() == "Url"
        )
        if not obj.setString(
            index, str(Path(directory.name) / "files" / destination.name)
        ):
            raise ValueError("SDK rejected copied weather URL")
        payload["weather_file"] = "files/" + destination.name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "workflow.osw").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    if not model.save(str(target), True):
        raise ValueError("SDK could not save model with copied resources")
    return [directory.name + "/files"]
