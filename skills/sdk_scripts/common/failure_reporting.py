"""Standalone, stdlib-only incident receipts and bounded GitHub submission.

This file is also exported verbatim into report-openstudio-failure. It must not
import the modeling runtime, OpenStudio, or another plugin file.
"""

from __future__ import annotations

import argparse
import ast
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from urllib.parse import urlencode

REPOSITORY = "pnnl/openstudio-ai-harness"
ISSUE_ROOT = f"https://github.com/{REPOSITORY}/issues/"
MAX_INPUT = 131072
RECEIPT_VERSION = 2
# Only these fixed messages cross the publication boundary. Error suffixes can
# contain arbitrary model values, even when they have no quotes or identifiers.
ERROR_MESSAGES = {
    "sdk_rejected": "The SDK rejected a bundled operation.",
    "missing_water_controller": "A required water-coil controller was missing.",
    "migration_side_effect": "Plant migration changed a protected model object.",
    "attachment_side_effect": "Coil attachment changed a protected model object.",
    "topology_side_effect": "A topology operation changed a protected model object.",
    "saved_validation_failed": "The saved model failed bundled validation.",
    "translation_failed": "EnergyPlus translation failed bundled validation.",
    "plan_mismatch": "Fresh preflight differed from the reviewed plan.",
    "unexpected_execution_error": "A bundled operation encountered an unexpected execution error.",
}
ERROR_PREFIXES = (
    ("SDK rejected", "sdk_rejected"),
    ("Missing water controller:", "missing_water_controller"),
    ("Unexpected migration side effect on", "migration_side_effect"),
    ("Unexpected SDK attachment side effect on", "attachment_side_effect"),
    ("Unapproved topology side effect on", "topology_side_effect"),
    ("Saved validation failed", "saved_validation_failed"),
    ("EnergyPlus translation failed", "translation_failed"),
    ("Reviewed plan differs from fresh preflight", "plan_mismatch"),
)
EXPECTED_MESSAGE = "Bundled operation completes its documented contract or returns an expected readiness result."
SUBMISSION_ACCOUNT = "Issues are created under your own authenticated GitHub account."
SAFE_WORDS = set(
    "automatic disabled claude claude_code codex nlr sdk harness plugin python "
    "Darwin Linux Windows arm64 aarch64 x86_64 AMD64 heating cooling water electric "
    "gas dx chilled_water hot_water constant variable supply demand Autosize "
    "FixedDryBulb NoEconomizer UA NominalCapacity prototype_vav_v1 "
    "input output preserved unpublished published unknown".split()
)
SAFE_FLAGS = set(
    "--input --output --config --report --plan --openstudio --candidate-filter "
    "--probe-timeout --output-dir --system execute_python_script -m --json".split()
)
CONFIG_KEYS = set(
    "operation type name handle air_loop air_loops plant_loop plant_loops zones "
    "thermal_zones zone_equipment vrf_systems fan heating cooling reheat controls "
    "sizing schedules outdoor_air availability_schedule defaults_profile "
    "dx_approved pressure_rise_pa pressure_rise_in_h2o total_efficiency "
    "motor_efficiency motor_in_airstream_fraction efficiency minimum_flow_m3_s "
    "maximum_flow_m3_s dcv economizer minimum_fraction flow_fraction "
    "design_supply_air_temperature_c design_inlet_air_temperature_c "
    "design_inlet_water_temperature_c rated_inlet_water_temperature_c "
    "rated_outlet_water_temperature_c maximum_water_flow_m3_s "
    "rated_capacity_w rated_flow_m3_s rated_power_w head_pa head_ft_h2o "
    "coefficients end_use_subcategory output_model_path hot_water_loop "
    "chilled_water_loop air_node destination_plant coil controller "
    "outlet_temperature_control sensible_effectiveness latent_effectiveness "
    "heating_effectiveness cooling_effectiveness performance_input_method "
    "supply_temperature_c delta_t_k cooling_type heating_type reheat_type "
    "availability_schedule_name thermostat_schedule minimum_airflow_fraction".split()
)
CONFIG_KEYS.update(
    {
        "availability_policy",
        "reheat_policy",
        "zone_sizing_policy",
        "maximum_airflow_m3_s",
    }
)
SAFE_WORDS.update(
    {
        "VAVNoReheat",
        "ConstantVolumeNoReheat",
        "None",
        "DistrictHeatingWater",
        "DistrictCooling",
    }
)
CONFIG_KEYS.update(
    {
        "district_equipment",
        "equipment",
        "capacity_fraction_schedule",
        "nominal_capacity_w",
        "tower",
        "design_fan_power_w",
        "minimum_air_flow_ratio",
        "free_convection_capacity_fraction",
        "chiller",
        "reference_cop",
        "reference_capacity_w",
        "boiler",
        "nominal_thermal_efficiency",
        "minimum_part_load_ratio",
        "maximum_part_load_ratio",
        "optimum_part_load_ratio",
        "minimum_unloading_ratio",
        "on_cycle_parasitic_electric_load_w",
        "off_cycle_parasitic_fuel_load_w",
    }
)
# Maintained schema field/enum allowlist; regression checks keep it complete.
CONFIG_KEYS.update(
    [
        "action",
        "actuator_variable",
        "air_loop",
        "air_node",
        "availability_schedule",
        "builtin",
        "bypass_control",
        "central_cooling",
        "central_heating",
        "coil",
        "coil_name",
        "control_type",
        "control_variable",
        "controller",
        "controller_name",
        "convergence_tolerance_k",
        "damper_heating_action",
        "dcv",
        "defaults_profile",
        "defrost_fraction_increase_per_k",
        "design",
        "design_air_flow_m3_s",
        "design_inlet_air_humidity_ratio",
        "design_inlet_air_temperature_c",
        "design_inlet_water_temperature_c",
        "design_outlet_air_humidity_ratio",
        "design_outlet_air_temperature_c",
        "design_temperatures_c",
        "design_water_flow_m3_s",
        "dx_approved",
        "economizer",
        "economizer_control",
        "economizer_lockout",
        "efficiency",
        "electric_power_per_flow",
        "end_use_subcategory",
        "fan",
        "flow_policy",
        "frost_control",
        "frost_threshold_c",
        "handle",
        "head",
        "head_units",
        "heat_exchanger",
        "heat_exchanger_configuration",
        "heat_exchanger_type",
        "initial_defrost_fraction",
        "kind",
        "latent_cooling",
        "latent_cooling_100",
        "latent_heating",
        "latent_heating_100",
        "lockout_type",
        "maximum_dewpoint_c",
        "maximum_dry_bulb_c",
        "maximum_enthalpy_j_kg",
        "maximum_flow_m3_s",
        "maximum_fraction_schedule",
        "maximum_humidity_ratio",
        "maximum_reheat_flow_fraction",
        "maximum_reheat_flow_per_area_m3_s_m2",
        "maximum_reheat_temperature_c",
        "maximum_temperature_c",
        "maximum_water_flow_m3_s",
        "mechanical_availability_schedule",
        "minimum_dry_bulb_c",
        "minimum_flow_m3_s",
        "minimum_flow_schedule",
        "minimum_fraction_schedule",
        "minimum_humidity_ratio",
        "minimum_limit_type",
        "minimum_power_flow_fraction",
        "minimum_system_airflow_ratio",
        "minimum_temperature_c",
        "minimum_terminal_airflow_fraction",
        "mode",
        "motor_efficiency",
        "motor_loss_fraction_to_fluid",
        "name",
        "nominal_flow_m3_s",
        "nominal_power_w",
        "operation",
        "outdoor_air_schedule",
        "output_model_path",
        "part_load_coefficients",
        "part_load_effectiveness",
        "part_load_policy",
        "performance_input_method",
        "plant_loop",
        "plant_policy",
        "power_coefficients",
        "power_policy",
        "power_sizing_method",
        "precool",
        "preheat",
        "pressure_rise",
        "pressure_units",
        "pretreat_limits",
        "pump",
        "rated_capacity_w",
        "rated_inlet_air_temperature_c",
        "rated_inlet_water_temperature_c",
        "rated_outlet_air_temperature_c",
        "rated_outlet_water_temperature_c",
        "rated_power_w",
        "ratings",
        "reference_policy",
        "reheat",
        "return_plenum",
        "sensible_cooling",
        "sensible_cooling_100",
        "sensible_heating",
        "sensible_heating_100",
        "settings",
        "shaft_power_per_flow_per_head",
        "sizing",
        "sizing_option",
        "supply_outlet_temperature_control",
        "system_name",
        "system_sizing_policy",
        "target_class",
        "target_zones",
        "temperature_control",
        "terminal",
        "terminal_policy",
        "total_efficiency",
        "type",
        "type_of_analysis",
        "ua_w_per_k",
        "variable_speed",
        "variable_volume",
        "ventilation",
        "ventilation_method",
        "zone",
        "zone_cooling",
        "zone_heating",
    ]
)
SAFE_WORDS.update(
    [
        "AlwaysOffDiscrete",
        "AlwaysOnDiscrete",
        "Autosize",
        "BypassWhenOAFlowGreaterThanMinimum",
        "BypassWhenWithinEconomizerLimits",
        "Coincident",
        "ConstantSpeed",
        "ConstantVolume",
        "Continuous",
        "Cooling",
        "CounterFlow",
        "CrossFlow",
        "DXTwoSpeed",
        "DetailedAnalysis",
        "DifferentialDryBulb",
        "DifferentialDryBulbAndEnthalpy",
        "DifferentialEnthalpy",
        "Electricity",
        "ElectronicEnthalpy",
        "ExhaustAirRecirculation",
        "ExhaustOnly",
        "FixedDewPointAndDryBulb",
        "FixedDryBulb",
        "FixedEnthalpy",
        "FixedMinimum",
        "Flow",
        "Heating",
        "Intermittent",
        "Linear75To100ConstantOutside",
        "LockoutWithCompressor",
        "LockoutWithHeating",
        "MinimumExhaustTemperature",
        "NaturalGas",
        "NoEconomizer",
        "NoLockout",
        "NominalCapacity",
        "NonCoincident",
        "None",
        "Normal",
        "Pa",
        "Plate",
        "PowerPerFlow",
        "PowerPerFlowPerPressure",
        "Preserve",
        "ProportionalMinimum",
        "Reject",
        "Reverse",
        "ReverseWithLimits",
        "Rotary",
        "SimpleAnalysis",
        "Temperature",
        "UFactorTimesAreaAndDesignWaterFlowRate",
        "VariableSpeed",
        "VariableVolume",
        "Water",
        "ZoneSum",
        "attach",
        "edit",
        "ftH2O",
        "inH2O",
        "migrate_plant",
        "prototype_vav_v1",
        "relocate_air",
    ]
)
FIELDS = (
    "operation",
    "stage",
    "provider",
    "category",
    "exception_type",
    "expected",
    "actual",
    "error_code",
    "error_site",
    "traceback",
    "command",
    "exit_code",
    "environment",
    "settings",
    "model_context",
    "diagnostic",
    "observations",
    "reproducer",
    "workarounds",
    "publication",
)


