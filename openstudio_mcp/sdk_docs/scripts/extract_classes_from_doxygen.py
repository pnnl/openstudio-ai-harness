#!/usr/bin/env python3
"""
Extract class information from Doxygen HTML documentation.
Generates classes.yaml (and a gzip-compressed classes.yaml.gz) for AI-friendly documentation.

Usage:
    python extract_classes_from_doxygen.py <doxygen_html_dir> [--output-dir <dir>]

    <doxygen_html_dir>  Path to the Doxygen-generated HTML directory (contains class*.html files).
    --output-dir        Where to write output files. Defaults to ./docs/api/ next to this script.
"""

import argparse
import gzip
import re
import shutil
from pathlib import Path
from bs4 import BeautifulSoup
import yaml
from typing import Dict, List, Optional
from collections import defaultdict


def _detect_version(html_dir: Path) -> str:
    """Try to read the OpenStudio version from the Doxygen index page."""
    index = html_dir / "index.html"
    if index.is_file():
        try:
            soup = BeautifulSoup(index.read_text(encoding="utf-8", errors="ignore"), "html.parser")
            # Doxygen puts the project version in <span id="projectnumber">
            elem = soup.find(id="projectnumber")
            if elem:
                version = elem.get_text().strip()
                if version:
                    return version
            # Fallback: look for a <title> containing a version-like token
            title = soup.find("title")
            if title:
                match = re.search(r"\b(\d+\.\d+\.\d+)\b", title.get_text())
                if match:
                    return match.group(1)
        except Exception:
            pass
    return "unknown"


