# Research Flow development contract

- Preserve the current minimal single-project design; do not reintroduce dashboards,
  project loading, status suggestions, nested checklists or font selectors.
- Keep blank-card insertion, graph connections, child branches, focus/overview,
  global minimap, delete confirmation, undo/redo and the fixed-arrow logo animation.
- Project hierarchy (`parent_id`) is different from dependencies (`depends_on`).
  Branch adoption is only for new, unambiguous connections and is undoable atomically.
- Do not mutate project data while rendering, focusing, collapsing or animating.
- Preserve unknown metadata. Read/migration must not rewrite a disk file without Save.
- The source checkout contains examples, not user workflows. Preserve user data and
  `.research-flow` backups/tokens. Never commit secrets, font files, exports or logs.
- Runtime has one Python dependency, no Node build, no external asset fetches.
- CLI must stay loopback-only and token-authenticated. Keep tokens out of state,
  exported HTML/JSON/YAML, request logs and screenshots. Do not disable Host/Origin
  checks to make a tunnel work; use the explicit forwarded-port option.
- `make_handler(..., auth_token=None)` is solely for controlled in-process tests.
  Never use that setting in a user-facing entrypoint.
- Test Python and JS units plus browser interactions. Keep the snapshot builder pure.
  See `docs/testing.md` for commands; browser suites live in `tests/browser/`.
- Declare dependencies in `pyproject.toml`. Keep installed web assets explicitly
  listed there; maintain source-distribution contents in `MANIFEST.in`.
- The title divider is rectangular: 2px desktop, 1px <=700px, existing close spacing.
  The requested project-title font comes from the client's local installation.
- Do not select an open-source license without the owner's approval.
