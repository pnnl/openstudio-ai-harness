"""Bounded failure reports without values, snapshots or model dumps."""

from collections import Counter
import re

MAX_DIFFERENCES = 12
MAX_PATH_LENGTH = 180
MAX_TYPES = 24


class DiagnosticError(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def failure_report(exc, operation=None):
    report = dict(ok=False, ready=False, mode="inspect_only", error=str(exc)[:1200])
    report.update(getattr(exc, "details", {}))
    if operation:
        report["operation"] = operation
    return report


def type_counts(values):
    counts = Counter(values)
    names = sorted(counts)
    result = {name: counts[name] for name in names[:MAX_TYPES]}
    if len(names) > MAX_TYPES:
        result["other_types"] = sum(counts[name] for name in names[MAX_TYPES:])
    return result


def handle_changes(before, after):
    removed, added = before.keys() - after.keys(), after.keys() - before.keys()
    return dict(
        removed_count=len(removed),
        added_count=len(added),
        removed_by_type=type_counts(before[h] for h in removed),
        added_by_type=type_counts(after[h] for h in added),
    )


def mismatch(reviewed, fresh, message="Reviewed plan differs from fresh preflight"):
    """The caller still compares reports exactly; only diagnostics are bounded."""
    differences = []
    truncated = False

    def add(path, category):
        nonlocal truncated
        if len(differences) == MAX_DIFFERENCES:
            truncated = True
            return
        differences.append(
            dict(path=(path or "/")[:MAX_PATH_LENGTH], category=category)
        )

    def escape(key):
        return str(key).replace("~", "~0").replace("/", "~1")

    def visit(left, right, path=""):
        if truncated:
            return
        if type(left) is not type(right):
            add(path, "changed_type")
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys()):
                child = path + "/" + escape(key)
                if key not in left or key not in right:
                    add(child, "handle_churn" if uuid(key) else "changed_structure")
                else:
                    visit(left[key], right[key], child)
                if truncated:
                    break
        elif isinstance(left, list):
            if len(left) != len(right):
                add(path, "changed_length")
            for i, (a, b) in enumerate(zip(left, right)):
                visit(a, b, path + "/" + str(i))
                if truncated:
                    break
        elif left != right:
            category = "changed_value"
            if path.endswith("/input_sha256"):
                category = "stale_source"
            elif path.endswith("/handle") or uuid(left) or uuid(right):
                category = "handle_churn"
            add(path, category)

    visit(reviewed, fresh)
    return DiagnosticError(
        message,
        status="plan_mismatch",
        diagnostic=dict(
            differences=differences, truncated=truncated, limit=MAX_DIFFERENCES
        ),
    )


def uuid(value):
    return isinstance(value, str) and bool(
        re.fullmatch(
            r"\{?[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}?", value
        )
    )
