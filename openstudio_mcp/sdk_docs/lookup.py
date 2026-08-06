from __future__ import annotations

import gzip
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


class SdkDocsUnavailableError(RuntimeError):
    """Raised when the bundled OpenStudio SDK YAML documentation is missing."""


_BUNDLED_DOCS_DIR = Path(__file__).parent / "docs"

# The OpenStudio version whose docs are served by default.
# Set to None to auto-detect the latest available versioned files in the docs
# directory (files named classes-<version>.yaml.gz), or set to an explicit
# version string such as "3.10.0" to pin to a specific extraction.
OPENSTUDIO_SDK_DOCS_VERSION: str | None = None


def _resolve_docs_version(docs_dir: Path) -> str | None:
    """Return the version suffix to use for versioned YAML files.

    Resolution order:
    1. If OPENSTUDIO_SDK_DOCS_VERSION is set and the corresponding
       ``classes-<version>.yaml.gz`` exists, use it.
    2. If OPENSTUDIO_SDK_DOCS_VERSION is set but that file is missing, log a
       warning and fall through to auto-detection so callers still get docs.
    3. Scan for ``classes-<version>.yaml.gz`` files and return the
       lexicographically latest version found.
    4. Return None — caller falls back to the legacy unversioned filenames
       ``classes.yaml.gz`` / ``python-api.yaml.gz``.
    """
    api_dir = docs_dir / "api"

    if OPENSTUDIO_SDK_DOCS_VERSION is not None:
        pinned_path = api_dir / f"classes-{OPENSTUDIO_SDK_DOCS_VERSION}.yaml.gz"
        if pinned_path.is_file():
            return OPENSTUDIO_SDK_DOCS_VERSION
        import warnings

        warnings.warn(
            f"OPENSTUDIO_SDK_DOCS_VERSION is set to {OPENSTUDIO_SDK_DOCS_VERSION!r} "
            f"but {pinned_path} was not found. "
            "Falling back to the latest available version.",
            stacklevel=3,
        )

    if not api_dir.is_dir():
        return None

    candidates = sorted(
        p.name[len("classes-") : -len(".yaml.gz")]
        for p in api_dir.glob("classes-*.yaml.gz")
    )
    return candidates[-1] if candidates else None


@dataclass(frozen=True)
class MethodRef:
    """Compact pointer to one documented SDK member function."""

    name: str
    signature: str
    python_signature: str | None
    description: str | None


@dataclass
class ClassDoc:
    """Indexed metadata for one OpenStudio SDK class."""

    class_name: str
    namespace: str
    description: str | None
    python_path: str | None
    parent: str | None
    is_abstract: bool
    methods: list[MethodRef] = field(default_factory=list)


