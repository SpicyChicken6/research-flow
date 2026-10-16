# Three layers of research work

The Layers view connects research direction, concrete operations and their detailed
methods. `examples/three-layers.yaml` is a fictional demonstration; its files,
completion states and run records do not describe work that actually occurred.

| Layer | Purpose | Examples |
| --- | --- | --- |
| Overview | Keep the project's goals and major decisions visible. | Define question, gather evidence, prepare data. |
| Operations | Describe the work that advances each overview step. | Review literature, download a dataset, develop code, normalize counts, write methods. |
| Processing steps | Show the individual implementation or transformation steps within an operation. | Apply a filtering rule, scale counts to CPM, apply a log transformation. |

Operations are not restricted to data processing. Use an `operation_type` that
describes the work, and record methods appropriate to it. A literature review can
record its query, source, screening rules and findings. A data transformation can
record its exact input, parameters, before/after changes and output version. Each
processing step is its own task and node. Clicking a node opens its method,
parameters, inputs, outputs and recorded history. An operation may also retain
records of work that was documented before its processing steps were separated.

## Membership and dependencies

Tasks use `layer: overview`, `layer: operation`, or `layer: processing`. An
operation's `overview_id` identifies its overview step; a processing step's
`operation_id` identifies its operation. Both associations reference existing
tasks of the appropriate layer. `depends_on` describes prerequisite work.
Membership does not itself imply execution order. The existing `parent_id`
hierarchy remains distinct from both membership and dependencies.

When an explicit association is absent, an operation can inherit membership from
its nearest overview ancestor, and an explicitly classified processing step can
inherit membership from its nearest operation ancestor. Opening an old workflow
does not classify any existing task as processing or write new membership fields.
Changing the layer of a referenced overview or operation is rejected until its
explicit links are reassigned or removed. Deleting a parent keeps remaining tasks
and their histories, clears references to the removed task, and preserves any
surviving hierarchy. Unlinked processing steps remain available for reassignment.

For example, two processing nodes can belong to normalization while an explicit
dependency describes their order:

```yaml
- id: scale-cpm
  title: Scale to CPM
  layer: processing
  operation_id: normalization
  depends_on: []
- id: log-transform
  title: Log-transform CPM
  layer: processing
  operation_id: normalization
  depends_on: [scale-cpm]
```

The example workflow adds a filtering-rule node and these two normalization nodes
as planned work. It does not turn previous alternative runs into sequential steps
or add execution claims. The settings and referenced files are fictional.

Set `project.presentation: layers` to open a project in the Layers view. The
existing workflow view remains available. The layers contain individually
selectable nodes, with connections for membership and prerequisite work. Node
details provide the planned method and recorded history separately from the
connections. The canvas shows every overview step. Selecting an overview shows
its operations and their processing steps. Drag any card above, beside, or below
another: its layer describes its role, not its position. Dashed lines mean “part of”; solid
arrows show dependencies. Pan the canvas or use the zoom and Fit controls.

Click **Layers** in any project to explore this view without changing the file.
Existing root steps appear as overview steps and child steps as operations until
an explicit layer is assigned. Click a node to inspect or edit its details; the
**Workflow layer** section controls its layer and overview or operation association.
**Graph** shows only high-level overview steps and their direct connections.
It keeps them in numbered step order; dependencies do not change that order.
Its layout, minimap, and Focus view use the same overview scope. Operations and
processing steps remain accessible in **Layers** and the full **Step list**; they
are preserved in saved files. Graph cards stay in fixed columns: arrow keys move
focus and **Arrange** fits the view. Free card positioning is available only in Layers.
Existing Graph coordinates remain in the file for compatibility and are not rewritten.
The plus control on an overview card adds an operation in Layers.

Graph connections leave layers, memberships, and parent branches unchanged.
In Layers or Step list, a new dependency can still assign an ungrouped step to an
unambiguous parent branch; existing branches are preserved.

## Free canvas arrangement

