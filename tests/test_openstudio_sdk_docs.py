"""Tests for OpenStudioSdkDocLookup backed by gzip YAML documentation."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
import yaml

from openstudio_mcp.sdk_docs.lookup import (
    OpenStudioSdkDocLookup,
    SdkDocsUnavailableError,
)


def _write_classes_gz(path: Path, classes: dict) -> None:
    """Write a minimal classes.yaml.gz under path/api/classes.yaml.gz."""
    (path / "api").mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {"total_classes": len(classes), "openstudio_version": "3.7.0"},
        "namespaces": {
            "openstudio::model": {
                "class_count": len(classes),
                "classes": classes,
            }
        },
    }
    (path / "api" / "classes.yaml.gz").write_bytes(
        gzip.compress(yaml.dump(payload, allow_unicode=True).encode())
    )


def _minimal_class(
    name: str,
    methods: list[dict] | None = None,
    description: str | None = None,
) -> dict:
    return {
        "name": name,
        "namespace": "openstudio::model",
        "description": description or f"{name} class.",
        "python": f"openstudio.model.{name}",
        "parent": None,
        "derived_classes": [],
        "is_abstract": False,
        "file_location": f"{name}.hpp",
        "public_methods": methods or [],
        "protected_methods": [],
        "static_methods": [],
        "public_types": [],
    }


def test_available_returns_false_when_docs_dir_missing(tmp_path: Path):
    lookup = OpenStudioSdkDocLookup(tmp_path / "nonexistent")
    assert not lookup.available()


def test_available_returns_false_when_classes_gz_absent(tmp_path: Path):
    (tmp_path / "api").mkdir()
    lookup = OpenStudioSdkDocLookup(tmp_path)
    assert not lookup.available()


def test_available_returns_true_when_classes_gz_present(tmp_path: Path):
    _write_classes_gz(tmp_path, {})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    assert lookup.available()


def test_find_classes_exact_match(tmp_path: Path):
    _write_classes_gz(tmp_path, {"PlanarSurface": _minimal_class("PlanarSurface")})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    results = lookup.find_classes("PlanarSurface")
    assert len(results) == 1
    assert results[0]["class_name"] == "PlanarSurface"


def test_find_classes_substring_match(tmp_path: Path):
    _write_classes_gz(
        tmp_path,
        {
            "AirLoopHVAC": _minimal_class("AirLoopHVAC"),
            "AirLoopHVACOutdoorAirSystem": _minimal_class(
                "AirLoopHVACOutdoorAirSystem"
            ),
            "Space": _minimal_class("Space"),
        },
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    results = lookup.find_classes("AirLoop")
    names = [r["class_name"] for r in results]
    assert "AirLoopHVAC" in names
    assert "AirLoopHVACOutdoorAirSystem" in names
    assert "Space" not in names


def test_find_classes_returns_empty_for_unknown(tmp_path: Path):
    _write_classes_gz(tmp_path, {"Space": _minimal_class("Space")})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    assert lookup.find_classes("NonExistentClass") == []


def test_find_classes_excludes_impl_by_default(tmp_path: Path):
    _write_classes_gz(
        tmp_path,
        {
            "Space": _minimal_class("Space"),
            "Space_Impl": _minimal_class("Space_Impl"),
        },
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    names = [r["class_name"] for r in lookup.find_classes("Space")]
    assert "Space_Impl" not in names


def test_find_classes_includes_impl_when_requested(tmp_path: Path):
    _write_classes_gz(
        tmp_path,
        {
            "Space": _minimal_class("Space"),
            "Space_Impl": _minimal_class("Space_Impl"),
        },
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    names = [r["class_name"] for r in lookup.find_classes("Space", include_detail=True)]
    assert "Space_Impl" in names


def test_find_classes_limit_is_respected(tmp_path: Path):
    classes = {f"ClassNum{i}": _minimal_class(f"ClassNum{i}") for i in range(20)}
    _write_classes_gz(tmp_path, classes)
    lookup = OpenStudioSdkDocLookup(tmp_path)
    assert len(lookup.find_classes("ClassNum", limit=5)) == 5


def test_list_methods_returns_all_methods(tmp_path: Path):
    methods = [
        {
            "name": "azimuth",
            "signature": "double azimuth() const",
            "description": "Returns azimuth.",
        },
        {
            "name": "tilt",
            "signature": "double tilt() const",
            "description": "Returns tilt.",
        },
    ]
    _write_classes_gz(
        tmp_path, {"PlanarSurface": _minimal_class("PlanarSurface", methods)}
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.list_methods("PlanarSurface")
    assert result["total_matches"] == 2
    assert result["class_name"] == "PlanarSurface"


def test_list_methods_keyword_filter(tmp_path: Path):
    methods = [
        {"name": "azimuth", "signature": "double azimuth() const", "description": None},
        {"name": "tilt", "signature": "double tilt() const", "description": None},
    ]
    _write_classes_gz(
        tmp_path, {"PlanarSurface": _minimal_class("PlanarSurface", methods)}
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.list_methods("PlanarSurface", keyword="azimuth")
    assert result["total_matches"] == 1
    assert result["methods"][0]["name"] == "azimuth"


def test_list_methods_raises_for_unknown_class(tmp_path: Path):
    _write_classes_gz(tmp_path, {})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    with pytest.raises(KeyError):
        lookup.list_methods("Nonexistent")


def test_list_methods_limit_clamped_to_200(tmp_path: Path):
    methods = [
        {"name": f"method{i}", "signature": f"void method{i}()", "description": None}
        for i in range(250)
    ]
    _write_classes_gz(tmp_path, {"BigClass": _minimal_class("BigClass", methods)})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.list_methods("BigClass", limit=10_000)
    assert len(result["methods"]) == 200


def test_get_method_returns_signature_and_docs(tmp_path: Path):
    methods = [
        {
            "name": "azimuth",
            "signature": "double azimuth() const",
            "python_signature": "azimuth() -> float",
            "description": "Returns the surface azimuth in radians.",
        }
    ]
    _write_classes_gz(
        tmp_path, {"PlanarSurface": _minimal_class("PlanarSurface", methods)}
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.get_method("PlanarSurface", "azimuth")
    assert "double azimuth()" in result["signature"]
    assert result["python_signature"] == "azimuth() -> float"
    assert "radians" in result["documentation"]


def test_get_method_adds_radians_note(tmp_path: Path):
    methods = [
        {
            "name": "azimuth",
            "signature": "double azimuth() const",
            "description": "Returns azimuth in radians.",
        }
    ]
    _write_classes_gz(
        tmp_path, {"PlanarSurface": _minimal_class("PlanarSurface", methods)}
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.get_method("PlanarSurface", "azimuth")
    assert any("radians" in note for note in result["notes"])


def test_get_method_adds_optional_note_from_signature(tmp_path: Path):
    methods = [
        {
            "name": "defaultScheduleSet",
            "signature": "boost::optional< DefaultScheduleSet > defaultScheduleSet() const",
            "description": "Returns the default schedule set.",
        }
    ]
    _write_classes_gz(tmp_path, {"Space": _minimal_class("Space", methods)})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.get_method("Space", "defaultScheduleSet")
    assert any("is_initialized()" in note for note in result["notes"])


def test_get_method_raises_for_unknown_method(tmp_path: Path):
    _write_classes_gz(tmp_path, {"Space": _minimal_class("Space", [])})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    with pytest.raises(KeyError):
        lookup.get_method("Space", "nonExistentMethod")


def test_get_method_signature_contains_disambiguates_overloads(tmp_path: Path):
    methods = [
        {
            "name": "setEconomizerMaximumLimitDryBulbTemperature",
            "signature": "bool setEconomizerMaximumLimitDryBulbTemperature(double temperature)",
            "description": "Sets the limit.",
        },
        {
            "name": "setEconomizerMaximumLimitDryBulbTemperature",
            "signature": "bool setEconomizerMaximumLimitDryBulbTemperature(const Quantity& temperature)",
            "description": "Sets the limit from a Quantity.",
        },
    ]
    _write_classes_gz(
        tmp_path,
        {"ControllerOutdoorAir": _minimal_class("ControllerOutdoorAir", methods)},
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.get_method(
        "ControllerOutdoorAir",
        "setEconomizerMaximumLimitDryBulbTemperature",
        signature_contains="Quantity",
    )
    assert "Quantity" in result["signature"]
    assert len(result["overloads"]) == 2


def test_get_method_overloads_list_contains_all_variants(tmp_path: Path):
    methods = [
        {
            "name": "addBranchForZone",
            "signature": "bool addBranchForZone(ThermalZone& zone)",
            "description": None,
        },
        {
            "name": "addBranchForZone",
            "signature": "bool addBranchForZone(ThermalZone& zone, HVACComponent& terminal)",
            "description": None,
        },
    ]
    _write_classes_gz(tmp_path, {"AirLoopHVAC": _minimal_class("AirLoopHVAC", methods)})
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.get_method("AirLoopHVAC", "addBranchForZone")
    assert len(result["overloads"]) == 2


def test_search_methods_finds_across_classes(tmp_path: Path):
    _write_classes_gz(
        tmp_path,
        {
            "Space": _minimal_class(
                "Space",
                [
                    {
                        "name": "setName",
                        "signature": "bool setName(const std::string&)",
                        "description": None,
                    }
                ],
            ),
            "ThermalZone": _minimal_class(
                "ThermalZone",
                [
                    {
                        "name": "setName",
                        "signature": "bool setName(const std::string&)",
                        "description": None,
                    }
                ],
            ),
        },
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    results = lookup.search_methods("setName")
    class_names = {r["class_name"] for r in results}
    assert "Space" in class_names
    assert "ThermalZone" in class_names


def test_search_methods_class_filter(tmp_path: Path):
    _write_classes_gz(
        tmp_path,
        {
            "Space": _minimal_class(
                "Space",
                [
                    {
                        "name": "setName",
                        "signature": "bool setName(const std::string&)",
                        "description": None,
                    }
                ],
            ),
            "ThermalZone": _minimal_class(
                "ThermalZone",
                [
                    {
                        "name": "setName",
                        "signature": "bool setName(const std::string&)",
                        "description": None,
                    }
                ],
            ),
        },
    )
    lookup = OpenStudioSdkDocLookup(tmp_path)
    results = lookup.search_methods("setName", class_filter="Space")
    assert all(r["class_name"] == "Space" for r in results)


def test_search_methods_clamps_large_limit(tmp_path: Path):
    methods = [
        {"name": f"method{i}", "signature": f"void method{i}()", "description": None}
        for i in range(250)
    ]
    _write_classes_gz(tmp_path, {"Model": _minimal_class("Model", methods)})
    results = OpenStudioSdkDocLookup(tmp_path).search_methods("", limit=10_000)
    assert len(results) == 100


def test_search_methods_empty_keyword_returns_all_up_to_limit(tmp_path: Path):
    methods = [
        {"name": f"doThing{i}", "signature": f"void doThing{i}()", "description": None}
        for i in range(10)
    ]
    _write_classes_gz(tmp_path, {"MyClass": _minimal_class("MyClass", methods)})
    results = OpenStudioSdkDocLookup(tmp_path).search_methods("", limit=5)
    assert len(results) == 5


def test_route_returns_geometry_wiki_packs(tmp_path: Path):
    # route() is deterministic and does not require local YAML files.
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.route("Compute WWR by orientation from exterior wall azimuths")
    assert "sdk_geometry" in result["wiki_packs"]
    assert "PlanarSurface" in result["classes"]


def test_route_returns_hvac_classes_for_air_loop_query(tmp_path: Path):
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.route("create an air loop with outdoor air controller and fan")
    assert "AirLoopHVAC" in result["classes"]


def test_route_returns_empty_domains_for_unrelated_query(tmp_path: Path):
    lookup = OpenStudioSdkDocLookup(tmp_path)
    result = lookup.route("what is the capital of France")
    assert result["domains"] == []


def test_ensure_available_raises_when_docs_missing(tmp_path: Path):
    lookup = OpenStudioSdkDocLookup(tmp_path / "missing")
    with pytest.raises(SdkDocsUnavailableError):
        lookup.find_classes("Space")


def test_from_env_falls_back_to_bundled_docs_for_invalid_override(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("OPENSTUDIO_SDK_DOCS_DIR", str(tmp_path / "missing"))

    with pytest.warns(UserWarning, match="using the bundled SDK documentation"):
        lookup = OpenStudioSdkDocLookup.from_env()

    assert lookup.source == "bundled_fallback"
    assert lookup.override_path == (tmp_path / "missing").resolve()
    assert lookup.available()
    assert lookup.find_classes("ThermalZone")


def test_bundled_docs_are_available():
    """The bundled YAML files must be importable without any env override."""
    lookup = OpenStudioSdkDocLookup()
    assert lookup.available(), (
        "Bundled SDK docs not found. "
        "Expected openstudio_mcp/sdk_docs/docs/api/classes.yaml.gz to exist."
    )


def test_bundled_docs_contain_airloophvac():
    lookup = OpenStudioSdkDocLookup()
    results = lookup.find_classes("AirLoopHVAC")
    names = [r["class_name"] for r in results]
    assert "AirLoopHVAC" in names


def test_bundled_docs_list_methods_for_airloophvac():
    lookup = OpenStudioSdkDocLookup()
    result = lookup.list_methods("AirLoopHVAC", keyword="addBranchForZone")
    assert result["total_matches"] >= 1


def test_bundled_docs_get_method_returns_signature():
    lookup = OpenStudioSdkDocLookup()
    result = lookup.get_method("AirLoopHVAC", "addBranchForZone")
    assert result["signature"] is not None
    assert "ThermalZone" in result["signature"]
