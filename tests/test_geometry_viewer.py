import json
import sqlite3
from pathlib import Path

import openstudio
import pytest

from openstudio_mcp.geometry_viewer import build_geometry_scene
from openstudio_mcp.geometry_viewer import render_geometry_viewer_html
import openstudio_mcp.server as mcp_server
from openstudio_mcp.server import OpenStudioService
from openstudio_mcp.runtime.state_store import RuntimeStateStore
from openstudio_mcp.tools.schemas import (
    ModelExportGeometryViewerArgs,
    ModelLoadArgs,
)

FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "sample.osm"


def test_state_store_migrates_and_backfills_legacy_artifact_ownership(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime-state.sqlite3"
    legacy_metadata = {"job_id": "legacy-job", "workspace_id": "legacy-workspace"}
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                parent_id TEXT,
                kind TEXT NOT NULL,
                tool_trace_id TEXT,
                metadata_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'available',
                pinned INTEGER NOT NULL DEFAULT 0,
                last_accessed_at TEXT NOT NULL
            )
            """)
        conn.execute(
            """
            INSERT INTO artifacts (
                artifact_id, created_at, parent_id, kind, tool_trace_id,
                metadata_json, status, pinned, last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-artifact",
                "2026-01-01T00:00:00+00:00",
                None,
                "simulation_sql",
                None,
                json.dumps(legacy_metadata),
                "available",
                0,
                "2026-01-01T00:00:00+00:00",
            ),
        )

    store = RuntimeStateStore(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)")}
        ownership = conn.execute(
            "SELECT job_id, workspace_id FROM artifacts WHERE artifact_id = ?",
            ("legacy-artifact",),
        ).fetchone()

    assert {"job_id", "workspace_id"} <= columns
    assert ownership == ("legacy-job", "legacy-workspace")
    assert store.get_artifact_ids_for_job("legacy-job") == {"legacy-artifact"}
    assert store.get_artifact_ids_for_workspace("legacy-workspace") == {
        "legacy-artifact"
    }


def test_model_export_geometry_viewer_writes_searchable_offline_html(
    tmp_path: Path,
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )

    result = service.model_export_geometry_viewer(
        ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
    )

    assert result["ok"] is True
    assert result["counts"]["spaces"] == 6
    assert result["counts"]["faces"] > 0
    viewer_path = Path(result["viewer_path"])
    assert viewer_path.exists()
    assert viewer_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    html = viewer_path.read_text(encoding="utf-8")
    assert "Search spaces" in html
    assert "Sort spaces" in html
    assert "click any surface for details" in html
    assert "Surface type:" in html
    assert "Belongs to:" in html
    assert "resetPitch=.65" in html
    assert html.count("<script>") == 1
    assert "function normal" in html
    assert "function visible" in html
    assert "function inside" in html
    assert "function faces" in html
    assert "canvas.onkeydown" in html
    assert "Arrow keys orbit" in html
    assert "No visible surfaces." in html
    assert "canvas.tabIndex=0" in html
    assert 'aria-label="Surfaces"' in html
    assert 'id="detail" role="status" aria-live="polite"' in html
    assert 'button type="button" class="space' in html
    assert "function listSurfaces" in html
    assert "byId=new Map" in html
    assert "function applyFilter" in html
    assert (
        "#layout{display:grid;grid-template-columns:320px 1fr;height:calc(100vh - 58px)"
        in html
    )
    assert "@media(max-width:700px)" in html
    assert "baseDraw" not in html
    assert "renderList=function" not in html
    artifact = service.artifacts.must_get(result["viewer_id"])
    assert artifact.kind == "geometry_viewer_html"
    assert artifact.parent_id == loaded["model_id"]
    workspace = next(
        record
        for record in service.state_store.list_workspaces()
        if record.kind == "geometry_viewer"
    )
    assert workspace.metadata["include_subsurfaces"] is True
    assert workspace.metadata["include_shading"] is True

    scene = build_geometry_scene(
        openstudio.osversion.VersionTranslator().loadModel(str(FIXTURE_MODEL)).get(),
        source_model="sample.osm",
        include_subsurfaces=False,
        include_shading=False,
    )
    assert scene["include_subsurfaces"] is False
    assert scene["include_shading"] is False


