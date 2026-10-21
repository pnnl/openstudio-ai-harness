"""Explicit translation into a stable, exclusively published working copy."""

from pathlib import Path
import re
import shutil
import tempfile

from common.companions import digest, inspect, stage, verify, external_file_status
from common.diagnostics import DiagnosticError, handle_changes, mismatch, type_counts
from common.files import publish
from common.model_preservation import fingerprint
from common.version_guard import (
    PreparationRequired,
    load_model,
    model_version,
    object_types,
    require_sdk,
)


def fields(model):
    # No exclusions, handle substitutions or ignored fields.
    return {str(x.handle()): fingerprint(x) for x in model.modelObjects()}


def stored_objects(path):
    # Provenance counts only: never used by a transaction comparison. Historic
    # schemas cannot be parsed with the current IDD without losing old fields.
    text = path.read_bytes().decode("utf-8", errors="replace")
    text = re.sub(r"!.*", "", text)
    return {
        handle.lower(): kind.replace(":", "_")
        for kind, handle in re.findall(
            r"(?mi)^\s*(OS:[\w:]+)\s*,\s*(\{[0-9a-f-]{36}\})", text
        )
    }


def translator_messages(translator):
    return {
        name: {
            "count": len(getattr(translator, name)()),
            "messages": [x.logMessage()[:240] for x in getattr(translator, name)()][:8],
        }
        for name in ("warnings", "errors")
    }


def prepare(source, output):
    sdk = require_sdk()
    if (
        not source.is_absolute()
        or not source.is_file()
        or source.suffix.lower() != ".osm"
    ):
        raise ValueError("Input must be an existing absolute .osm path")
    original = digest(source)
    version = model_version(source)
    target = str(sdk.openStudioVersion()).split("+")[0]
    try:
        model, translator = load_model(sdk, source)
    except PreparationRequired:
        model, translator = load_model(
            sdk, source, allow_preparation=True, check_stability=False
        )
    else:
        if digest(source) != original:
            raise ValueError("Input changed during preparation")
        return dict(
            ok=True,
            ready=False,
            operation="prepare_model",
            mode="inspect_only",
            status="already_current",
            input_model_path=str(source),
            output_model_path=str(source),
            input_sha256=original,
            output_sha256=original,
            source_version=version,
            target_version=target,
            translator=translator_messages(translator),
            state_patch={},
            validation={"ok": True, "handle_set_stable": True},
            note="Already current and handle-stable; no new model or companions written. This is not a semantic equivalence assertion.",
        )
    from common.files import check_model_paths

    check_model_paths(source, output)
    translated = object_types(model)
    changes = handle_changes(stored_objects(source), translated)
    changes["refactored_by_type"] = type_counts(
        x.newObject().iddObject().name().replace(":", "_")
        for x in translator.refactoredObjects()
    )
    diagnostics = translator_messages(translator)
    if diagnostics["errors"]["count"]:
        raise DiagnosticError(
            "Version translation reported errors", translator=diagnostics
        )
    companions_plan = inspect(model, source, output, sdk)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".prepare-stage-", dir=output.parent
    ) as directory:
        staged = Path(directory) / "prepared.osm"
        companions = Path(directory) / output.stem
        stage(model, sdk, companions_plan, companions)
        expected = fields(model)
        if not model.save(str(staged), True):
            raise RuntimeError("SDK could not save prepared copy")
        saved, _ = load_model(sdk, staged)
        second, _ = load_model(sdk, staged, check_stability=False)
        actual = fields(saved)
        if expected != actual:
            raise mismatch(
                expected, actual, "Prepared copy changed raw object fields on reload"
            )
        if actual != fields(second):
            raise mismatch(
                actual, fields(second), "Prepared copy is not reproducible across loads"
            )
        plain = external_file_status(saved)
        second.workflowJSON().setOswPath(str(companions / "workflow.osw"))
        if not external_file_status(second)["ok"]:
            raise ValueError(
                "Prepared external files do not resolve through companion workflow"
            )
        if digest(source) != original:
            raise ValueError("Input changed before preparation publication")
        verify(companions_plan)
        companion_output = output.with_suffix("")
        companion_output.mkdir()
        try:
            shutil.copytree(companions, companion_output, dirs_exist_ok=True)
            method = publish(staged, output)
        except BaseException:
            shutil.rmtree(companion_output)
            raise
        output_hash = digest(staged)
    lineage = dict(
        source={"path": str(source), "sha256": original, "version": version},
        prepared={"path": str(output), "sha256": output_hash, "version": target},
    )
    return dict(
        ok=True,
        ready=False,
        mode="edit_model",
        operation="prepare_model",
        status="prepared",
        input_model_path=str(source),
        input_sha256=original,
        output_model_path=str(output),
        output_sha256=output_hash,
        source_version=version,
        target_version=target,
        translator=diagnostics,
        object_changes=changes,
        lineage=lineage,
        state_patch={
            "model_preparation": {output_hash: lineage},
            "completed_steps": ["model_preparation"],
            "output_model_path": str(output),
        },
        validation={
            "ok": True,
            "handle_set_stable": True,
            "all_raw_fields_stable": True,
        },
        publication_method=method,
        companion_directory=str(companion_output),
        workflow_path=str(companion_output / "workflow.osw"),
        requires_companion_workflow=not plain["ok"],
        companion_readiness=companions_plan["simulation_ready"],
        warnings=companions_plan["warnings"][:8],
        note="Translation and companion relocation may change model fields and bytes; preparation does not establish semantic equivalence or simulation readiness. Re-inventory and re-preflight this copy.",
    )