The automatic arrangement spreads operation branches above and below their
overview step, with processing steps fanning diagonally beside their operation.
Branches make room for their children while overview steps remain easy to follow.
Repeated arrangement produces the same positions. Drag a card to move it freely;
its connections follow without changing memberships, dependencies, or recorded
methods. Focus a card and use arrow keys to move it (Shift moves farther), or
expand **Canvas position** in its details and enter X/Y coordinates. Escape cancels
a drag. Undo and Redo restore card positions.

**Arrange** restores the automatic arrangement for the visible cards, and can be
undone. **Fit** adjusts the camera without changing positions. Saved coordinates
live in `layout.layer_positions`, independently of Graph's `layout.positions`, and
survive YAML saves, automatic HTML snapshots and editable Save copy exports. Cards outside the selected overview keep their
saved positions when arranging the current view.

## Ideas and questions to revisit

Use the **Ideas & questions** button beside Details from Layers, Graph, or Step
list. It opens a separate panel with one item per row without changing the current
workflow view. Rows initially show only the title and status. Click a row to reveal
its notes, linked step, revisit condition, and editing actions; opening another row
collapses the previous one. Closing the panel returns to the canvas.

Capture an idea, question or decision with context, an optional related step,
and a note about when to revisit it. Choose **Open**, **Later** or **Resolved**;
record the outcome when useful. The **To revisit**, **Resolved** and **All items**
filters keep prior decisions available. Opening, filtering or following a step
link does not change project data or create a dependency. Removing a linked step
keeps the idea as a project-wide item. Edits and removals support Undo/Redo.

Items are stored in the optional top-level `ideas` list and travel with YAML,
JSON, read-only HTML snapshots and editable HTML saves. Older files do not gain this field just by opening
the view. A revisit note is context, not an automatic reminder or scheduled job.

To build the standalone demonstration from a source checkout:

```bash
python scripts/build_preview.py --project examples/three-layers.yaml --output dist/three-layers.html
```

Open the generated demonstration in a browser. **Save copy** downloads an editable
HTML with the current document, including records. This is separate from the
automatic snapshot produced by the running app: **Save** writes the YAML and
refreshes a read-only HTML file beside it. That snapshot supports Graph, Layers,
Step list, method-history browsing and Ideas & questions, with its saved data and
assets available offline. Navigation never edits the snapshot or the YAML; run
Research Flow to change positions, plans, records or ideas. Reload an open snapshot
after saving again to see the newer version.

Use **More → Export SVG** in the running app for a static dependency-graph figure.
SVG export does not include the detailed method-history panel. Existing SVG files
are preserved and are no longer updated automatically on Save.

## Planned methods and recorded work

An operation or processing step's `method`, `parameters` and `rationale` describe
the current plan or choice. Its `records` list preserves individual accounts of work, including prior
attempts. Each record has an `id`, a required `recorded_at` time, an optional `performed_at` time,
a `status` (`recorded`, `completed`, `failed` or `partial`), and fields for `method`,
`parameters`, `rationale`, `inputs`, `outputs`, `changes`, `code`, `software` and `notes`.
Each record keeps its own rationale, so a later change to the plan cannot rewrite
the reason recorded for an earlier attempt.

Use `recorded` when an account has been added without a stronger completion claim.
Only label a real record `completed`, `failed` or `partial` when that outcome is
known. These are manually recorded states: Research Flow does not execute an
operation or independently verify that its outputs exist or checks passed.

`selected_record_id` identifies the record currently selected for an operation or processing step.
Selection does not establish scientific acceptance. An operation may remain
`in_progress` while a completed run awaits review. Preserve earlier records and
output versions when comparing methods; add a new record for a new attempt.

For bioinformatics processing, dimensions alone are insufficient. Record changes
to values, units, scale, excluded sample or feature identifiers, and annotations
when relevant. Preserve the original inputs and identify the exact outputs used
downstream. Record software and code versions when known; explicitly note missing
details rather than inventing them. The demo's numerical settings illustrate these
fields and are not recommended analysis parameters.