def test_geometry_viewer_escapes_all_model_text_tag_delimiters() -> None:
    html = render_geometry_viewer_html(
        {
            "source_model": "</ScRiPt><script>window.injected=true</script>",
            "counts": {"spaces": 0, "stories": 0, "faces": 0},
            "warnings": [],
            "bounds": [0, 0, 0, 1, 1, 1],
            "spaces": [],
            "faces": [],
        }
    )

    assert "</ScRiPt>" not in html
    assert "\\u003c/ScRiPt>" in html


def test_geometry_scene_warns_for_collinear_surface() -> None:
    class Point:
        def __init__(self, value: float):
            self.value = value

        def x(self) -> float:
            return self.value

        def y(self) -> float:
            return self.value

        def z(self) -> float:
            return self.value

    class Unassigned:
        def is_initialized(self) -> bool:
            return False

    class Surface:
        def vertices(self) -> list[Point]:
            return [Point(0), Point(1), Point(2)]

        def handle(self) -> str:
            return "collinear-surface"

        def nameString(self) -> str:
            return "Collinear surface"

        def surfaceType(self) -> str:
            return "Wall"

        def grossArea(self) -> float:
            return 0.0

        def outsideBoundaryCondition(self) -> str:
            return "Outdoors"

        def subSurfaces(self) -> list[object]:
            return []

    class Space:
        def handle(self) -> str:
            return "degenerate-space"

        def nameString(self) -> str:
            return "Degenerate space"

        def buildingStory(self) -> Unassigned:
            return Unassigned()

        def thermalZone(self) -> Unassigned:
            return Unassigned()

        def spaceType(self) -> Unassigned:
            return Unassigned()

        def floorArea(self) -> float:
            return 0.0

        def volume(self) -> float:
            return 0.0

        def surfaces(self) -> list[Surface]:
            return [Surface()]

        def siteTransformation(self) -> None:
            return None

    class Model:
        def getSpaces(self) -> list[Space]:
            return [Space()]

        def getShadingSurfaces(self) -> list[object]:
            return []

    scene = build_geometry_scene(
        Model(),
        source_model="degenerate.osm",
        include_subsurfaces=False,
        include_shading=False,
    )

    assert scene["faces"] == []
    assert scene["warnings"] == ["Skipped invalid surface: Collinear surface"]


def test_geometry_viewer_runs_in_a_browser_and_supports_selection(
    tmp_path: Path,
) -> None:
    from playwright.sync_api import sync_playwright

    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )
    exported = service.model_export_geometry_viewer(
        ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
    )
    errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.goto(Path(exported["viewer_path"]).as_uri())

            page.locator("#spaces").get_by_role("button", name="Core_ZN").click()
            assert "Core_ZN" in page.locator("#detail").inner_text()
            assert page.locator("#spaces [aria-pressed='true']").evaluate(
                "button => document.activeElement === button"
            )

            page.get_by_role(
                "button", name="Perimeter_ZN_1_wall_south_Window_1"
            ).click()
            assert "Surface type:" in page.locator("#detail").inner_text()
            page.locator("#sub").uncheck()
            assert not page.locator("#detail").is_visible()

            page.locator("#canvas").press("ArrowRight")
            page.locator("#story").select_option("Building Story 1")
            assert "Attic" not in page.locator("#spaces").inner_text()
            assert page.locator("#surface-list li[hidden]").count() > 0
            page.get_by_role("button", name="Show all spaces").click()
            assert "Attic" in page.locator("#spaces").inner_text()
            assert errors == []
        finally:
            browser.close()


def test_geometry_viewer_honors_optional_face_categories(tmp_path: Path) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )

    full = service.model_export_geometry_viewer(
        ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
    )
    opaque_only = service.model_export_geometry_viewer(
        ModelExportGeometryViewerArgs(
            model_id=loaded["model_id"],
            include_subsurfaces=False,
            include_shading=False,
        )
    )

    assert opaque_only["counts"]["spaces"] == full["counts"]["spaces"]
    assert opaque_only["counts"]["faces"] < full["counts"]["faces"]


