"""Validate the machine-readable repository map without optional dependencies."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
project = json.loads((root / 'PROJECT_MAP.json').read_text(encoding='utf-8'))
for group in ('entry_points', 'modules', 'documentation'):
    for item in project[group]:
        path = (root / item['path']).resolve()
        if root not in path.parents or not path.is_file():
            raise SystemExit('Invalid project-map path: ' + item['path'])
for path in (root / 'examples').rglob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
print('Project map and example JSON are valid.')
