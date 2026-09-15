#!/usr/bin/env python3
"""Validate a Research Flow YAML or JSON file without modifying it."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import parse_project
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('file', type=Path)
a = p.parse_args()
try:
    document = parse_project(a.file.read_text(encoding='utf-8'))
except (OSError, ValueError, UnicodeError) as error:
    p.exit(1, f'Invalid project: {error}\n')
print(f'Valid: {document["project"]["name"]} — {len(document["tasks"])} tasks, '
      f'{sum(len(t["depends_on"]) for t in document["tasks"])} dependencies')
