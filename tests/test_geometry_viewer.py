from pathlib import Path

import openstudio
import pytest

from openstudio_mcp.geometry_viewer import build_geometry_scene
import openstudio_mcp.server as mcp_server
from openstudio_mcp.server import OpenStudioService
from openstudio_mcp.tools.schemas import (
    ModelExportGeometryViewerArgs,
    ModelLoadArgs,
)

FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "sample.osm"


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
    assert "frontFacing" in html
    assert "pointInPolygon" in html
    assert "averageDepth" in html
    assert "face.kind==='shading'||frontFacing(face)" in html
    assert "face.id===selectedFaceId||face.kind==='shading'||frontFacing(face)" in html
    assert "canvas.onkeydown" in html
    assert "Arrow keys orbit" in html
    assert "No visible surfaces." in html
    assert "canvas.tabIndex=0" in html
    assert 'aria-label="Surfaces"' in html
    assert 'button type="button" class="space' in html
    assert "renderSurfaceList" in html
    assert (
        "renderList();draw()"
        not in html.split("renderList=function()", 1)[1].split("const resetYaw", 1)[0]
    )
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

    with pytest.raises(RuntimeError, match="artifact rollback failed"):
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


def test_interrupted_geometry_export_remains_prunable(
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
    assert workspace.status == "available"
    preview = service.runtime_prune_preview()
    assert workspace.workspace_id in {
        item["workspace_id"] for item in preview["candidates"]
    }