def sdk_root():
    source = Path(__file__).resolve()
    if source.parent.name == "common":
        return source.parents[1]
    # Independent recovery copy: skills/report-openstudio-failure/scripts/.
    return source.parents[3] / "sdk"


def plugin_frames(value):
    """Validate locations against shipped source, never formatted traceback text.

    Missing SDK sources (a supported reporter recovery case) yield no frames.
    AST inspection never executes the source and permits only existing symbols.
    """
    if not isinstance(value, list):
        return []
    root = sdk_root().resolve()
    sources, result = {}, []
    for frame in value[-12:]:
        if not isinstance(frame, dict):
            continue
        relative, function, line = (
            frame.get("file"),
            frame.get("function"),
            frame.get("line"),
        )
        if (
            not isinstance(relative, str)
            or not re.fullmatch(r"(?:common/)?[a-z][a-z0-9_]*\.py", relative)
            or not isinstance(function, str)
            or type(line) is not int
            or line < 1
        ):
            continue
        try:
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                continue
            if relative not in sources:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
                symbols = [("<module>", 1, len(text.splitlines()))]
                symbols.extend(
                    (node.name, node.lineno, node.end_lineno)
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                sources[relative] = symbols
            if any(
                name == function and start <= line <= end
                for name, start, end in sources[relative]
            ):
                result.append({"file": relative, "function": function, "line": line})
        except (OSError, UnicodeError, SyntaxError):
            continue
    return result


def exception_frames(exc):
    root = sdk_root().resolve()
    frames = []
    current = exc.__traceback__
    while current:
        code = current.tb_frame.f_code
        path = Path(code.co_filename).resolve()
        if path.is_relative_to(root):
            frames.append(
                {
                    "file": path.relative_to(root).as_posix(),
                    "function": code.co_name,
                    "line": current.tb_lineno,
                }
            )
        current = current.tb_next
    return plugin_frames(frames)


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_INPUT:
        raise ValueError("Diagnostic input exceeds 128 KiB")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Diagnostic input must be an object")
    return value


def write_json(path, value):
    """Atomic owned-state update; never modify a model or the SDK report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Incident state cannot be a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".incident-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Sanitizer:
    def __init__(self, private_values=()):
        self.private = sorted(
            {str(x) for x in private_values if isinstance(x, str) and x},
            key=len,
            reverse=True,
        )
        self.aliases = {}

    def alias(self, value):
        if re.fullmatch(r"<value-\d{1,9}>", value):
            self.aliases[value] = value
            return value
        if value not in self.aliases:
            index = len(self.aliases) + 1
            while f"<value-{index}>" in self.aliases.values():
                index += 1
            self.aliases[value] = f"<value-{index}>"
        return self.aliases[value]

    def text(self, value, limit=1200):
        text = str(value)[:12000]
        for private in self.private:
            text = text.replace(private, self.alias(private))
        text = re.sub(r"-----BEGIN[\s\S]*?-----END[^\n]*", "<redacted-key>", text)
        text = re.sub(
            r"(?i)\b(password|passwd|token|secret|authorization|api[_-]?key)\s*[:=]\s*[^\n]+",
            r"\1=<redacted>",
            text,
        )
        text = re.sub(
            r"\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]+", "<redacted-token>", text
        )
        text = re.sub(r"\bBearer\s+\S+", "Bearer <redacted>", text, flags=re.I)
        text = re.sub(
            r"https?://[^\s<>\"']+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
            "<private-address>",
            text,
        )
        text = re.sub(
            r"(?<!\w)(?:[A-Za-z]:[\\/]|/|~/)[^\s\"'<>]+", "<local-path>", text
        )
        text = re.sub(
            r"\{?[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\}?",
            "<object>",
            text,
        )
        text = re.sub(r"['\"][^'\"\n]+['\"]", "<quoted-value>", text)
        text = re.sub(
            r"\b[\w.-]+\.(?:osm|csv|epw|osw|json|pdf)\b", "<file>", text, flags=re.I
        )
        text = re.sub(r"\b[A-Za-z0-9_+=-]{32,}\b", "<opaque-value>", text)
        # GitHub mention/HTML/hidden-marker injection in untrusted log text.
        text = text.replace("<!--", "<comment>").replace("@", "[at]")
        return text[:limit]

    def settings(self, value, depth=0):
        if depth > 6:
            return "<bounded>"
        if isinstance(value, dict):
            return {
                key: self.settings(child, depth + 1)
                for key, child in list(value.items())[:60]
                if key in CONFIG_KEYS
            }
        if isinstance(value, list):
            return [self.settings(x, depth + 1) for x in value[:12]]
        if value is None or type(value) in (bool, int, float):
            return value
        return value if value in SAFE_WORDS else self.alias(str(value))

    def command(self, values):
        if not isinstance(values, list):
            return []
        result = []
        for item in values[:40]:
            item = str(item)
            base = item.replace("\\", "/").rsplit("/", 1)[-1]
            if item in SAFE_FLAGS:
                result.append(item)
            elif re.fullmatch(r"(?:python(?:3(?:\.\d+)?)?|openstudio)(?:\.exe)?", base):
                result.append(base)
            elif re.fullmatch(
                r"(?:edit_|replace_|connect_|attach_|manage_|remove_|prepare_|visualize_|vav_|plant_|cav_|sdk_)[a-z_]+\.py",
                base,
            ):
                result.append(base)
            else:
                result.append(self.alias(item))
        return result


def sanitize(event):
    private = event.get("private_values", [])
    if not isinstance(private, list):
        private = []
    s = Sanitizer(private)
    public = {}
    frames = plugin_frames(event.get("plugin_frames", event.get("traceback")))
    code = event.get("error_code")
    if code not in ERROR_MESSAGES:
        actual = str(event.get("actual", ""))
        code = next(
            (code for prefix, code in ERROR_PREFIXES if actual.startswith(prefix)),
            "unexpected_execution_error",
        )
    for key in FIELDS:
        if key not in event and key not in {
            "actual",
            "error_code",
            "error_site",
            "traceback",
            "expected",
        }:
            continue
        value = event.get(key)
        if key == "actual":
            public[key] = ERROR_MESSAGES[code]
        elif key == "error_code":
            public[key] = code
        elif key == "error_site":
            # Distinguish defects at different plugin locations without hashing
            # model values. Preserve only this digest if SDK sources are lost.
            public[key] = (
                hashlib.sha256(
                    json.dumps(
                        {k: frames[-1][k] for k in ("file", "function")}, sort_keys=True
                    ).encode()
                ).hexdigest()
                if frames
                else (
                    value
                    if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
                    else None
                )
            )
        elif key == "expected":
            public[key] = EXPECTED_MESSAGE
        elif key == "traceback":
            public[key] = frames
        elif key == "exception_type":
            public[key] = (
                value
                if value
                in {
                    "RuntimeError",
                    "ValueError",
                    "TypeError",
                    "AttributeError",
                    "KeyError",
                    "IndexError",
                    "AssertionError",
                    "OSError",
                    "PermissionError",
                    "FileNotFoundError",
                    "DiagnosticError",
                    "CompatibilityError",
                    "ImportError",
                    "ModuleNotFoundError",
                    "TimeoutError",
                    "SystemExit",
                }
                else "Exception"
            )
        elif key == "command":
            public[key] = s.command(value)
        elif key == "settings":
            public[key] = s.settings(value)
        elif key == "environment" and isinstance(value, dict):
            public[key] = {
                k: (
                    str(v)[:100]
                    if re.fullmatch(r"[a-f0-9]{64}", str(v))
                    else s.text(v, 100)
                )
                for k, v in value.items()
                if k
                in {
                    "host",
                    "host_version",
                    "plugin_version",
                    "bundle_id",
                    "required_sdk",
                    "observed_sdk",
                    "source_version",
                    "python",
                    "os",
                    "architecture",
                }
            }
        elif key == "model_context" and isinstance(value, dict):
            public[key] = {
                "object_counts": {
                    k: v
                    for k, v in list(value.get("object_counts", {}).items())[:24]
                    if re.fullmatch(r"OS_[A-Za-z0-9_]+", k)
                    and type(v) is int
                    and v >= 0
                },
                "source_sha256": (
                    value.get("source_sha256")
                    if re.fullmatch(r"[a-f0-9]{64}", str(value.get("source_sha256")))
                    else None
                ),
                "companions_available": (
                    value.get("companions_available")
                    if type(value.get("companions_available")) is bool
                    else None
                ),
            }
        elif key == "diagnostic" and isinstance(value, dict):
            differences = []
            known = CONFIG_KEYS | {
                "plan",
                "configuration",
                "snapshot",
                "protected_snapshot",
                "removed_objects",
                "input_sha256",
                "fields",
            }
            for item in value.get("differences", [])[:12]:
                category = item.get("category")
                if category not in {
                    "handle_churn",
                    "stale_source",
                    "changed_value",
                    "changed_type",
                    "changed_structure",
                    "changed_length",
                }:
                    continue
                parts = str(item.get("path", ""))[:180].split("/")
                path = "/".join(
                    p if not p or p in known or p.isdigit() else s.alias(p)
                    for p in parts
                )
                differences.append({"path": path, "category": category})
            public[key] = {
                "differences": differences,
                "truncated": bool(value.get("truncated")),
            }
        elif key == "exit_code" and type(value) is int:
            public[key] = value
        elif key in {"observations", "workarounds"} and isinstance(value, list):
            public[key] = [s.text(x, 500) for x in value[:8]]
        elif key == "reproducer" and isinstance(value, dict):
            verified = (
                value.get("synthetic_verified") is True
                or value.get("status") == "synthetic_steps_verified"
            )
            public[key] = {
                "status": (
                    "synthetic_steps_verified"
                    if verified
                    else "not_independently_reproducible_yet"
                ),
                "steps": [s.text(x, 600) for x in value.get("steps", [])[:10]],
                "missing_evidence": (
                    ""
                    if verified
                    else "Equivalent synthetic input and independent reproduction; private model is not uploaded."
                ),
            }
        elif isinstance(value, str):
            public[key] = s.text(value, 2000 if key == "traceback" else 1200)
    public.setdefault(
        "reproducer",
        {
            "status": "not_independently_reproducible_yet",
            "steps": [],
            "missing_evidence": "Equivalent synthetic input and independent reproduction; private model is not uploaded.",
        },
    )
    if len(json.dumps(public, allow_nan=False)) > 24000:
        public["settings"] = {}
        public["observations"] = public.get("observations", [])[:7] + [
            "Configuration omitted at the diagnostic size limit; supply minimal synthetic settings for reproduction."
        ]
        public["reproducer"]["status"] = "not_independently_reproducible_yet"
        public["reproducer"][
            "missing_evidence"
        ] = "Minimal settings omitted at the diagnostic size limit."
    return public


def fingerprint(public):
    identity = {
        k: public.get(k)
        for k in (
            "operation",
            "stage",
            "provider",
            "category",
            "exception_type",
            "actual",
            "error_code",
            "error_site",
        )
    }
    identity["environment"] = {
        k: public.get("environment", {}).get(k)
        for k in ("plugin_version", "bundle_id", "required_sdk", "observed_sdk")
    }
    normalized = re.sub(r"<value-\d+>", "<value>", json.dumps(identity, sort_keys=True))
    return hashlib.sha256(normalized.encode()).hexdigest()


def capture(event, state_dir):
    if any(
        not isinstance(event.get(k), str) or not event[k].strip()
        for k in ("operation", "stage", "actual")
    ):
        raise ValueError("Failure event requires operation, stage and actual strings")
    if event.get("expected_outcome") is True:
        return {"ok": True, "status": "expected_outcome", "submitted": False}
    state = Path(state_dir).expanduser().resolve()
    public = sanitize(event)
    identity = fingerprint(public)
    directory = state / identity
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    ignore = state / ".gitignore"
    try:
        with ignore.open("x", encoding="utf-8") as stream:
            stream.write("*\n")
    except FileExistsError:
        pass
    receipt = directory / "receipt.json"
    lock = directory / "submission.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {
            "ok": False,
            "status": "busy",
            "submitted": False,
            "receipt": str(receipt),
            "fingerprint": identity,
        }
    os.close(descriptor)
    try:
        if not receipt.exists():
            # Keep the original diagnostic private and separate. render_issue
            # and submit only consume receipt.public, never this local file.
            write_json(
                directory / "private.json",
                {
                    "actual": str(event.get("actual", ""))[:12000],
                    "traceback": str(event.get("traceback", ""))[:12000],
                    "exception_type": str(event.get("exception_type", ""))[:120],
                },
            )
            write_json(
                receipt,
                {
                    "schema_version": RECEIPT_VERSION,
                    "fingerprint": identity,
                    "repository": REPOSITORY,
                    "status": (
                        "local_only"
                        if event.get("security_sensitive") is True
                        else "pending"
                    ),
                    "created_at": now(),
                    "public": public,
                },
            )
        elif event.get("security_sensitive") is True:
            record = read_json(receipt)
            if record["status"] not in {"submitted", "duplicate"}:
                record["status"] = "local_only"
                write_json(receipt, record)
    finally:
        lock.unlink()
    return {
        "ok": True,
        "status": read_json(receipt)["status"],
        "submitted": False,
        "receipt": str(receipt),
        "fingerprint": identity,
    }


def unexpected(exc):
    status = getattr(exc, "details", {}).get("status")
    if status in {"requires_preparation", "invalid_model"}:
        return False
    if status == "plan_mismatch":
        return any(
            x.get("category") == "handle_churn"
            for x in exc.details.get("diagnostic", {}).get("differences", [])
        )
    if (
        isinstance(exc, (FileNotFoundError, PermissionError))
        or type(exc).__name__ == "CompatibilityError"
    ):
        return False
    if isinstance(exc, ValueError):
        return any(
            x in str(exc)
            for x in (
                "Saved validation failed",
                "EnergyPlus translation failed",
                "SDK rejected",
                "Saved model",
                "Staged external files",
            )
        )
    return True


def capture_exception(exc, operation, stage, args=None, report=None):
    """Best-effort local capture only; never changes model success/failure."""
    published = bool(
        report
        and report.get("ok")
        and (report.get("mode") == "edit_model" or report.get("status") == "prepared")
    )
    if not unexpected(exc) and not published:
        return {}
    try:
        event = {
            "operation": operation,
            "stage": stage,
            "provider": "sdk",
            "category": "unexpected_execution",
            "exception_type": type(exc).__name__,
            "actual": str(exc),
            "expected": "Bundled operation completes its documented contract or returns an expected readiness result.",
            "traceback": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[-6000:],
            "plugin_frames": exception_frames(exc),
            "command": sys.argv,
            "exit_code": 2,
            "environment": {
                "host": "unknown",
                "python": platform.python_version(),
                "os": platform.system(),
                "architecture": platform.machine(),
            },
            "publication": "unknown; inspect the original operation report before recovery",
        }
        sdk = sys.modules.get("openstudio")
        if sdk is not None and hasattr(sdk, "openStudioVersion"):
            event["environment"]["observed_sdk"] = str(sdk.openStudioVersion())
        diagnostic = getattr(exc, "details", {}).get("diagnostic")
        if diagnostic:
            event["diagnostic"] = diagnostic
        root = Path(__file__).resolve().parents[1]
        contract = root / "compatibility.json"
        if contract.is_file():
            event["environment"]["required_sdk"] = read_json(contract).get(
                "required_openstudio_version"
            )
        marker = root / "bundle.json"
        if marker.is_file():
            metadata = read_json(marker)
            event["environment"]["bundle_id"] = metadata.get("bundle_id")
            event["environment"]["plugin_version"] = metadata.get(
                "plugin_version", "unknown"
            )
        if args:
            # Plan/report warnings can contain model-object names. Never copy
            # them into diagnostics; take only the explicit configuration below.
            for field in ("config", "plan"):
                path = getattr(args, field, None)
                if (
                    path
                    and Path(path).is_file()
                    and Path(path).stat().st_size <= 8 * 1024 * 1024
                ):
                    value = json.loads(Path(path).read_text(encoding="utf-8"))
                    event["settings"] = value.get("configuration", value)
                    source = value.get("input_model_path")
                    if source:
                        event["source_path"] = source
                    if value.get("input_sha256"):
                        event["model_context"] = {
                            "source_sha256": value["input_sha256"]
                        }
            source = getattr(args, "input", None) or event.get("source_path")
            if (
                source
                and Path(source).is_file()
                and Path(source).suffix.lower() == ".osm"
            ):
                with Path(source).open("rb") as stream:
                    header = stream.read(8192).decode("latin-1")
                version = re.search(r"OS:Version\s*,.*?(\d+\.\d+\.\d+)", header, re.S)
                if version:
                    event["environment"]["source_version"] = version.group(1)
        private = []

        def names(value):
            if isinstance(value, dict):
                for child in value.values():
                    names(child)
            elif isinstance(value, list):
                for child in value:
                    names(child)
            elif isinstance(value, str) and value not in SAFE_WORDS:
                private.append(value)

        names(event.get("settings", {}))
        event["private_values"] = private[:500]
        if published:
            event["publication"] = (
                "published; report writing failed; do not repeat the mutation"
            )
        elif report and report.get("ok"):
            event["publication"] = (
                "unpublished; read-only operation completed but report writing failed"
            )
        state = os.environ.get(
            "OPENSTUDIO_AI_FAILURE_DIR", str(Path.cwd() / ".openstudio_ai_failures")
        )
        result = capture(event, state)
        return {"failure_receipt": result["receipt"]}
    except Exception:
        return {"failure_capture_unavailable": True}


class TransportError(RuntimeError):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


class GitHub:
    def request(self, method, endpoint, payload=None):
        gh = shutil.which("gh")
        if not gh:
            raise TransportError("github_cli_unavailable")
        command = [gh, "api", "--hostname", "github.com", "--method", method, endpoint]
        if payload is not None:
            command += ["--input", "-"]
        env = os.environ.copy()
        env["GH_PROMPT_DISABLED"] = "1"
        env.pop("GH_DEBUG", None)
        try:
            run = subprocess.run(
                command,
                input=json.dumps(payload) if payload is not None else None,
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise TransportError("github_transport_unavailable") from None
        if run.returncode:
            if method == "GET" and "HTTP 404" in run.stderr:
                return None
            raise TransportError("github_request_failed")
        try:
            return json.loads(run.stdout)
        except ValueError:
            raise TransportError("github_response_unreadable") from None


def issue_identity(value):
    if not isinstance(value, dict) or "pull_request" in value:
        return None
    number = value.get("number")
    url = value.get("html_url")
    if type(number) is int and number > 0 and url == ISSUE_ROOT + str(number):
        return {"number": number, "url": url}
    return None


def find_existing(transport, identity):
    marker = "openstudio-ai-incident:" + identity
    result = transport.request(
        "GET",
        "search/issues?"
        + urlencode(
            {"q": f'repo:{REPOSITORY} is:issue in:body "{marker}"', "per_page": 30}
        ),
    )
    if (
        not isinstance(result, dict)
        or result.get("incomplete_results")
        or not isinstance(result.get("items"), list)
    ):
        raise TransportError("duplicate_search_unavailable")
    for item in result["items"]:
        found = issue_identity(item)
        if found and marker in item.get("body", ""):
            return found
    return None


def render_issue(record):
    public = record["public"]
    identity = record["fingerprint"]
    operation = re.sub(r"[^a-zA-Z0-9_-]", "_", public.get("operation", "unknown"))[:60]
    category = re.sub(r"[^a-zA-Z0-9_-]", "_", public.get("exception_type", "failure"))[
        :40
    ]
    body = "\n".join(
        [
            "## Summary",
            "",
            f"Bundled {operation} encountered {category}.",
            "",
            "## Reproduction and diagnostic evidence",
            "",
            "```json",
            json.dumps(public, indent=2, sort_keys=True),
            "```",
            "",
            "## Data handling",
            "",
            "Sanitized allowlisted diagnostics only. No model, companion files, credentials or transcript is attached. Attribution remains provisional.",
            "",
            f"<!-- openstudio-ai-incident:{identity} -->",
            "",
        ]
    )
    return {"title": f"[automatic failure] {operation}: {category}", "body": body}


def apply_template(transport, payload, public):
    listing = transport.request(
        "GET", f"repos/{REPOSITORY}/contents/.github/ISSUE_TEMPLATE"
    )
    if listing is None:
        return payload, "documented_fallback_no_template_directory"
    if not isinstance(listing, list):
        raise TransportError("repository_template_requires_mapping")
    names = {x.get("name") for x in listing if isinstance(x, dict)}
    selected = next(
        (x for x in ("bug_report.md", "bug-report.md", "bug.md") if x in names), None
    )
    if not selected:
        raise TransportError("repository_template_requires_mapping")
    resource = transport.request(
        "GET", f"repos/{REPOSITORY}/contents/.github/ISSUE_TEMPLATE/{selected}"
    )
    try:
        if resource.get("encoding") != "base64" or len(resource["content"]) > 24000:
            raise ValueError()
        template = base64.b64decode(resource["content"]).decode("utf-8")
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        raise TransportError("repository_template_unreadable") from None
    labels = []
    if template.startswith("---\n"):
        parts = template.split("---", 2)
        if len(parts) != 3 or re.search(r"(?m)^\s+-|[|>]", parts[1]):
            raise TransportError("repository_template_requires_mapping")
        for line in parts[1].strip().splitlines():
            key, separator, value = line.partition(":")
            if not separator or key not in {
                "name",
                "about",
                "title",
                "labels",
                "assignees",
            }:
                raise TransportError("repository_template_requires_mapping")
            if key == "assignees" and value.strip(" []'\""):
                raise TransportError("repository_template_requires_mapping")
            if key == "labels":
                labels = [
                    x.strip(" []'\"") for x in value.split(",") if x.strip(" []'\"")
                ]
                if any(not re.fullmatch(r"[A-Za-z0-9 _-]{1,40}", x) for x in labels):
                    raise TransportError("repository_template_requires_mapping")
        template = parts[2]
    headings = re.findall(r"(?m)^#{1,4}\s+([^\n]+)", template)
    if not headings or len(headings) > 16:
        raise TransportError("repository_template_requires_mapping")
    sections = []
    for heading in headings[:16]:
        lower = heading.lower()
        if any(x in lower for x in ("reproduc", "steps")):
            value = json.dumps(public.get("reproducer"), indent=2)
        elif "expected" in lower:
            value = public.get(
                "expected", "Documented bundled operation completes successfully."
            )
        elif any(
            x in lower for x in ("bug", "summary", "description", "actual", "problem")
        ):
            value = public.get("actual", "Unexpected execution failure")
        elif any(
            x in lower
            for x in ("environment", "version", "desktop", "system", "installation")
        ):
            value = json.dumps(public.get("environment", {}), indent=2)
        elif any(
            x in lower for x in ("additional", "context", "log", "evidence", "config")
        ):
            value = "See the structured sanitized evidence below."
        elif any(x in lower for x in ("screenshot", "attachment")):
            value = "No private files or screenshots are attached."
        else:
            raise TransportError("repository_template_requires_mapping")
        sections.append("## " + Sanitizer().text(heading, 100) + "\n\n" + value)
    result = dict(payload, body="\n\n".join(sections) + "\n\n" + payload["body"])
    if labels:
        result["labels"] = labels
    return result, selected


def submit(receipt, state_dir, transport=None):
    state = Path(state_dir).expanduser().resolve()
    receipt = Path(receipt).resolve()
    if not receipt.is_relative_to(state) or receipt.name != "receipt.json":
        raise ValueError("Receipt must belong to this reporting state directory")
    transport = transport or GitHub()
    lock = receipt.parent / "submission.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {
            "ok": False,
            "status": "busy",
            "receipt": str(receipt),
            "submitted": False,
        }
    os.close(descriptor)
    try:
        record = read_json(receipt)
        if record.get("schema_version") != RECEIPT_VERSION:
            # Do not migrate an old, potentially published/uncertain identity or
            # send its regex-filtered free text. Keep its status/identity intact.
            return {
                "ok": False,
                "status": "requires_recapture",
                "reason": "legacy_public_diagnostics_require_private_recapture",
                "receipt": str(receipt),
                "issue": record.get("issue"),
                "submitted": False,
            }
        if fingerprint(record["public"]) != record.get("fingerprint"):
            raise ValueError(
                "Receipt identity changed; capture a new sanitized incident"
            )
        public = sanitize(record["public"])
        # Never submit an edited draft body or unknown fields from local receipts.
        if record.get("repository") != REPOSITORY or fingerprint(public) != record.get(
            "fingerprint"
        ):
            raise ValueError(
                "Receipt identity changed; capture a new sanitized incident"
            )
        record["public"] = public
        payload = render_issue(record)
        write_json(receipt.parent / "issue.json", payload)
        config = state / "policy.json"
        disabled = config.is_file() and read_json(config).get("mode") == "disabled"
        if disabled or record["status"] == "local_only":
            return {
                "ok": True,
                "status": "disabled" if disabled else "local_only",
                "receipt": str(receipt),
                "submitted": False,
            }
        if record["status"] in {"submitted", "duplicate"}:
            return {
                "ok": True,
                "status": record["status"],
                "issue": record["issue"],
                "submitted": False,
            }
        try:
            found = find_existing(transport, record["fingerprint"])
            if found:
                record.update(status="duplicate", issue=found, updated_at=now())
            elif record["status"] in {"submitting", "submission_uncertain"}:
                record.update(
                    status="submission_uncertain",
                    reason="Check the possibly created issue manually; no automatic second POST.",
                )
            else:
                payload, template = apply_template(transport, payload, public)
                write_json(receipt.parent / "issue.json", payload)
                record.update(
                    status="submitting",
                    updated_at=now(),
                    template=template,
                )
                write_json(
                    receipt, record
                )  # Durable intent BEFORE the external mutation.
                created = transport.request(
                    "POST", f"repos/{REPOSITORY}/issues", payload
                )
                found = issue_identity(created)
                if not found:
                    raise TransportError("github_creation_response_unreadable")
                record.update(status="submitted", issue=found, updated_at=now())
        except TransportError as exc:
            ambiguous = record["status"] == "submitting"
            record.update(
                status="submission_uncertain" if ambiguous else "pending",
                reason=exc.kind,
                updated_at=now(),
            )
            if ambiguous:
                try:
                    found = find_existing(transport, record["fingerprint"])
                    if found:
                        record.update(status="submitted", issue=found)
                except TransportError:
                    pass
        write_json(receipt, record)
        return {
            "ok": record["status"] in {"submitted", "duplicate"},
            "status": record["status"],
            "receipt": str(receipt),
            "issue": record.get("issue"),
            "reason": record.get("reason"),
            "submitted": record["status"] == "submitted",
        }
    finally:
        lock.unlink()


def readiness(state_dir):
    path = Path(state_dir).expanduser().resolve()
    config = path / "policy.json"
    mode = (
        read_json(config).get("mode", "automatic") if config.is_file() else "automatic"
    )
    gh = shutil.which("gh")
    authenticated = False
    if gh:
        try:
            authenticated = (
                subprocess.run(
                    [gh, "auth", "status", "--hostname", "github.com"],
                    capture_output=True,
                    timeout=5,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "optional": True,
        "repository": REPOSITORY,
        "mode": mode,
        "github_cli_available": bool(gh),
        "authenticated": authenticated,
        "submission_ready": mode == "automatic" and authenticated,
        "affects_modeling_readiness": False,
        "submission_account": SUBMISSION_ACCOUNT,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "OPENSTUDIO_AI_FAILURE_DIR", str(Path.cwd() / ".openstudio_ai_failures")
            )
        ),
    )
    commands = parser.add_subparsers(dest="action", required=True)
    event = commands.add_parser("capture")
    event.add_argument("--event", type=Path, required=True)
    send = commands.add_parser("submit")
    send.add_argument("--receipt", type=Path, required=True)
    commands.add_parser("pending")
    commands.add_parser("doctor")
    policy = commands.add_parser("policy")
    policy.add_argument("mode", choices=["automatic", "disabled"])
    args = parser.parse_args()
    try:
        if args.action == "capture":
            result = capture(read_json(args.event), args.state_dir)
        elif args.action == "submit":
            result = submit(args.receipt, args.state_dir)
        elif args.action == "doctor":
            result = readiness(args.state_dir)
        elif args.action == "policy":
            write_json(args.state_dir / "policy.json", {"mode": args.mode})
            result = {"ok": True, "mode": args.mode}
        else:
            items = []
            for path in sorted(args.state_dir.glob("*/receipt.json")):
                record = read_json(path)
                if record.get("status") not in {"submitted", "duplicate", "local_only"}:
                    items.append({"receipt": str(path), "status": record["status"]})
            result = {"ok": True, "pending": items[:20], "total": len(items)}
        print(json.dumps(result, allow_nan=False))
        return 0 if result.get("ok", True) else 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "reporting_unavailable",
                    "error": Sanitizer().text(exc, 200),
                    "submitted": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
