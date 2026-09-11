#!/usr/bin/env python3
"""
Parse an EnergyPlus or OpenStudio IDD file and generate a YAML + GZ schema file.

Usage:
    python extract_idd_to_yaml.py <idd_file> [--output-dir <dir>]

    <idd_file>       Path to the .idd file to parse.
    --output-dir     Where to write output files. Defaults to <script_dir>/docs/schemas/.
                     Files are named <stem>-<version>.yaml and <stem>-<version>.yaml.gz.
"""

import argparse
import datetime
import gzip
import re
import shutil
from pathlib import Path
from typing import Dict, Optional
import yaml


def parse_idd(idd_path: Path) -> Dict:
    """Parse an EnergyPlus or OpenStudio IDD file into a structured dict."""
    text = idd_path.read_text(encoding='utf-8', errors='replace')
    lines = text.splitlines()

    version_match = re.search(r'!IDD_Version\s+(\S+)', text)
    version = version_match.group(1) if version_match else 'unknown'

    groups = {}
    current_group = 'Ungrouped'
    current_object = None
    current_field = None
    objects = {}

    def flush_field():
        nonlocal current_field
        if current_object and current_field:
            current_object['fields'].append(current_field)
            current_field = None

    def flush_object():
        nonlocal current_object
        if current_object:
            flush_field()
            name = current_object['name']
            objects[name] = current_object
            groups.setdefault(current_group, []).append(name)
            current_object = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        m = re.match(r'\\group\s+(.*)', stripped)
        if m:
            current_group = m.group(1).strip()
            i += 1
            continue

        # Object definition: word(s) followed by a comma, not a comment
        if stripped and not stripped.startswith('!') and re.match(r'^[A-Za-z][A-Za-z0-9:_\-\s]*,$', stripped):
            flush_object()
            obj_name = stripped.rstrip(',').strip()
            current_object = {
                'name': obj_name,
                'group': current_group,
                'memo': [],
                'unique': False,
                'required': False,
                'min_fields': None,
                'extensible': None,
                'fields': [],
            }
            current_field = None
            i += 1
            continue

        if current_object is None:
            i += 1
            continue

        m = re.match(r'\\memo\s*(.*)', stripped)
        if m:
            current_object['memo'].append(m.group(1).strip())
            i += 1
            continue

        if re.match(r'\\unique-object', stripped):
            current_object['unique'] = True
            i += 1
            continue

        if re.match(r'\\required-object', stripped):
            current_object['required'] = True
            i += 1
            continue

        m = re.match(r'\\min-fields\s+(\d+)', stripped)
        if m:
            current_object['min_fields'] = int(m.group(1))
            i += 1
            continue

        m = re.match(r'\\extensible\s*:?\s*(\d+)', stripped)
        if m:
            current_object['extensible'] = int(m.group(1))
            i += 1
            continue

        # Field declaration: A1, N1, A2, etc.
        m = re.match(r'^([AN]\d+)\s*[,;]', stripped)
        if m:
            flush_field()
            current_field = {
                'id': m.group(1),
                'name': None,
                'note': [],
                'type': None,
                'required': False,
                'autosizable': False,
                'autocalculatable': False,
                'default': None,
                'minimum': None,
                'maximum': None,
                'units': None,
                'ip_units': None,
                'keys': [],
                'object_list': [],
                'reference': [],
                'deprecated': False,
            }
            i += 1
            continue

        if current_field is None:
            i += 1
            continue

        m = re.match(r'\\field\s+(.*)', stripped)
        if m:
            current_field['name'] = m.group(1).strip()
            i += 1
            continue

        m = re.match(r'\\note\s+(.*)', stripped)
        if m:
            current_field['note'].append(m.group(1).strip())
            i += 1
            continue

        m = re.match(r'\\type\s+(.*)', stripped)
        if m:
            current_field['type'] = m.group(1).strip()
            i += 1
            continue

        if re.match(r'\\required-field', stripped):
            current_field['required'] = True
            i += 1
            continue

        if re.match(r'\\autosizable', stripped):
            current_field['autosizable'] = True
            i += 1
            continue

        if re.match(r'\\autocalculatable', stripped):
            current_field['autocalculatable'] = True
            i += 1
            continue

        m = re.match(r'\\default\s+(.*)', stripped)
        if m:
            val = m.group(1).strip()
            try:
                current_field['default'] = int(val)
            except ValueError:
                try:
                    current_field['default'] = float(val)
                except ValueError:
                    current_field['default'] = val
            i += 1
            continue

        m = re.match(r'\\minimum>\s*(.*)', stripped)
        if m:
            current_field['minimum'] = f'>{m.group(1).strip()}'
            i += 1
            continue

        m = re.match(r'\\minimum\s+(.*)', stripped)
        if m:
            current_field['minimum'] = m.group(1).strip()
            i += 1
            continue

        m = re.match(r'\\maximum<\s*(.*)', stripped)
        if m:
            current_field['maximum'] = f'<{m.group(1).strip()}'
            i += 1
            continue

        m = re.match(r'\\maximum\s+(.*)', stripped)
        if m:
            current_field['maximum'] = m.group(1).strip()
            i += 1
            continue

        m = re.match(r'\\ip-units\s+(.*)', stripped)
        if m:
            current_field['ip_units'] = m.group(1).strip()
            i += 1
            continue

        m = re.match(r'\\units\s+(.*)', stripped)
        if m:
            current_field['units'] = m.group(1).strip()
            i += 1
            continue

        m = re.match(r'\\key\s+(.*)', stripped)
        if m:
            current_field['keys'].append(m.group(1).strip())
            i += 1
            continue

        m = re.match(r'\\object-list\s+(.*)', stripped)
        if m:
            current_field['object_list'].append(m.group(1).strip())
            i += 1
            continue

        m = re.match(r'\\reference\s+(.*)', stripped)
        if m:
            current_field['reference'].append(m.group(1).strip())
            i += 1
            continue

        if re.match(r'\\deprecated', stripped):
            current_field['deprecated'] = True
            i += 1
            continue

        i += 1

    flush_object()

    def compact(obj):
        out = {}
        for k, v in obj.items():
            if v is None or v == [] or v is False:
                continue
            if k == 'fields':
                out[k] = [compact_field(f) for f in v]
            else:
                out[k] = v
        return out

    def compact_field(f):
        return {k: v for k, v in f.items() if v is not None and v != [] and v is not False}

    return {
        'metadata': {
            'version': version,
            'source': idd_path.name,
            'total_objects': len(objects),
            'total_groups': len(groups),
            'extraction_date': datetime.date.today().isoformat(),
        },
        'groups': dict(groups),
        'objects': {name: compact(obj) for name, obj in objects.items()},
    }