DOMAIN_CLASS_GRAPH: dict[str, dict[str, Any]] = {
    "geometry": {
        "wiki_packs": ["sdk_geometry"],
        "keywords": [
            "azimuth",
            "cardinal",
            "centroid",
            "door",
            "exterior",
            "floor area",
            "geometry",
            "north",
            "orientation",
            "roof",
            "shading",
            "space",
            "story",
            "subsurface",
            "surface",
            "tilt",
            "wall",
            "window",
            "wwr",
        ],
        "classes": [
            "Building",
            "BuildingStory",
            "PlanarSurface",
            "ShadingSurface",
            "Space",
            "SubSurface",
            "Surface",
        ],
    },
    "spaces_zones_loads": {
        "wiki_packs": ["sdk_spaces_zones_loads"],
        "keywords": [
            "area",
            "electric equipment",
            "infiltration",
            "internal load",
            "lights",
            "load",
            "occupancy",
            "people",
            "plenum",
            "space type",
            "thermal zone",
            "ventilation",
            "zone",
        ],
        "classes": [
            "ElectricEquipment",
            "ElectricEquipmentDefinition",
            "Lights",
            "LightsDefinition",
            "People",
            "PeopleDefinition",
            "Space",
            "SpaceInfiltrationDesignFlowRate",
            "SpaceType",
            "ThermalZone",
        ],
    },
    "constructions": {
        "wiki_packs": ["sdk_constructions"],
        "keywords": [
            "absorptance",
            "c-factor",
            "construction",
            "f-factor",
            "glazing",
            "insulation",
            "layer",
            "material",
            "r-value",
            "resistance",
            "shgc",
            "u-factor",
            "visible transmittance",
        ],
        "classes": [
            "CFactorUndergroundWallConstruction",
            "Construction",
            "ConstructionBase",
            "FFactorGroundFloorConstruction",
            "MasslessOpaqueMaterial",
            "Material",
            "SimpleGlazing",
            "StandardOpaqueMaterial",
        ],
    },
    "schedules": {
        "wiki_packs": ["sdk_schedules"],
        "keywords": [
            "availability",
            "day schedule",
            "default day",
            "hourly",
            "profile",
            "rule",
            "schedule",
            "schedule ruleset",
        ],
        "classes": [
            "Schedule",
            "ScheduleConstant",
            "ScheduleDay",
            "ScheduleRule",
            "ScheduleRuleset",
            "ScheduleTypeLimits",
        ],
    },
    "daylighting": {
        "wiki_packs": ["sdk_daylighting"],
        "keywords": [
            "daylight",
            "daylighting",
            "illuminance",
            "sensor",
            "setpoint",
        ],
        "classes": [
            "DaylightingControl",
            "GlareSensor",
            "IlluminanceMap",
            "Space",
        ],
    },
    "hvac": {
        "wiki_packs": ["sdk_hvac"],
        "keywords": [
            "air loop",
            "air terminal",
            "coil",
            "controller",
            "economizer",
            "fan",
            "hvac",
            "node",
            "outdoor air",
            "plant loop",
            "setpoint manager",
            "sizing",
            "thermostat",
            "zone equipment",
        ],
        "classes": [
            "AirLoopHVAC",
            "AirLoopHVACOutdoorAirSystem",
            "ControllerMechanicalVentilation",
            "ControllerOutdoorAir",
            "Node",
            "PlantLoop",
            "SetpointManagerScheduled",
            "ThermalZone",
            "ZoneHVACEquipmentList",
        ],
    },
    "simulation_results": {
        "wiki_packs": ["sdk_simulation_results"],
        "keywords": [
            "artifact",
            "eplusout",
            "osw",
            "result",
            "run",
            "simulation",
            "sql",
        ],
        "classes": ["Model", "OutputSQLite"],
    },
}