def test_geometry_scene_uses_site_coordinates_for_spaces_and_shading() -> None:
    loaded = openstudio.osversion.VersionTranslator().loadModel(str(FIXTURE_MODEL))
    assert loaded.is_initialized()
    model = loaded.get()
    space = model.getSpaces()[0]
    space.setXOrigin(10.0)
    space.setYOrigin(-4.0)
    space.setDirectionofRelativeNorth(20.0)
    surface = space.surfaces()[0]
    expected = space.siteTransformation() * surface.vertices()[0]

    group = openstudio.model.ShadingSurfaceGroup(model)
    group.setTransformation(
        openstudio.Transformation.translation(openstudio.Vector3d(30, 0, 0))
    )
    shading = openstudio.model.ShadingSurface(
        [
            openstudio.Point3d(0, 0, 0),
            openstudio.Point3d(2, 0, 0),
            openstudio.Point3d(0, 2, 0),
        ],
        model,
    )
    shading.setName("Translated shading")
    assert shading.setShadingSurfaceGroup(group)

    scene = build_geometry_scene(
        model,
        source_model="transformed.osm",
        include_subsurfaces=True,
        include_shading=True,
    )

    exported_surface = next(
        face for face in scene["faces"] if face["id"] == str(surface.handle())
    )
    assert exported_surface["vertices"][0] == pytest.approx(
        [expected.x(), expected.y(), expected.z()]
    )
    exported_shading = next(
        face for face in scene["faces"] if face["id"] == str(shading.handle())
    )
    assert exported_shading["surface_type"] == "Shading"
    assert exported_shading["vertices"][0] == pytest.approx([30.0, 0.0, 0.0])


def test_geometry_viewer_quota_failure_cleans_workspace_before_publishing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )
    original_ensure_quota = service.workspace_manager.ensure_quota
    calls = 0

    def fail_after_workspace_creation(workspace_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise ValueError("Workspace quota exceeded for test")
        original_ensure_quota(workspace_id)

    monkeypatch.setattr(
        service.workspace_manager, "ensure_quota", fail_after_workspace_creation
    )

    with pytest.raises(ValueError, match="quota exceeded"):
        service.model_export_geometry_viewer(
            ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
        )

    workspace = next(
        record
        for record in service.state_store.list_workspaces()
        if record.kind == "geometry_viewer"
    )
    assert workspace.status == "failed"
    assert not Path(workspace.path).exists()
    assert not any(
        artifact.kind == "geometry_viewer_html"
        for artifact in service.artifacts._items.values()
    )


def test_geometry_viewer_publication_failure_discards_artifact_and_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )
    original_register = service._register_workspace
    calls = 0

    def fail_final_registration(**kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("SQLite persistence failed for test")
        original_register(**kwargs)

    monkeypatch.setattr(service, "_register_workspace", fail_final_registration)

    with pytest.raises(RuntimeError, match="persistence failed"):
        service.model_export_geometry_viewer(
            ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
        )

    workspace = next(
        record
        for record in service.state_store.list_workspaces()
        if record.kind == "geometry_viewer"
    )
    assert workspace.status == "failed"
    assert not Path(workspace.path).exists()
    assert not any(
        artifact.kind == "geometry_viewer_html"
        for artifact in service.artifacts._items.values()
    )


def test_geometry_viewer_cleanup_runs_when_artifact_rollback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )
    original_register = service._register_workspace
    original_discard = service.artifacts.discard
    calls = 0

    def fail_final_registration(**kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("final registration failed")
        original_register(**kwargs)

    def fail_artifact_rollback(*_args, **_kwargs) -> None:
        raise RuntimeError("artifact rollback failed")

    monkeypatch.setattr(service, "_register_workspace", fail_final_registration)
    monkeypatch.setattr(service.artifacts, "discard", fail_artifact_rollback)

    with pytest.raises(RuntimeError, match="final registration failed"):
        service.model_export_geometry_viewer(
            ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
        )

    workspace = next(
        record
        for record in service.state_store.list_workspaces()
        if record.kind == "geometry_viewer"
    )
    assert workspace.status == "failed"
    assert Path(workspace.path).exists()
    artifact_ids = service.state_store.get_artifact_ids_for_workspace(
        workspace.workspace_id
    )
    assert len(artifact_ids) == 1

    monkeypatch.setattr(service.artifacts, "discard", original_discard)
    service.runtime_prune(
        workspace_ids=[workspace.workspace_id],
        include_measure_workspaces=False,
        include_geometry_viewers=True,
        include_failed_simulations=False,
    )

    assert not Path(workspace.path).exists()
    artifact_id = artifact_ids.pop()
    assert service.artifacts.get(artifact_id) is None
    assert service.state_store.get_artifact(artifact_id)["status"] == "pruned"


def test_runtime_prune_keeps_workspace_when_artifact_tombstone_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    workspace_id = "geometry-prune-retry"
    workspace = service.workspace_manager.create_workspace(workspace_id)
    viewer_path = workspace / "geometry-viewer.html"
    viewer_path.write_text("viewer", encoding="utf-8")
    artifact = service.artifacts.create(
        kind="geometry_viewer_html",
        metadata={"path": str(viewer_path), "workspace_id": workspace_id},
    )
    service._register_workspace(
        workspace_id=workspace_id,
        kind="geometry_viewer",
        model_id="model-id",
        artifact_id=artifact.artifact_id,
        status="available",
    )
    original_discard = service.artifacts.discard

    def fail_tombstone(*_args, **_kwargs) -> None:
        raise RuntimeError("artifact tombstone failed")

    monkeypatch.setattr(service.artifacts, "discard", fail_tombstone)
    with pytest.raises(RuntimeError, match="artifact tombstone failed"):
        service.runtime_prune(
            workspace_ids=[workspace_id],
            include_measure_workspaces=False,
            include_geometry_viewers=True,
            include_failed_simulations=False,
        )

    assert workspace.exists()
    assert (
        next(
            record
            for record in service.state_store.list_workspaces()
            if record.workspace_id == workspace_id
        ).status
        == "available"
    )
    assert (
        service.state_store.get_artifact(artifact.artifact_id)["status"] == "available"
    )

    monkeypatch.setattr(service.artifacts, "discard", original_discard)
    service.runtime_prune(
        workspace_ids=[workspace_id],
        include_measure_workspaces=False,
        include_geometry_viewers=True,
        include_failed_simulations=False,
    )
    assert not workspace.exists()
    assert service.state_store.get_artifact(artifact.artifact_id)["status"] == "pruned"


def test_resolve_model_path_normalizes_encoded_windows_drive_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)

    class CapturedPath:
        def __init__(self, value: str):
            self.value = value

        def resolve(self) -> str:
            return self.value

    def encoded_drive_path(path: str) -> str:
        assert path == "/C%3A/Models/sample.osm"
        return r"\C:\Models\sample.osm"

    monkeypatch.setattr(mcp_server, "Path", CapturedPath)
    monkeypatch.setattr(mcp_server, "url2pathname", encoded_drive_path)
    monkeypatch.setattr(mcp_server.os, "name", "nt")

    assert (
        service._resolve_model_path("file:///C%3A/Models/sample.osm")
        == r"C:\Models\sample.osm"
    )