def _write_yaml_and_gz(data: dict, path: Path) -> None:
    """Write a YAML file and its gzip-compressed counterpart."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    gz_path = path.with_suffix(path.suffix + '.gz')
    with open(path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)
    print(f"  Written: {path}")
    print(f"  Written: {gz_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse an IDD file and write a YAML + GZ schema file."
    )
    parser.add_argument(
        "idd_file",
        help="Path to the .idd file to parse.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory where output files are written. "
            "Defaults to <script_dir>/docs/schemas/. "
            "Files are named <idd-stem>-<version>.yaml and <idd-stem>-<version>.yaml.gz."
        ),
    )
    args = parser.parse_args()

    idd_path = Path(args.idd_file).expanduser().resolve()
    if not idd_path.exists():
        print(f"Error: {idd_path} does not exist")
        return 1

    print(f"Parsing {idd_path.name} ...")
    data = parse_idd(idd_path)
    version = data['metadata']['version']
    print(f"  IDD version : {version}")
    print(f"  Objects     : {data['metadata']['total_objects']}")
    print(f"  Groups      : {data['metadata']['total_groups']}")

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else \
        Path(__file__).parent.parent / 'docs' / 'schemas'

    version_slug = version.replace(' ', '_')
    stem = idd_path.stem.lower()
    out_path = output_dir / f"{stem}-{version_slug}.yaml"

    print(f"\nWriting outputs to {output_dir} ...")
    _write_yaml_and_gz(data, out_path)

    size_mb = out_path.stat().st_size / 1e6
    print(f"\nDone — {size_mb:.1f} MB")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