class DoxygenClassExtractor:
    def __init__(self, doc_output_dir: str, openstudio_version: str = "unknown"):
        self.doc_output_dir = Path(doc_output_dir)
        self.openstudio_version = openstudio_version
        self.classes = {}
        self.namespaces = defaultdict(list)

    def extract_all_classes(self) -> Dict:
        """Extract all classes from Doxygen HTML files"""
        print(f"Scanning {self.doc_output_dir} for class documentation...")

        class_files = list(self.doc_output_dir.glob('class*.html'))
        print(f"Found {len(class_files)} class files")

        for class_file in class_files:
            try:
                class_data = self.extract_class_from_file(class_file)
                if class_data:
                    class_name = class_data['name']
                    self.classes[class_name] = class_data

                    namespace = class_data.get('namespace', 'global')
                    self.namespaces[namespace].append(class_name)

            except Exception as e:
                print(f"Error processing {class_file.name}: {e}")
                continue

        print(f"Successfully extracted {len(self.classes)} classes")
        return self.organize_classes()

    def extract_class_from_file(self, html_file: Path) -> Optional[Dict]:
        """Extract class information from a single HTML file"""
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

        title = soup.find('title')
        if not title:
            return None

        title_text = title.get_text()

        if 'Class' not in title_text and 'Struct' not in title_text:
            return None

        class_name = self.extract_class_name(soup)
        if not class_name:
            return None

        # Skip internal implementation classes (pimpl pattern, not public API)
        if class_name.endswith('_Impl'):
            return None

        print(f"  Processing: {class_name}")

        class_data = {
            'name': class_name,
            'namespace': self.extract_namespace(soup, class_name),
            'description': self.extract_description(soup),
            'parent': self.extract_parent_class(soup),
            'derived_classes': self.extract_derived_classes(soup),
            'file_location': self.extract_file_location(soup),
            'public_methods': self.extract_methods(soup, 'Public Member Functions'),
            'protected_methods': self.extract_methods(soup, 'Protected Member Functions'),
            'static_methods': self.extract_methods(soup, 'Static Public Member Functions'),
            'public_types': self.extract_types(soup),
            'is_abstract': self.check_if_abstract(soup),
            'template_parameters': self.extract_template_params(soup),
        }

        class_data['python'] = self.infer_python_name(class_data['namespace'], class_name)

        return class_data

    def extract_class_name(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the class name"""
        title_elem = soup.find('div', class_='title')
        if title_elem:
            title_text = title_elem.get_text().strip()
            if '::' in title_text:
                return title_text.split('::')[-1].split()[0]
            return title_text.split()[0]

        title = soup.find('title')
        if title:
            match = re.search(r'(\w+)\s+Class', title.get_text())
            if match:
                return match.group(1)

        return None

    def extract_namespace(self, soup: BeautifulSoup, class_name: str) -> str:
        """Extract the namespace"""
        breadcrumb = soup.find('div', class_='header')
        if breadcrumb:
            text = breadcrumb.get_text()
            if '::' in text:
                parts = text.split('::')
                if parts[-1].strip() == class_name:
                    return '::'.join(parts[:-1])

        title_div = soup.find('div', class_='title')
        if title_div:
            text = title_div.get_text()
            if '::' in text:
                parts = text.split('::')
                if len(parts) > 1:
                    return '::'.join(parts[:-1]).strip()

        return 'openstudio'

    def extract_description(self, soup: BeautifulSoup) -> str:
        """Extract the brief description"""
        brief = soup.find('div', class_='textblock')
        if brief:
            first_p = brief.find('p')
            if first_p:
                desc = first_p.get_text().strip()
                desc = re.sub(r'\s+', ' ', desc)
                return desc

        contents = soup.find('div', class_='contents')
        if contents:
            text = contents.get_text().strip()
            sentences = text.split('.')
            if sentences:
                return sentences[0].strip() + '.'

        return "No description available"

    def extract_parent_class(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract parent/base class"""
        inherit_div = soup.find('div', class_='inherit')
        if inherit_div:
            links = inherit_div.find_all('a')
            if links:
                parent_text = links[-1].get_text()
                if '::' in parent_text:
                    return parent_text.split('::')[-1]
                return parent_text

        textblocks = soup.find_all('div', class_='textblock')
        for block in textblocks:
            text = block.get_text()
            if 'Inherits' in text or 'inherits' in text:
                match = re.search(r'Inherits?\s+(?:from\s+)?(\w+(?:::\w+)*)', text)
                if match:
                    parent = match.group(1)
                    if '::' in parent:
                        return parent.split('::')[-1]
                    return parent

        return None

    def extract_derived_classes(self, soup: BeautifulSoup) -> List[str]:
        """Extract derived/child classes"""
        derived = []

        textblocks = soup.find_all('div', class_='textblock')
        for block in textblocks:
            text = block.get_text()
            if 'Inherited by' in text:
                links = block.find_all('a', class_='el')
                for link in links:
                    class_name = link.get_text()
                    if '::' in class_name:
                        class_name = class_name.split('::')[-1]
                    derived.append(class_name)

        return derived

    def extract_file_location(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract source file location"""
        text = soup.get_text()
        match = re.search(r'Definition (?:at line \d+ )?of file ([^\s\.]+\.(?:hpp|h|cpp))', text)
        if match:
            return f"src/{match.group(1)}"

        match = re.search(r'#include\s+[<"]([^>"]+)[>"]', text)
        if match:
            return match.group(1)

        return None

    def extract_methods(self, soup: BeautifulSoup, section_name: str) -> List[Dict]:
        """Extract methods from a specific section"""
        methods = []

        for table in soup.find_all('table', class_='memberdecls'):
            heading = table.find('tr', class_='heading')
            if not heading or section_name not in heading.get_text():
                continue
            for row in table.find_all('tr'):
                classes = row.get('class', [])
                row_key = next((c for c in classes if c.startswith('memitem:')), None)
                if not row_key:
                    continue
                suffix = row_key.split(':', 1)[1]
                desc_row = table.find('tr', class_=lambda c: c and f'memdesc:{suffix}' in c)
                method = self.parse_method_row(row, desc_row)
                if method:
                    methods.append(method)

        return methods

    def parse_method_row(self, row, desc_row=None) -> Optional[Dict]:
        """Parse a method from a memberdecls table row"""
        left_td = row.find('td', class_='memItemLeft')
        right_td = row.find('td', class_='memItemRight')

        if not right_td:
            return None

        return_type = re.sub(r'\s+', ' ', left_td.get_text(separator=' ', strip=True)) if left_td else ''
        sig_text = re.sub(r'\s+', ' ', right_td.get_text(separator=' ', strip=True))

        if return_type and return_type not in ('', 'virtual', 'static', 'explicit'):
            signature = f"{return_type} {sig_text}".strip()
        else:
            signature = f"{return_type} {sig_text}".strip() if return_type else sig_text

        match = re.match(r'(\w+)\s*\(', sig_text)
        if not match:
            return None
        method_name = match.group(1)

        description = None
        if desc_row:
            desc = desc_row.get_text(separator=' ', strip=True)
            desc = re.sub(r'\s+', ' ', desc).strip()
            if desc:
                description = desc

        return {
            'name': method_name,
            'signature': signature,
            'description': description,
        }

    def extract_types(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract public types (enums, typedefs)"""
        types = []

        sections = soup.find_all('h2', class_='groupheader')
        for section in sections:
            if 'Public Types' in section.get_text():
                table = section.find_next('table', class_='memberdecls')
                if table:
                    rows = table.find_all('tr', class_='memitem')
                    for row in rows:
                        type_def = row.find('td', class_='memname')
                        if type_def:
                            types.append({
                                'name': type_def.get_text().strip(),
                                'definition': row.get_text(strip=True)
                            })

        return types

    def check_if_abstract(self, soup: BeautifulSoup) -> bool:
        """Check if class is abstract"""
        text = soup.get_text()
        return 'pure virtual' in text.lower() or 'abstract' in text.lower()

    def extract_template_params(self, soup: BeautifulSoup) -> Optional[List[str]]:
        """Extract template parameters if any"""
        title_div = soup.find('div', class_='title')
        if title_div:
            text = title_div.get_text()
            match = re.search(r'template\s*<([^>]+)>', text)
            if match:
                params = match.group(1).split(',')
                return [p.strip() for p in params]
        return None

    def infer_python_name(self, namespace: str, class_name: str) -> str:
        """Infer Python module path"""
        if namespace and '::' in namespace:
            python_module = namespace.replace('::', '.')
            return f"{python_module}.{class_name}"
        return f"openstudio.{class_name}"

    def organize_classes(self) -> Dict:
        """Organize classes by namespace and category"""
        import datetime
        organized = {
            'metadata': {
                'total_classes': len(self.classes),
                'namespaces': len(self.namespaces),
                'extraction_date': datetime.date.today().isoformat(),
                'openstudio_version': self.openstudio_version,
            },
            'namespaces': {}
        }

        for namespace, class_list in self.namespaces.items():
            organized['namespaces'][namespace] = {
                'class_count': len(class_list),
                'classes': {}
            }

            for class_name in class_list:
                if class_name in self.classes:
                    organized['namespaces'][namespace]['classes'][class_name] = self.classes[class_name]

        organized['categories'] = self.categorize_classes()

        return organized

    def build_methods_catalog(self) -> Dict:
        """Build a flat methods.yaml catalog across all classes"""
        import datetime
        methods = {}
        total = 0

        for class_name, class_data in self.classes.items():
            for visibility, method_list in (
                ('public', class_data.get('public_methods', [])),
                ('protected', class_data.get('protected_methods', [])),
                ('static', class_data.get('static_methods', [])),
            ):
                for method in method_list:
                    key = f"{class_name}.{method['name']}"
                    if key in methods:
                        i = 2
                        while f"{key}_{i}" in methods:
                            i += 1
                        key = f"{key}_{i}"
                    methods[key] = {
                        'class': class_name,
                        'namespace': class_data.get('namespace', ''),
                        'name': method['name'],
                        'signature': method.get('signature', ''),
                        'description': method.get('description', ''),
                        'visibility': visibility,
                    }
                    total += 1

        return {
            'metadata': {
                'total_methods': total,
                'extraction_date': __import__('datetime').date.today().isoformat(),
                'openstudio_version': self.openstudio_version,
            },
            'methods': methods,
        }

    def categorize_classes(self) -> Dict:
        """Categorize classes by functionality"""
        categories = {
            'core': [],
            'geometry': [],
            'hvac': [],
            'loads': [],
            'schedules': [],
            'materials': [],
            'simulation': [],
            'utilities': [],
            'other': []
        }

        geometry_keywords = ['Space', 'Surface', 'Point', 'Vector', 'Vertex', 'Plane', 'Geometry']
        hvac_keywords = ['AirLoop', 'PlantLoop', 'Zone', 'Coil', 'Fan', 'Pump', 'Boiler', 'Chiller', 'HVAC']
        load_keywords = ['People', 'Lights', 'Equipment', 'Load', 'Infiltration', 'Ventilation']
        schedule_keywords = ['Schedule', 'Ruleset', 'ScheduleTypeLimits']
        material_keywords = ['Material', 'Construction', 'Layer', 'Glazing', 'Gas']
        simulation_keywords = ['Simulation', 'RunPeriod', 'SizingPeriod', 'Weather', 'Output']
        core_keywords = ['Model', 'Building', 'Site', 'Facility']

        for class_name in self.classes:
            categorized = False

            if any(kw in class_name for kw in core_keywords):
                categories['core'].append(class_name)
                categorized = True
            elif any(kw in class_name for kw in geometry_keywords):
                categories['geometry'].append(class_name)
                categorized = True
            elif any(kw in class_name for kw in hvac_keywords):
                categories['hvac'].append(class_name)
                categorized = True
            elif any(kw in class_name for kw in load_keywords):
                categories['loads'].append(class_name)
                categorized = True
            elif any(kw in class_name for kw in schedule_keywords):
                categories['schedules'].append(class_name)
                categorized = True
            elif any(kw in class_name for kw in material_keywords):
                categories['materials'].append(class_name)
                categorized = True
            elif any(kw in class_name for kw in simulation_keywords):
                categories['simulation'].append(class_name)
                categorized = True
            elif 'openstudio::' in self.classes[class_name].get('namespace', '') and \
                 'model' not in self.classes[class_name].get('namespace', ''):
                categories['utilities'].append(class_name)
                categorized = True

            if not categorized:
                categories['other'].append(class_name)

        return categories


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
        description="Extract OpenStudio class docs from Doxygen HTML and write YAML + GZ files."
    )
    parser.add_argument(
        "doxygen_html_dir",
        help="Path to the Doxygen-generated HTML directory (contains class*.html files).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory where output files are written. "
            "Defaults to <script_dir>/docs/api/. "
            "Files are named classes-<version>.yaml and classes-<version>.yaml.gz."
        ),
    )
    args = parser.parse_args()

    html_dir = Path(args.doxygen_html_dir).expanduser().resolve()
    if not html_dir.exists():
        print(f"Error: {html_dir} does not exist")
        return 1

    version = _detect_version(html_dir)
    print(f"Detected OpenStudio version: {version}")

    extractor = DoxygenClassExtractor(html_dir, openstudio_version=version)
    classes_data = extractor.extract_all_classes()
    methods_data = extractor.build_methods_catalog()

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else \
        Path(__file__).parent.parent / 'docs' / 'api'

    version_slug = version.replace(' ', '_')
    classes_path = output_dir / f"classes-{version_slug}.yaml"
    methods_path = output_dir / f"methods-{version_slug}.yaml"

    print(f"\nWriting outputs to {output_dir} ...")
    _write_yaml_and_gz(classes_data, classes_path)
    _write_yaml_and_gz(methods_data, methods_path)

    print(f"\nExtraction complete!")
    print(f"  OpenStudio version : {version}")
    print(f"  Total classes      : {classes_data['metadata']['total_classes']}")
    print(f"  Namespaces         : {classes_data['metadata']['namespaces']}")
    print(f"  Total methods      : {methods_data['metadata']['total_methods']}")
    print(f"\nCategories:")
    for category, classes in classes_data['categories'].items():
        if classes:
            print(f"  {category}: {len(classes)} classes")

    print(f"\nTop 10 classes by method count:")
    class_method_counts = []
    for namespace_data in classes_data['namespaces'].values():
        for class_name, class_data in namespace_data['classes'].items():
            method_count = len(class_data.get('public_methods', []))
            class_method_counts.append((class_name, method_count))

    class_method_counts.sort(key=lambda x: x[1], reverse=True)
    for class_name, count in class_method_counts[:10]:
        print(f"  {class_name}: {count} methods")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
