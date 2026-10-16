#!/usr/bin/env python3
"""Build a portable HTML without changing any tracked source or project file."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import parse_project
from workflow_html import render_workflow_html


def build(project_path=None, output=None, *, read_only=False, layout_mode='stages'):
    project_path = Path(project_path or ROOT / 'examples/research-project.yaml')
    output = Path(output or ROOT / 'dist/research-flow.html')
    project = parse_project(project_path.read_text(encoding='utf-8'))
    preview = render_workflow_html(
        project, read_only=read_only, layout_mode=layout_mode,
        saved_at=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(preview, encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--read-only', action='store_true', help='Build an offline viewer instead of an editable copy.')
    parser.add_argument('--layout', choices=('stages', 'freeform'), default='stages')
    args = parser.parse_args()
    try:
        output = build(args.project, args.output, read_only=args.read_only, layout_mode=args.layout)
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(1, f'Build failed: {error}\n')
    print(f'Built {output} ({output.stat().st_size:,} bytes)')
