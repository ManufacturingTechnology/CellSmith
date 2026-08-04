# Export — STEP / USD / OBJ (subtree)

The subtree export layer: the export-options popup (origin / scale / mesh quality), the STEP faithful-vs-rebuild paths, USD authoring (transform baked into points, meters + `metersPerUnit=1`, per-face `displayColor`, subprocess CLI), OBJ authoring, and the `--model` / main-stage CLI convention. Read when touching `src/export/` or `io_step/writer.py`. Whole-scene **composed** export lives in `asset-splitting-and-compose.md`; joint authoring in `kinematic-joints.md`. Verify against `src/`; may lag.

---

3. **Rigging + export** — `src/io_step/writer.py` (STEP) and `src/export/` (USD, later)
   - **STEP export of a subtree** (right-click → Export): FAITHFUL path transfers the
     node's `source_label` straight from the model's baked XCAF doc via
     `STEPCAFControl_Writer` (color/name modes on) — preserves colors + names +
     hierarchy + instancing exactly (verified in SolidWorks/Isaac), AP214. Used only
     when nothing is suppressed AND no color override AND no Local-origin shift
     (orientation/datum are already IN the geometry — the Source→Main bake).
     Otherwise the REBUILD path (`_transfer_filtered_doc`) is used: it applies a
     4x4 `pre_transform` (the local-origin shift) on top of each solid's world
     placement and writes `Component.color` (incl. baked overrides) as styles —
     at the cost of the authored names/instancing (the pending
     filtered-ASSEMBLY rebuild will fix that).
   - **Export options popup** (`_ExportOptionsDialog`): origin = Global vs Local (the
     selected component's frame origin → export origin); for USD/OBJ, an adjustable **scale**
     (source→USD units, persisted to config `export_scale`, default 0.001 = mm→m — bump
     to 0.01 if Isaac import is ~10× small) AND **mesh quality** — two tolerances:
     "Allowable Linear Mesh Error [mm]" (chordal deflection) + "Allowable Angular Mesh
     Error [deg]" (curve facet angle). Export quality is PERSISTED SEPARATELY from the
     display quality (`export_deflection`=5 mm / `export_angular_deg`=30° defaults vs
     display `deflection`=25 mm / `angular_deg`=45°). Both quality tolerances are whole
     numbers (mm / deg). Orientation + the global Z-datum are Source→Main BAKE
     inputs (Transform Source window) — exports never reapply them; the only
     export-time placement left is the per-export Local-origin choice.
     **STEP ignores scale + quality** — it exports EXACT B-rep, so a
     whole-model STEP is inherently huge and deflection can't shrink it.
   - **USD export of a subtree** (right-click → Export subtree as USD): DONE for
     geometry — `src/export/usd_writer.py` authors a prim hierarchy mirroring the
     assembly, one `UsdGeom.Mesh` per meshed leaf, suppressed excluded. **Colors are
     PER-FACE**: `displayColor` with `uniform` interpolation = one color per triangle
     (from `tri_faces` + `face_colors`), so multi-colored parts export correctly; a
     single-color part gets a `constant` displayColor. `usd_cli` bakes node overrides
     (→ constant) + global recolor (→ per-face remap) before authoring. The SELECTED component is the **default prim** (no `/Root`
     wrapper). The full export transform (orientation + unit scale + local-origin
     shift) is **baked into the mesh points**, NOT a root Xform — so the asset stays
     correctly sized/placed when *referenced* into another scene (a root transform was
     getting lost on reference → wrong size + offset). **Units = METERS,
     `metersPerUnit=1.0`** (Isaac Sim convention). Isaac's importer reads the raw unit
     MAGNITUDES as meters and IGNORES `metersPerUnit` (a cm+`metersPerUnit=0.01` build
     imported 100× too big), so geometry must be meter-scale; `scale` is exposed via
     config `export_scale` (default mm→m = 0.001) to tune other workflows. Runs in a
     subprocess (`usd_cli.py`) reloading the fast `.xbf` + color sidecar + mesh cache.
     NO physics/joints yet (next milestone).
   - **OBJ export of a subtree** (right-click → Export subtree as OBJ): DONE —
     `src/export/obj_writer.py` writes a Wavefront `.obj` (one `o <name>` group per
     meshed leaf, triangles) + sibling `.mtl` (per-part `Kd`, colors deduped). Same
     baked transform (orientation + `export_scale` + local-origin) as USD; OBJ has no
     unit/up-axis metadata so it's all in the coordinates. Vertices/faces written via
     `np.savetxt` (fast on big meshes). Subprocess `obj_cli.py`; pure numpy (no pxr).
   - **Joints** (prismatic/revolute/fixed → USD) — see `kinematic-joints.md`.
