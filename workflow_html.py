"""Self-contained HTML snapshots of validated Research Flow documents.

The caller supplies the saved timestamp so rendering is reproducible and never
changes project data, source assets, or files on disk.
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path
import re


WEB = Path(__file__).resolve().parent / 'web'


def _script_json(value):
    # A JSON script element is still parsed as HTML; never allow a closing tag.
    return json.dumps(value, ensure_ascii=True).replace('<', '\\u003c')


def render_workflow_html(document, *, read_only=True, layout_mode='stages', saved_at=None):
    """Bundle a validated document with local assets, without network resources."""
    if layout_mode not in ('stages', 'freeform'):
        raise ValueError('Preview layout must be stages or freeform.')
    if read_only and (not isinstance(saved_at, str) or not saved_at):
        raise ValueError('A saved timestamp is required for a read-only preview.')
    template = (WEB / 'index.html').read_text(encoding='utf-8')
    template = re.sub(r'(<script id="initial-project" type="application/json">).*?(</script>)',
                      lambda match: match[1] + _script_json(document) + match[2], template, flags=re.S)
    title = html.escape(f'{document["project"]["name"]} · Research Flow', quote=True)
    template = re.sub(r'<title>.*?</title>', lambda match: f'<title>{title}</title>', template, flags=re.S)
    for variant in ('light', 'dark'):
        path = f'assets/research-flow-icon-{variant}.svg'
        data = base64.b64encode((WEB / path).read_bytes()).decode('ascii')
        template = template.replace(f'href="{path}"', f'href="data:image/svg+xml;base64,{data}"')
    model = re.sub(r'^export\s+', '', (WEB / 'model.mjs').read_text(encoding='utf-8'), flags=re.M)
    connection = re.sub(r'^export\s+', '', (WEB / 'connection.mjs').read_text(encoding='utf-8'), flags=re.M)
    layers = re.sub(r'^import\s+.*?;\s*', '', (WEB / 'layers.mjs').read_text(encoding='utf-8'), flags=re.M | re.S)
    layers = re.sub(r'^export\s+', '', layers, flags=re.M)
    app = re.sub(r'^import\s+.*?;\s*', '', (WEB / 'app.js').read_text(encoding='utf-8'), flags=re.M | re.S)
    css = (WEB / 'styles.css').read_text(encoding='utf-8')
    template = re.sub(r'<link\b[^>]*href="styles\.css"[^>]*>',
                      lambda match: f'<style>{css}</style>', template)
    settings = 'window.RESEARCH_FLOW_PREVIEW = true;\n'
    if read_only:
        settings += 'window.RESEARCH_FLOW_VIEWER = ' + _script_json({
            'saved_at': saved_at, 'layout_mode': layout_mode,
        }) + ';\n'
    code = settings + model + '\n' + connection + '\n' + layers + '\n' + app
    return re.sub(r'<script\b[^>]*src="app\.js"[^>]*></script>',
                  lambda match: '<script type="module">\n' + code.replace('</script', '<\\/script') + '\n</script>', template)
