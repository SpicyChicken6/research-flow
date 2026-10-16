# Research Flow design decisions

## Accepted direction

- A working research editor, with the connected workflow as the main surface.
- One canvas with individual rectangular nodes. Do not put entire layers inside
  large cards or panels, or turn the workspace into a dashboard.
- Three visible categories: Research overview, Operations, and Processing.
  Operations include literature research, downloads, analysis, code, and writing.
- Preserve the restrained blue, purple, and green accents for these categories.
  Keep category labels on cards and in the toolbar so color is not the only distinction.
- Clicking a node opens its details in the existing inspector. Exact methods,
  parameters, inputs, outputs, changes, and history belong there.
- Ideas & questions has its own toolbar button beside Details, available in all
  three workflow views. It opens a separate side panel with full-width rows and
  fine separators, replacing the old collapsed strip and card grid.
- Ideas start as compact rows showing a single-line title, status, and disclosure
  chevron. Clicking a row reveals its full title, type, linked step, notes, revisit
  condition, outcome, and Edit/Remove actions. Open only one row at a time; clicking
  it again collapses it. Expansion is view state and never changes project data.
  Keep Add item and the active/resolved/all filter at the top.
  Details and Ideas share the right side and never open together. Opening the list
  preserves the current view, selection, and canvas coordinates.
- On phones the ideas panel uses the full workspace width. Keep its close action
  visible, prevent focus on the covered canvas, and return focus to its button.
- Remove decorative row numbers and row count/context captions. The user explicitly
  rejected `01 / 02 / 03` and captions such as `Visible operations · 3 steps`.
- Avoid gradients, decorative sparkles, oversized introductions, and unnecessary
  labels. Preserve useful status and provenance information.

## Visual system

- White controls on a pale canvas (`#fafbfd`); primary text `#17202c`.
- Overview accent `#7193bc`, operation accent `#9a80b1`, processing accent `#719f8a`.
- Preserve the existing platform sans serif for interface text and the requested
  local condensed project-title face. No externally fetched fonts.
- Node titles are left aligned, 13px/18px at the natural canvas scale. Technical settings and file references use monospace for their content.
- Nodes have uniform 1px borders, small 3px corners, and no decorative shadows.
  Do not add colored side bars. Subtle fills and category text distinguish roles.
- Use spacing and connections for grouping. No imagery is needed on this editor.
- Give view controls distinct, consistently drawn icons: stacked planes for Layers,
  connected nodes for Graph, and rows with squares for Step list. Keep text labels.

## Arrangement and meaning

- Layer means role, not a fixed row. Cards can sit above, beside, or below any other
  card; their position never changes membership, dependency direction, or methods.
- Show all overview nodes and the operations/processing belonging to the selected
  overview. Category labels remain with the cards; there are no fixed row headings.
- The automatic arrangement uses 184×108px cards in compact groups around their
  parent. Overview steps form a readable spine; operation branches spread above
  and below it, with processing steps fanning diagonally beside their operation.
  Space branches to avoid overlapping cards. Placement is deterministic and
  remains freely editable; categories never return to fixed global rows.
- Drag cards freely in two dimensions, including negative coordinates. Keep other
  cards still during movement. New cards find space without displacing saved cards.
- Save Layers coordinates separately from Graph. Undo/redo restores movement;
  Escape cancels a drag. Arrow keys nudge a focused card, Shift moves farther, and
  the inspector's Canvas position fields provide a non-drag alternative.
- Arrange restores the automatic arrangement for visible cards and can be undone.
  Fit changes the camera only. Connections follow facing card edges in any direction.
- Use smooth curves for connections and rounded bends when routing around cards.
  Preserve clear arrow direction and keep curves outside card interiors.
- Only explicit dependency arrows establish execution order. Dashed lines mean
  “part of”; proximity and canvas direction do not create scientific relationships.
- Keep pan, zoom, Fit, keyboard navigation, and selection available. View changes
  must not change project data. Graph shows only high-level overview steps and their
  direct dependencies; its layout, focus, counts, and minimap use that same scope.
  Operations and processing remain in Layers and the full Step list.
- Graph connections change dependencies only; keep layer, membership, and hierarchy
  unchanged so connecting a legacy overview cannot make it disappear. Existing
  unambiguous branch adoption remains available when connecting in Layers or Step list.
- Entering Graph from detailed work selects its owning overview, when assigned.
  Opening detailed work from Graph switches to Layers. Graph creates overview
  steps; its Add operation control creates detailed work in Layers.
- Graph always follows the full project’s numbered overview-step order in fixed
  columns, including independent steps. Connections never reorder the columns.
  Remove the Freeform switch: dragging cards and arrow keys cannot reposition them
  in Graph. Arrow keys move focus; selection, renaming, ports, and panning remain.
- Graph Arrange only fits the organized view. Saved Graph coordinates stay as
  compatibility metadata, and Layers positions remain independent. Hidden work and
  cross-layer dependencies remain in saved data, without fabricated overview arrows.
- On mobile, open at a readable scale focused on the current operation in Layers
  or its overview in Graph (95%). Fit remains
  an explicit way to see the entire graph, even when that makes node text small.
- Run records are historical attempts or alternatives, not sequential processing
  nodes. Do not imply execution from a planned processing step.

## Review practice

- Preserve this direction during scoped refinements; the user's brief outranks
  generic skill recommendations.
- Inspect desktop and mobile screenshots for clipping, legibility, usable controls,
  and inspector behavior. Keep keyboard focus visible and text labels meaningful.
- Use Impeccable for the primary workflow, frontend-design for direction,
  ui-ux-pro-max for targeted references, and web-design-guidelines for final review.
