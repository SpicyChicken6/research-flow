# Changelog

## Unreleased — first-upload review

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
