# Node state & color

Per-node state (hidden / suppressed / color-override) and its asset-occurrence propagation, the unified color picker + screen eyedropper, the global Recolor registry, and the tree indicator glyphs. Read when working on node visibility/suppression, color overrides/recolor, or tree decoration. Verify against `src/`; may lag.

---

## Node state model (GUI)
- **Asset-occurrence propagation** (`MainWindow._expand_asset_occurrences`): a
  per-node edit — Hide/Show, Suppress, color override/clear — on a node that IS
  (or is UNDER) a marked-asset subtree is applied to the CORRESPONDING node in
  EVERY occurrence of that asset's prototype (nearest asset-root ancestor → its
  group_key → all sibling occurrences → same relative sub-path via
  `build_path_maps`). All occurrences bake into ONE generated asset, so this
  keeps them identical (otherwise it's ambiguous which instance's state bakes).
  Source model only (`_asset_nodes` empty elsewhere); wired into
  `_set_hidden_nodes`/`_set_suppressed_nodes`/`_override_color`/`_clear_color_override`
  (NOT the asset-mark toggle, which already fans out via `expand_marks`).
- **Hidden** (gray dot, right side): not shown in 3D; per-node, cascades to subtree.
- **Suppressed** (red dot, right side): excluded from export AND not shown in 3D.
- Effective 3D visibility = NOT under any hidden-or-suppressed node
  (`MainWindow._effective_hidden()` → `viewport.set_hidden(set)`; hidden solids are
  EXCLUDED from the shaded actor's display mesh so it stays OPAQUE + occludes the
  edge overlays — see the depth-peeling note in Viewport interaction; ~50 ms per
  hide-set change, not per frame).
- **Color override** (per-node; assembly cascades to descendant leaves; nearest
  ancestor-or-self wins) via `viewport.set_overrides({leaf: rgb})`. **Purple dot**
  marks a node whose OWN color is overridden (`tree.set_color_override`). The
  context-menu "Override Body Color…" opens the UNIFIED `ColorPickerDialog`
  (below) — so it too has the screen "Pick Color" eyedropper.
- **Unified color picker** (`src/gui/color_picker.py` `ColorPickerDialog`): the
  ONE color chooser used everywhere (main-window Override Body Color, Recolor
  Registry replacement color, Edit Bodies "Cut Surface Color" Set…). Embeds a
  non-native `QColorDialog` (NoButtons, DontUseNativeDialog) + a **"Pick Color"
  screen eyedropper** (`screen_eyedropper.ScreenColorPicker` — freezes ALL
  screens into one composite, shows an application-modal frameless overlay
  painting the frozen capture + a magnifier loupe, returns the clicked pixel's
  color; reads from the FROZEN composite so the overlay never occludes the
  sample; before the grab the CHOOSER DIALOGS are faded to `setWindowOpacity(0)`
  — NOT `hide()`, which QUITS `exec()` and drops the result — restored in the
  callback, and also on an exception so a dialog is never left invisible).
  ⭐ **`_windows_to_dim()` dims THIS dialog plus any ancestor `QDialog` ONLY —
  never an application window.** It used to dim `parentWidget()`
  unconditionally, and every caller's parent is a `QMainWindow` (MainWindow, the
  Component Editor, the Source Editor), so clicking "Pick Color" blanked the whole
  app: the live report was *"all CellSmith windows are being closed"*. It also
  defeated the eyedropper's most natural use — sampling a color from CellSmith's
  OWN viewport ("make this body match that one"), impossible if the viewport is
  invisible in the frozen capture. The Recolor flow still gets what it wanted:
  `RecolorDialog` is a `QDialog`, so it IS dimmed and stays out of the shot.
  Guarded by `scratchpad/color_picker_dim_test.py` (11). + OK/Cancel.
  `get_color(initial, parent,
  title, show_alpha=True)` is the drop-in replacement for
  `QColorDialog.getColor` (returns a `QColor` or None). The old
  `recolor_dialog._ReplacementColorDialog` + duplicated Edit-Bodies "Pick"
  button are GONE (folded into this). **ALPHA CHANNEL is shown by default**
  (`ShowAlphaChannel`) as GROUNDWORK — `selected_color()`/`selected_rgba()`
  return the alpha, but every caller currently reads RGB only
  (`redF/greenF/blueF`) and DROPS alpha until alpha is wired through the color
  model / sidecar / exports (the "ALPHA / TRANSPARENCY EVERYWHERE" NEXT BIG
  TODO). The screen eyedropper PRESERVES the current alpha (screen pixels are
  opaque). Pure Qt.
