# Glossary — overloaded domain terms

One-line definitions for the terms that recur (and collide) across the docs, each pointing to where the concept is detailed. Verify against `src/`; may lag.

- **Model** — a top-level editable unit: the root scene (shown as **Main** in the UI), **Static**, or an **asset**. Each has its own two geometry stages + config section. → `asset-splitting-and-compose.md`.
- **Source / Main (stages)** — the two geometry STAGES every model keeps side-by-side: `geometry-source.xbf` (the input) and `geometry-main.xbf` (after that model's own edits/transform — always baked). The GUI displays and exports MAIN. → `pipeline-and-caching.md`.
- **Variant** — the cache DIRECTORY key for a model: `root` / `static` / `asset-{slug}`. Distinct from a STAGE (source/main). → `pipeline-and-caching.md`.
- **Model id** — the GUI/config key: `source` / `static` / `asset:{Name}` (maps to a variant). → `asset-splitting-and-compose.md`.
- **Prototype / occurrence** — a *prototype* is the shared product master; an *occurrence* is one placement of it. Asset marking groups all occurrences of a prototype; the **canonical occurrence** is the build root. → `asset-splitting-and-compose.md`.
- **Component / cid** — a node in the assembly tree; `component_id` (cid) is its stable internal id. → `scene-config-and-orientation.md`, `invariants.md`.
- **Link vs joint** — a **link** is a kinematic group of components (made via restructure link-folders); a **joint** is a defined motion (prismatic/revolute/fixed) between links. → `restructure-and-transform-source.md`, `kinematic-joints.md`.
- **Recipe** — a stored, replayable geometry edit (e.g. `SplitRecipe` = the op-sequence behind Edit Bodies). The config key `"splits"` keeps the historical name. → `geometry-edits.md`.
- **Frame / OriginFrame** — a local coordinate frame (origin + orientation); an `OriginFrame` is the stored form for Set-Origin and body/link joint frames. → `geometry-edits.md`.
- **Datum** — persistent user reference geometry (point/axis/plane/basis) drawn in the viewport and chainable into constructions; a per-model `datums` config map, excluded from bake inputs. → `selection-and-cgb.md`.
- **Point vs Vertex (SF/CGB)** — a **Point** is a bare 3D position (no topology); a **Vertex** is a B-Rep `TopoDS_Vertex` (STEP only). The SF/CGB deal in Points; "Vertex" is reserved for the End snap on a B-Rep edge. → `Specs/construction_geometry_builder_definitions.md`.
- **Collect vs Construct (CGB)** — **Collect** returns the SET of picked model entities (recolor/group/suppress); **Construct** turns picks into ONE reference entity. → `selection-and-cgb.md`.
- **Faithful vs rebuild path (STEP export)** — **faithful** = one `Transfer(root_label)` copy (preserves names/colors/instancing); **rebuild** = a filtered/flat doc when suppression/override/local-origin is present. → `export.md`, `occ-vtk-gotchas.md`.
- **B-rep vs tessellation / `has_brep`** — B-rep = analytic geometry (STEP); tessellation = triangle mesh. `has_brep` gates analytic-only features (edge/arc/Face-B-Rep snapping, STEP export, re-tessellation quality). → `mesh-import.md`, `selection-and-cgb.md`.
- **Implied root** — the top-level assembly root; config paths omit it so they survive a renamed root across STEP revisions. → `scene-config-and-orientation.md`.
- **Asset / Static** — Generate Assets splits the scene into one **asset** model per marked prototype group + one **Static** model (everything else). → `asset-splitting-and-compose.md`.
