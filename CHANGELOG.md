# Changelog

## Unreleased

- When default port 8765 is occupied, try successive ports and warn with the
  selected port. The private URL, local browser launch, and forwarding instructions
  use the bound port; other explicit ports retain their fixed-port behavior.

## 0.8.6 — default to creating a workflow

- The new-workflow prompt now defaults to Yes: Enter, `y`, or `yes` creates the file.
  Explicit No, Ctrl+C, or EOF still cancels without creating files.
- Esc cancels the terminal prompt immediately, without requiring Enter.

## 0.8.5 — confirm new workflow creation

- Ask before creating `workflow.yaml` when no YAML file is found in the current
  folder. Show the destination path and default to No; cancellation creates no files.
- Keep `--init` as the explicit option for scripts and services. Noninteractive
  launches without an existing workflow or `--init` exit with guidance.
- Existing workflows, multiple-file selection, and `--print-url` are unchanged.

## 0.8.4 — canvas editing and numbered steps

- Moved Arrange and Step list into the canvas toolbar.
- Added double-click card renaming, with Enter to apply and Escape to cancel.
- Added a delete button on each card using the existing confirmation and undo.
- Grouped parents and descendants in the list with indentation and derived numbers.
- Added editable main-step numbers. Child numbers follow automatically; assigning
  an occupied main number swaps the two roots. Number edits persist in YAML and
  undo together without changing task IDs, relationships, or canvas positions.

## 0.8.3 — repository and setup cleanup

- Removed one-time publishing helpers, their manifest, the unused validation
  wrapper and blank example, and the superseded simulated transport harness.
- Removed unused task-suggestion helpers and their tests; kept workflow editing,
  validation, persistence, installation, migration, and browser regression coverage.
- Grouped browser checks under `tests/browser/`, consolidated dependencies in
  `pyproject.toml`, and replaced historical test reports with current instructions.

- Simplified the README and updated the tagline to “from action to completion.”
- Made VS Code integrated browser remote access the main remote setup, with
  manual forwarding documented as an optional alternative.

## 0.8.2 — use the current research folder

- With no `--project`, open the only YAML/YML file in the current directory; create
  `workflow.yaml` if none exists, and require an explicit choice if several exist.
- Preserve existing YAML until Save and report invalid workflows without replacing
  them. Explicit `--project` paths bypass discovery.
- Keep the systemd template on an explicit data path and document migration from
  the previous global default. Existing workflows are never moved or deleted.
- Add regression and installed-app checks for discovery and saving in the launch
  directory, including filenames with spaces and arbitrary workflow filenames.

## 0.8.1 — installable Linux/server app

- Added a pipx-compatible Python distribution and `research-flow` command, with all
  browser assets bundled. Existing source-checkout launchers remain supported.
- Added installation, update, and VS Code Remote-SSH instructions.
- Added isolated wheel/source-distribution installation checks to Linux CI.
- Published the source repository publicly; running servers remain token-protected.

- Reject non-string task IDs and statuses in the browser, matching server validation.
- Return a validation error for extremely large integers instead of overflowing
  during the server's numeric-range check. Added regression coverage for both fixes.

## 0.8.0 — Linux deployment cleanup

- Consolidated the 0.7.1 application and the approved thin rectangular divider.
- Preserved current graph/branch editing and the animated SVG logo.
- Headless startup by default; optional browser opening is explicit.
- Private access-token protection for server API reads/writes, in addition to the
  existing loopback, Host, Origin and custom-header restrictions.
- Explicit alternate browser port for SSH local forwarding; private URL recovery.
- Project data defaults outside the source checkout. Missing explicit paths require
  `--init`, which never overwrites an existing file.
- Kept conflict detection, backups, previous substep conversion and schema version 1.
- Pure standalone HTML builder; generated output, verification logs, previous full
  app snapshots, redundant screenshots and obsolete update files removed from source.
- Added Linux deployment notes, optional user-service template, manifest-based private
  GitHub publishing, security notes, CI and Linux/transport regression checks.
- No new runtime dependencies, external font files, dashboard or workflow features.

## Existing 0.7.1 behavior retained

Nested child cards, contextual branch adoption for newly connected cards, collapse,
branch dragging, explicit reparenting, global minimap, editable dependency arrows,
in-page deletion confirmation, explicit save and undo/redo.