- **Global recolor** (**"Recolor Registry…"** toolbar button → `RecolorDialog`, or the
  **eyedropper** — labeled "Recolor"): per-color rules
  in `model_settings.recolor` (per-MODEL since v3) recolor EVERY matching face at
  once (viewport per-cell).
  Affected leaves get a distinct **purple SQUARE** marker (`tree.set_global_recolored`)
  — a different shape+stroke from the round purple per-node dot. Component-level
  overrides win, so an overridden leaf shows the purple dot, not the square.
  `_open_recolor(focus_rgb)` opens the dialog optionally scrolled to + selecting a
  color's row: the context item focuses the node's base color; the eyedropper focuses
  the captured face color. Picking a REPLACEMENT color (clicking a row's Override cell)
  opens the unified **`color_picker.ColorPickerDialog`** (see "Unified color picker"
  above — the embedded non-native picker + "Pick Color" screen eyedropper + alpha
  channel). Recolor rules stay RGB (alpha dropped for now).
- **Eyedropper** (toolbar, checkable, drawn icon): `_on_eyedropper` →
  `viewport.set_pick_color_mode(True)`; the next viewport left-click captures the
  nearest visible face's BASE color (`_color_at`, the recolor SOURCE) and fires
  `on_pick_color` → `_on_pick_color` exits the mode and opens Global Recolor focused
  on that color.
- **Simplify Bodies** (cyan stacked bars ≡): this node's whole subtree exports as
  ONE merged mesh. **GENERATED models only** (assets + Static) — the exact mirror
  of the `is_asset` gate, which is Source-only. `NodeConfig.simplify_bodies`,
  `MainWindow._simplify_nodes` / `_set_simplify_nodes`, `tree.set_simplify`.
  Export-only: the bake, the viewport and the STEP path are untouched, so it
  needs no `_confirm_edit_clears_assets`. Two explicit menu entries ("Mark
  Simplify Bodies" / "Clear Mark Simplify Bodies") rather than one toggling
  label, so a mixed multi-selection is unambiguous. It can be REFUSED — full
  semantics + the strict-validation rule in `export.md` § *Simplify Bodies*.
- Indicator glyphs are painted at the RIGHT of the row by `tree_panel._IndicatorDelegate`,
  from the right edge inward: red dot = suppressed, gray dot = hidden, purple dot =
  own color override, purple square = affected by a global recolor rule, blue dot =
  asset, orange diamond = split recipe, teal triangle = custom origin, gold hexagon =
  joint, green move-cross = component transform, **cyan stacked bars = Simplify
  Bodies**, then a blue
  **caret (^)** on any node with a modified DESCENDANT (hidden/suppressed/color) so a
  collapsed parent signals edits below. Roles are `UserRole + 1..12`
  (`SIMPLIFY_ROLE` = 12, next free is 13); **a new role must be added to the
  early-out at the top of `paint()` or nothing draws**. The bars are spaced
  `d // 2 - 1` apart, NOT `d // 3` — at 2 px a 1.4 px pen merges them into a blob
  (probe-verified, `scratchpad/simplify_obj_gui_probe.py`). Caret set =
  strict ancestors of every non-default `NodeConfig`, via
  `MainWindow._modified_descendant_ancestors()` → `tree.set_modified_descendants(set)`
  on load + after each edit.