class OpenStudioSdkDocLookup:
    """Lookup helper for bundled OpenStudio SDK YAML documentation."""

    def __init__(self, docs_dir: str | Path | None = None) -> None:
        configured = docs_dir or _BUNDLED_DOCS_DIR
        self.docs_dir = Path(configured).expanduser().resolve() if configured else None
        self.source = "bundled" if docs_dir is None else "explicit"
        self.override_path: Path | None = None
        self.override_warning: str | None = None
        self._classes: dict[str, ClassDoc] | None = None

    @classmethod
    def from_env(cls) -> "OpenStudioSdkDocLookup":
        """Create a lookup helper with a safe fallback for a stale environment override.

        A custom directory is useful to test a newer documentation extraction,
        but it must not disable the SDK bundle shipped with OpenStudio AI.  SDK
        documentation is intentionally portable across compatible OpenStudio
        minor versions, so the bundled index remains a useful fallback even
        when the local OpenStudio installation differs from its version.
        """
        configured_dir = os.getenv("OPENSTUDIO_SDK_DOCS_DIR", "").strip()
        if not configured_dir:
            return cls()

        configured = cls(configured_dir)
        if configured.available():
            configured.source = "environment"
            return configured

        fallback = cls()
        fallback.source = "bundled_fallback"
        fallback.override_path = configured.docs_dir
        fallback.override_warning = (
            "OPENSTUDIO_SDK_DOCS_DIR does not contain a usable SDK bundle; "
            "using the bundled SDK documentation instead."
        )
        import warnings

        warnings.warn(fallback.override_warning, stacklevel=2)
        return fallback

    def available(self) -> bool:
        """Return whether the configured SDK documentation directory can be used."""
        if not self.docs_dir:
            return False
        version = _resolve_docs_version(self.docs_dir)
        if version is not None:
            return (self.docs_dir / "api" / f"classes-{version}.yaml.gz").is_file()
        return (self.docs_dir / "api" / "classes.yaml.gz").is_file()

    def selected_version(self) -> str | None:
        """Return the resolved versioned bundle, or None for legacy filenames."""
        if not self.docs_dir:
            return None
        return _resolve_docs_version(self.docs_dir)

    def health_probe(self) -> dict[str, Any]:
        """Read the bounded YAML header needed to confirm the bundle is usable.

        This deliberately avoids loading the full class catalog, which is too
        expensive for a command-line readiness check.
        """
        self._ensure_available()
        assert self.docs_dir is not None
        version = self.selected_version()
        filename = (
            f"classes-{version}.yaml.gz" if version is not None else "classes.yaml.gz"
        )
        classes_path = self.docs_dir / "api" / filename
        with gzip.open(classes_path, "rt", encoding="utf-8") as handle:
            header = handle.read(4096)

        if not header.startswith("metadata:\n") or "namespaces:" not in header:
            raise SdkDocsUnavailableError(
                f"SDK docs file has an invalid YAML header: {classes_path}"
            )

        class_count_match = re.search(r"^  total_classes: (\d+)$", header, re.MULTILINE)
        openstudio_version_match = re.search(
            r"^  openstudio_version: ['\"]?([^\n'\"]+)", header, re.MULTILINE
        )
        return {
            "classes_path": str(classes_path),
            "class_count": (
                int(class_count_match.group(1)) if class_count_match else None
            ),
            "documented_openstudio_version": (
                openstudio_version_match.group(1).strip()
                if openstudio_version_match
                else None
            ),
        }

    def route(self, query: str, *, limit: int = 6) -> dict[str, Any]:
        """Map a user request to likely SDK wiki packs and OpenStudio classes."""
        text = query.lower()
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for domain, config in DOMAIN_CLASS_GRAPH.items():
            score = 0
            for keyword in config["keywords"]:
                if keyword in text:
                    score += 2 if " " in keyword else 1
            for class_name in config["classes"]:
                if class_name.lower() in text:
                    score += 3
            if score:
                scored.append((score, domain, config))

        scored.sort(key=lambda item: (-item[0], item[1]))
        bounded_limit = max(0, limit)
        selected = scored[:bounded_limit]
        wiki_packs: list[str] = []
        classes: list[str] = []
        for _, _, config in selected:
            wiki_packs.extend(config["wiki_packs"])
            classes.extend(config["classes"])

        return {
            "domains": [
                {
                    "name": domain,
                    "score": score,
                    "wiki_packs": config["wiki_packs"],
                    "classes": config["classes"],
                }
                for score, domain, config in selected
            ],
            "wiki_packs": _dedupe(wiki_packs),
            "classes": _dedupe(classes),
            "notes": [
                "Use sdk_docs_get_method for exact constructor/getter/setter "
                "signatures before drafting SDK code.",
                "Use Python introspection when a generated Python collection "
                "getter is not present in the C++ docs.",
            ],
        }

    def find_classes(
        self,
        query: str,
        *,
        include_detail: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find SDK classes by exact or substring match on class names."""
        classes = self._load_classes()
        normalized_query = _normalize(query)
        results: list[tuple[int, ClassDoc]] = []
        for class_doc in classes.values():
            if class_doc.class_name.endswith("_Impl") and not include_detail:
                continue
            name = _normalize(class_doc.class_name)
            if name == normalized_query:
                score = 100
            elif name.startswith(normalized_query):
                score = 80
            elif normalized_query in name:
                score = 60
            else:
                continue
            results.append((score, class_doc))
        results.sort(key=lambda item: (-item[0], item[1].class_name))
        bounded_limit = max(0, min(limit, 100))
        return [
            self._class_summary(class_doc) for _, class_doc in results[:bounded_limit]
        ]

    def list_methods(
        self,
        class_name: str,
        *,
        keyword: str | None = None,
        limit: int = 80,
    ) -> dict[str, Any]:
        """List documented member functions for a class, optionally filtered."""
        class_doc = self._resolve_class(class_name)
        normalized_keyword = _normalize(keyword) if keyword else None
        methods = [
            method
            for method in class_doc.methods
            if normalized_keyword is None
            or normalized_keyword in _normalize(method.name)
        ]
        bounded_limit = max(0, min(limit, 200))
        return {
            **self._class_summary(class_doc),
            "methods": [asdict(method) for method in methods[:bounded_limit]],
            "total_matches": len(methods),
        }

    def get_method(
        self,
        class_name: str,
        method_name: str,
        *,
        anchor: str | None = None,
        signature_contains: str | None = None,
    ) -> dict[str, Any]:
        """Return signature and documentation for one class method.

        `anchor` is accepted for API compatibility but ignored (no per-method
        anchors in the YAML-derived data).  `signature_contains` disambiguates overloads.
        """
        class_doc = self._resolve_class(class_name)
        matches = [
            method
            for method in class_doc.methods
            if _normalize(method.name) == _normalize(method_name)
        ]
        if not matches:
            matches = [
                method
                for method in class_doc.methods
                if _normalize(method_name) in _normalize(method.name)
            ]
        if not matches:
            raise KeyError(f"Method not found on {class_doc.class_name}: {method_name}")

        overloads = [_method_summary(method) for method in matches]

        if anchor:
            # Anchors don't exist in YAML; ignore the filter but keep the
            # overloads list so callers get the full picture.
            pass

        if signature_contains:
            sig_lower = signature_contains.lower()
            filtered = [m for m in matches if sig_lower in (m.signature or "").lower()]
            if filtered:
                matches = filtered

        method = matches[0]
        notes = _method_notes(
            method.name, method.description or "", method.signature or ""
        )
        return {
            **self._class_summary(class_doc),
            "method": method.name,
            "anchor": None,
            "href": None,
            "signature": method.signature,
            "python_signature": method.python_signature,
            "documentation": method.description,
            "source_url": None,
            "notes": notes,
            "overloads": overloads,
        }

    def search_methods(
        self,
        keyword: str,
        *,
        class_filter: str | None = None,
        include_detail: bool = False,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Search member names across indexed SDK classes."""
        classes = self._load_classes()
        normalized_keyword = _normalize(keyword)
        normalized_class_filter = _normalize(class_filter) if class_filter else None
        bounded_limit = max(1, min(limit, 100))
        results: list[dict[str, Any]] = []
        for class_doc in classes.values():
            if class_doc.class_name.endswith("_Impl") and not include_detail:
                continue
            if normalized_class_filter and normalized_class_filter not in _normalize(
                class_doc.class_name
            ):
                continue
            for method in class_doc.methods:
                if normalized_keyword and normalized_keyword not in _normalize(
                    method.name
                ):
                    continue
                results.append(
                    {
                        "class_name": class_doc.class_name,
                        "namespace": class_doc.namespace,
                        "method": method.name,
                        "signature": method.signature,
                        "python_signature": method.python_signature,
                    }
                )
                if len(results) >= bounded_limit:
                    return results
        return results

    def build_index_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable index payload for optional offline caching."""
        classes = self._load_classes()
        return {
            "classes": [
                {
                    **self._class_summary(class_doc),
                    "methods": [asdict(method) for method in class_doc.methods],
                }
                for class_doc in classes.values()
            ],
            "class_count": len(classes),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_classes(self) -> dict[str, ClassDoc]:
        self._ensure_available()
        if self._classes is not None:
            return self._classes

        assert self.docs_dir is not None
        version = _resolve_docs_version(self.docs_dir)
        if version is not None:
            classes_path = self.docs_dir / "api" / f"classes-{version}.yaml.gz"
            python_api_path = self.docs_dir / "api" / f"python-api-{version}.yaml.gz"
        else:
            classes_path = self.docs_dir / "api" / "classes.yaml.gz"
            python_api_path = self.docs_dir / "api" / "python-api.yaml.gz"

        with gzip.open(classes_path) as fh:
            classes_data = yaml.safe_load(fh)

        python_paths: dict[str, str] = {}
        if python_api_path.is_file():
            with gzip.open(python_api_path) as fh:
                py_data = yaml.safe_load(fh) or {}
            for entry_name, entry in (py_data.get("classes") or {}).items():
                if isinstance(entry, dict):
                    python_paths[_normalize(entry_name)] = entry.get("python_path", "")

        classes: dict[str, ClassDoc] = {}
        for _ns_name, ns_data in (classes_data.get("namespaces") or {}).items():
            for class_name, class_entry in (ns_data.get("classes") or {}).items():
                if not isinstance(class_entry, dict):
                    continue
                key = _normalize(class_name)
                methods = _parse_methods(class_entry)
                py_path = python_paths.get(key) or class_entry.get("python") or ""
                classes[key] = ClassDoc(
                    class_name=class_name,
                    namespace=class_entry.get("namespace", _ns_name),
                    description=class_entry.get("description"),
                    python_path=py_path or None,
                    parent=class_entry.get("parent"),
                    is_abstract=bool(class_entry.get("is_abstract", False)),
                    methods=methods,
                )

        self._classes = classes
        return classes

    def _resolve_class(self, class_name: str) -> ClassDoc:
        classes = self._load_classes()
        key = _normalize(class_name)
        if key in classes:
            return classes[key]
        candidates = self.find_classes(class_name, limit=5)
        if not candidates:
            raise KeyError(f"OpenStudio SDK class not found: {class_name}")
        return classes[_normalize(candidates[0]["class_name"])]

    def _class_summary(self, class_doc: ClassDoc) -> dict[str, Any]:
        return {
            "class_name": class_doc.class_name,
            "namespace": class_doc.namespace,
            "description": class_doc.description,
            "python_path": class_doc.python_path,
            "parent": class_doc.parent,
            "is_abstract": class_doc.is_abstract,
            "method_count": len(class_doc.methods),
        }

    def _ensure_available(self) -> None:
        if not self.available():
            raise SdkDocsUnavailableError(
                "OpenStudio SDK docs are unavailable. "
                "Expected a versioned or legacy api/classes YAML gzip inside "
                f"the docs directory ({self.docs_dir})."
            )


def write_index_file(docs_dir: str | Path, output_path: str | Path) -> Path:
    """Build a compact class/method index from local SDK docs."""
    import json

    lookup = OpenStudioSdkDocLookup(docs_dir)
    payload = lookup.build_index_payload()
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def _parse_methods(class_entry: dict[str, Any]) -> list[MethodRef]:
    methods: list[MethodRef] = []
    seen: set[tuple[str, str]] = set()
    for section_key in ("public_methods", "protected_methods", "static_methods"):
        for item in class_entry.get(section_key) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            sig = item.get("signature") or ""
            key = (_normalize(name), _normalize(sig))
            if key in seen:
                continue
            seen.add(key)
            methods.append(
                MethodRef(
                    name=name,
                    signature=sig,
                    python_signature=item.get("python_signature"),
                    description=item.get("description"),
                )
            )
    return methods


def _method_summary(method: MethodRef) -> dict[str, Any]:
    return {
        "method": method.name,
        "signature": method.signature,
        "python_signature": method.python_signature,
    }


def _method_notes(method_name: str, description: str, signature: str) -> list[str]:
    haystack = f"{description} {signature}".lower()
    notes: list[str] = []
    if "radians" in haystack or "radian" in haystack:
        notes.append(
            "This method documents an angle in radians. Convert with "
            "openstudio.convert(value, 'rad', 'deg') before degree-based reporting."
        )
    if "w/m" in haystack or "m^2" in haystack or "m2" in haystack:
        notes.append(
            "The documentation references SI units. Confirm or convert "
            "user-provided IP values before calling the SDK."
        )
    if (
        "boost::optional" in haystack
        or method_name.startswith(("get", "optional"))
        or re.search(r"optional\s*<", haystack)
    ):
        notes.append(
            "If the Python binding returns an OpenStudio optional, check "
            "is_initialized() before get()."
        )
    if "throws" in description.lower() or "throw" in description.lower():
        notes.append(
            "The documentation states this method can throw; catch exceptions "
            "or guard preconditions in generated scripts."
        )
    return notes


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