def test_interrupted_geometry_export_cleans_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )

    def interrupt_export(_scene) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(mcp_server, "render_geometry_viewer_html", interrupt_export)

    with pytest.raises(KeyboardInterrupt):
        service.model_export_geometry_viewer(
            ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
        )

    workspace = next(
        record
        for record in service.state_store.list_workspaces()
        if record.kind == "geometry_viewer"
    )
    assert workspace.status == "failed"
    assert not Path(workspace.path).exists()


def test_interrupted_geometry_export_discards_published_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    loaded = service.model_load(
        ModelLoadArgs(model_uri=FIXTURE_MODEL.resolve().as_uri())
    )
    original_register = service._register_workspace
    original_create = service.artifacts.create
    calls = 0
    artifact_id: str | None = None

    def remember_artifact(**kwargs):
        nonlocal artifact_id
        artifact = original_create(**kwargs)
        artifact_id = artifact.artifact_id
        return artifact

    def interrupt_final_registration(**kwargs) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        original_register(**kwargs)

    monkeypatch.setattr(service.artifacts, "create", remember_artifact)
    monkeypatch.setattr(service, "_register_workspace", interrupt_final_registration)

    with pytest.raises(KeyboardInterrupt):
        service.model_export_geometry_viewer(
            ModelExportGeometryViewerArgs(model_id=loaded["model_id"])
        )

    assert artifact_id is not None
    assert service.artifacts.get(artifact_id) is None
    assert service.state_store.get_artifact(artifact_id)["status"] == "failed"
    workspace = next(
        record
        for record in service.state_store.list_workspaces()
        if record.kind == "geometry_viewer"
    )
    assert workspace.status == "failed"
    assert not Path(workspace.path).exists()


