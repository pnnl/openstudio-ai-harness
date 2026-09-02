from pathlib import Path

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
    artifact = service.artifacts.must_get(result["viewer_id"])
    assert artifact.kind == "geometry_viewer_html"
    assert artifact.parent_id == loaded["model_id"]


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
