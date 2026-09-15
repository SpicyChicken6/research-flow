#!/usr/bin/env python3
"""Build a portable HTML without changing any tracked source or project file."""
import argparse
import base64
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import parse_project


def build(project_path=None, output=None):
    project_path = Path(project_path or ROOT / 'examples/research-project.yaml')
    output = Path(output or ROOT / 'dist/research-flow.html')
    project = parse_project(project_path.read_text(encoding='utf-8'))
    template = (ROOT / 'web/index.html').read_text(encoding='utf-8')
    initial = json.dumps(project, ensure_ascii=False).replace('<', '\\u003c')
    template = re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',
                      lambda m: m[1] + initial + m[2], template, flags=re.S)
    for variant in ('light', 'dark'):
        path = f'assets/research-flow-icon-{variant}.svg'
        data = base64.b64encode((ROOT / 'web' / path).read_bytes()).decode('ascii')
        template = template.replace(f'href="{path}"', f'href="data:image/svg+xml;base64,{data}"')
    model = (ROOT / 'web/model.mjs').read_text(encoding='utf-8')
    model = re.sub(r'^export\s+', '', model, flags=re.M)
    connection = (ROOT / 'web/connection.mjs').read_text(encoding='utf-8')
    connection = re.sub(r'^export\s+', '', connection, flags=re.M)
    app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
    app = re.sub(r'^import\s+.*?;\s*', '', app, flags=re.M | re.S)
    css = (ROOT / 'web/styles.css').read_text(encoding='utf-8')
    preview = re.sub(r'<link\b[^>]*href="styles\.css"[^>]*>',
                     lambda m: f'<style>{css}</style>', template)
    code = 'window.RESEARCH_FLOW_PREVIEW = true;\n' + model + '\n' + connection + '\n' + app
    preview = re.sub(r'<script\b[^>]*src="app\.js"[^>]*></script>',
                     lambda m: '<script type="module">\n' + code.replace('</script', '<\\/script') + '\n</script>', preview)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(preview, encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        output = build(args.project, args.output)
    except (OSError, ValueError, UnicodeError) as error:
        parser.exit(1, f'Build failed: {error}\n')
    print(f'Built {output} ({output.stat().st_size:,} bytes)')
