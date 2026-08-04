# Architecture & stack

The three-layer decomposition (OCC STEP parsing · PySide6/pyvistaqt GUI · rigging+export) and the rules that keep the layers decoupled, plus the config-driven / GUI-optional principle, the Qt-free pure mesh/edge layer, and the dependency list. Read this to understand where a subsystem lives and why the layers don't leak into each other. Per-layer deep detail lives in the sibling reference files (`export.md`, `kinematic-joints.md`, the pipeline/viewport/geometry docs). Verify against `src/`; may lag.

---

### Architecture / stack
Three layers. Keep them decoupled: OCC, VTK/PyVista, and USD imports each stay
inside their layer so a broken optional dep can't take down the app.

1. **STEP parsing** — `pythonocc-core` (OpenCASCADE bindings), in `src/io_step/`
   - `STEPCAFControl_Reader` + `XCAFDoc` to read the **labeled assembly/product
     structure**, not just raw geometry.
   - Per component: `component_id` (stable), name, `TopoDS_Shape` (master-local),
     `source_label` (TDF_Label into the source doc), accumulated **world transform**,
     and color. `Assembly` also holds the live source `doc` (keeps labels valid).
   - **Accumulate assembly locations** down the tree for world placement —
     `GetShape(label)` only positions relative to the immediate parent.
   - Tessellation is **on demand**, not at load (see GUI). `tessellate_many` meshes
     ALL shapes in ONE `BRepMesh_IncrementalMesh(compound, isInParallel=True)` call —
     OCCT's TBB parallelizes across every face at once (~2× vs per-shape) — then
     extracts per-component triangles (keep per-component meshes; the *render* layer
     merges). Threads DON'T help (OCC holds the GIL); the per-shape Python extraction
     stays serial (true parallelism there would need multiprocessing — a follow-up).
   - Missing/useless names ("Solid1", "Body2") → synthesised fallback labels
     (bbox centroid) so grouping is still possible. Log them.

2. **GUI** — `PySide6` + `pyvistaqt`, in `src/gui/`
   - **Tree-first load**: opening a STEP parses structure + colors only and fills
     the `QTreeView` immediately (no meshing). On load (Main + every asset)
     `TreePanel.load` expands ONLY the root node(s) — `collapseAll()` then
     `expand()` each top-level row — so the top-level structure shows without
     revealing deeper levels.
   - **"Show 3D"** (toolbar) tessellates on demand at adjustable quality — two
     toolbar controls: "Allowable Linear Mesh Error [mm]" + "Allowable Angular Mesh
     Error [deg]" (coarse defaults for speed). Re-meshing calls `BRepTools.Clean`
     first so a new deflection actually takes effect (BRepMesh only *refines*).
   - **Rendering = ONE merged actor**, not one-actor-per-component (14k+ actors
     freezes VTK). All component meshes merge into a single `pv.PolyData` with
     per-cell RGBA and a **cell→component** map. This scales to 20k parts. Per-cell
     RGBA also carries **per-FACE colors** for multi-colored parts (each triangle
     painted by its source face via `Component.tri_faces` + `face_colors`).
     - **Highlight** (tree→3D): recolor that component's cells. Selecting a node
       highlights its whole **subtree**.
     - **Visibility** (right-click node → Hide/Show with children): set that
       subtree's cells' alpha to 0 / restore.
     - **Picking** (3D→tree): `find_closest_cell` on click → cell→component → select.
   - Keep selection state in one `SelectionController` (single source of truth).

3. **Rigging + export** — see `export.md` (STEP/USD/OBJ subtree exports) + `kinematic-joints.md` (joints).

### Config-driven, GUI-optional principle
The GUI produces config files (name→link map, joint definitions) + caches. The
export step must also run **headless from configs alone**, so a robot can be
re-exported after a STEP update without redoing GUI work. Configs are the durable
artifact; the GUI authors them.


## Pure mesh/edge layer
`src/gui/mesh_ops.py` is Qt-FREE (numpy + PyVista data only): `build_combined`
(merge → single PolyData + per-cell/-point component maps), `extract_edges`,
`save/load_edges_npz`. `viewport_panel.py` re-exports these and owns the Qt/render
widget. `src/gui/edges_build.py` is the headless subprocess CLI that reuses them.
`src/gui/fonts.py` and `src/gui/theme.py` are Qt-only leaf modules with no OCC/VTK/USD
dependency. `fonts.py` registers the **vendored** `src/resources/fonts/*.ttf` (IBM Plex
Sans for UI, JetBrains Mono for numeric fields, both SIL OFL 1.1) and is called from
`main.py` right after `QApplication`; it exists because Qt's `offscreen` platform ships
**zero font families on Windows**, so any headless capture renders text as tofu without it.
`theme.py` supplies an explicit dark palette + `VIEWPORT_BG` and is used ONLY by the test
harness and the docs screenshot generator - **the app itself follows the OS colour scheme**.
Together they pin the three variables a reproducible capture needs: style, palette, font.
`src/gui/num_field.py` is a third such leaf: `PreciseDoubleSpinBox`, a `QDoubleSpinBox`
that does not QUANTISE its value (12 internal decimals, shortest-exact display, `C`
locale). Use it for any field whose value is a **stored geometry parameter** rather than
a display knob — `setDecimals(n)` rounds on `setValue` too, so a field that round-trips
a saved value silently degrades it (see `geometry-edits.md`, the Component-Editor
Transform bullets).

**`src/gui/__init__.py` must stay EMPTY** (docstring only — no eager MainWindow
import): `edges_build` lives under `src.gui` and `assets_build`/`restructure_build`
import `..gui.mesh_ops`, so an eager package import would drag Qt/pyvistaqt into
every "headless" worker (it silently did, until packaging fixed it).


### Dependencies (all free / open source)
- `pythonocc-core` **novtk** build (STEP parse + XCAF + tessellation + STEP export)
- `PySide6` (Qt GUI)
- `pyvista`, `pyvistaqt` (embedded 3D viewport; bundles its own VTK via pip)
- `numpy`
- `pydantic` (scene-config schema — global + per-node models)
- `pyyaml` (reserved for future configs)
- `usd-core` (`pxr`) — USD export; INSTALLED (pip, in `packaging/environment.yml`; wheel
  `usd-core==26.5` for py3.12). Only `src/export/` imports it.
- `trimesh`/`pymeshlab`/`open3d` — optional decimation helpers only