def test_runtime_prune_discards_unlinked_geometry_viewer_artifact(
    tmp_path: Path,
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    workspace_id = "geometry-interrupted"
    workspace = service.workspace_manager.create_workspace(workspace_id)
    viewer_path = workspace / "geometry-viewer.html"
    viewer_path.write_text("viewer", encoding="utf-8")
    artifact = service.artifacts.create(
        kind="geometry_viewer_html",
        metadata={"path": str(viewer_path), "workspace_id": workspace_id},
    )
    service._register_workspace(
        workspace_id=workspace_id,
        kind="geometry_viewer",
        model_id="model-id",
        status="available",
    )

    service.runtime_prune(
        include_measure_workspaces=False,
        include_geometry_viewers=True,
        include_failed_simulations=False,
    )

    assert not workspace.exists()
    assert service.artifacts.get(artifact.artifact_id) is None
    assert service.state_store.get_artifact(artifact.artifact_id)["status"] == "pruned"


def test_runtime_prune_discards_every_successful_simulation_artifact(
    tmp_path: Path,
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    job = service.job_manager.create_job(
        model_id="simulation-model", run_mode="annual", options={}
    )
    workspace = service.workspace_manager.workspace_path(job.job_id)
    (workspace / "eplusout.sql").write_text("simulation output", encoding="utf-8")
    osm = service.artifacts.create(
        kind="osm", parent_id="simulation-model", metadata={"job_id": job.job_id}
    )
    sql = service.artifacts.create(
        kind="sql", parent_id=osm.artifact_id, metadata={"job_id": job.job_id}
    )
    logs = service.artifacts.create(
        kind="logs", parent_id=osm.artifact_id, metadata={"job_id": job.job_id}
    )
    report = service.artifacts.create(
        kind="report", parent_id=sql.artifact_id, metadata={"job_id": job.job_id}
    )
    artifacts = {
        "osm_id": osm.artifact_id,
        "sql_id": sql.artifact_id,
        "logs_id": logs.artifact_id,
        "report_id": report.artifact_id,
    }
    service.job_manager.mark_succeeded(job.job_id, artifacts=artifacts)
    service._register_workspace(
        workspace_id=job.job_id,
        kind="simulation",
        job_id=job.job_id,
        model_id="simulation-model",
        artifact_id=osm.artifact_id,
        status="succeeded",
    )

    result = service.runtime_prune(
        include_measure_workspaces=False,
        include_geometry_viewers=False,
        include_failed_simulations=False,
        include_successful_simulations=True,
    )

    assert result["deleted"][0]["workspace_id"] == job.job_id
    assert not workspace.exists()
    for artifact_id in artifacts.values():
        assert service.artifacts.get(artifact_id) is None
        assert service.state_store.get_artifact(artifact_id)["status"] == "pruned"


def test_runtime_prune_discards_failed_simulation_artifacts_missing_from_job_map(
    tmp_path: Path,
) -> None:
    service = OpenStudioService(workspace_root=tmp_path)
    job = service.job_manager.create_job(
        model_id="simulation-model", run_mode="annual", options={}
    )
    workspace = service.workspace_manager.workspace_path(job.job_id)
    (workspace / "eplusout.sql").write_text("simulation output", encoding="utf-8")
    osm = service.artifacts.create(
        kind="osm", parent_id="simulation-model", metadata={"job_id": job.job_id}
    )
    sql = service.artifacts.create(
        kind="sql", parent_id=osm.artifact_id, metadata={"job_id": job.job_id}
    )
    logs = service.artifacts.create(
        kind="logs", parent_id=osm.artifact_id, metadata={"job_id": job.job_id}
    )
    report = service.artifacts.create(
        kind="report", parent_id=sql.artifact_id, metadata={"job_id": job.job_id}
    )
    artifacts = [osm.artifact_id, sql.artifact_id, logs.artifact_id, report.artifact_id]
    service.job_manager.fail(job.job_id, error={"message": "quota failure"})
    service._register_workspace(
        workspace_id=job.job_id,
        kind="simulation",
        job_id=job.job_id,
        model_id="simulation-model",
        artifact_id=osm.artifact_id,
        status="failed",
    )

    service.runtime_prune(
        include_measure_workspaces=False,
        include_geometry_viewers=False,
        include_failed_simulations=True,
        include_successful_simulations=False,
    )

    assert not workspace.exists()
    for artifact_id in artifacts:
        assert service.artifacts.get(artifact_id) is None
        assert service.state_store.get_artifact(artifact_id)["status"] == "pruned"
