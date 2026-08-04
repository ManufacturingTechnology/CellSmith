"""Durable per-scene configuration saved beside the STEP/.xbf file.

Split into GLOBAL (per-file) settings and PER-NODE settings so the schema can
grow cleanly. Serialized as ``<base>.cellsmith.json`` next to the source file,
written whenever a setting changes and loaded/applied when the file is opened.

Pure model layer — no OCC/Qt. Uses pydantic for a clear, validated schema.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

log = logging.getLogger(__name__)

CONFIG_SUFFIX = ".cellsmith.json"
#: Bump if the schema changes incompatibly. v2 added NodeConfig.is_asset and the
#: per-model ``static`` / ``assets`` sections. v3 split the old ``global_settings``
#: into GLOBAL (file-wide, stored once: quality/scale/view toggles) and per-model
#: ``model_settings`` (orientation, origin offsets, recolor) — v1/v2 files are
#: migrated on load (``ModelConfigStore._migrate_raw``).
SCHEMA_VERSION = 3

# --- model ids -----------------------------------------------------------------
# The GUI/config layer identifies which model is being edited by a MODEL ID:
# "source" (the parsed STEP), "static" (scene minus assets) or "asset:{Name}"
# (Name = the asset's config key / display name). The CACHE layer uses a parallel
# filename VARIANT ("source" | "static" | "asset-{slug}"); the slug is derived
# from the name here so the pure model layer owns the mapping.
MODEL_SOURCE = "source"
MODEL_STATIC = "static"
ASSET_MODEL_PREFIX = "asset:"

#: Static is stored as a reserved entry in the ``assets`` config dict (so it uses
#: the exact same section/seed code path as any asset — it is NOT a unique
#: top-level section). Its model id stays ``MODEL_STATIC`` and its cache variant
#: stays ``"static"``; only its config LOCATION is unified. This key is excluded
#: from :meth:`ModelConfigStore.asset_entries` so it never lists as a real asset.
STATIC_MODEL_NAME = "Static"
STATIC_VARIANT = "static"

#: Feature A (Restructure): the BASE model keeps the internal id ``MODEL_SOURCE``
#: (zero churn/migration) but is DISPLAYED as "Main".
MAIN_DISPLAY_NAME = "Main"

#: Source→Main pipeline: every model's cache directory holds TWO geometry
#: STAGES side by side — ``geometry-source.xbf`` (that model's input: the STEP
#: parse for the root model, the pruned base for assets/Static) and
#: ``geometry-main.xbf`` (after that model's own edits/transform, ALWAYS baked).
#: The GUI always displays a model's MAIN stage. The root model's cache
#: directory is the cache dir itself; its variant key is ``ROOT_VARIANT``
#: (``"source"``/``"main"`` are STAGES, no longer variant keys — the cache
#: layer rejects them as variants to fail loud on stale call sites).
ROOT_VARIANT = "root"
STAGE_SOURCE = "source"
STAGE_MAIN = "main"

#: Reserved model display names — Generate's asset-name dedup seeds with these so
#: a part literally named "Static"/"Main" can't collide with the reserved config
#: key / the base-model row.
RESERVED_MODEL_NAMES = {STATIC_MODEL_NAME, MAIN_DISPLAY_NAME}


def asset_model(name: str) -> str:
    """Model id for an asset display name."""
    return ASSET_MODEL_PREFIX + name


def is_asset_model(model: str) -> bool:
    return model.startswith(ASSET_MODEL_PREFIX)


def asset_name_of(model: str) -> str:
    """The asset display name embedded in an ``asset:{Name}`` model id."""
    return model[len(ASSET_MODEL_PREFIX):]


def asset_slug(name: str) -> str:
    """Filesystem-safe slug for an asset display name (cache filename infix)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    s = re.sub(r"_+", "_", s).strip("._-")
    return s[:60] or "asset"


def path_under_any(path: str, roots) -> bool:
    """True when ``path`` equals or is nested under any ``/``-rooted root path."""
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def asset_root_declares_origin(origin_map_raw: Optional[dict],
                               occurrence_paths,
                               folder_origin_paths=None) -> bool:
    """True when the asset's ROOT (any of its occurrences) carries a custom origin.

    Such an origin re-frames the asset root's geometry into that frame at the Main
    bake (assembly child-location surgery). Asset generation must then NOT re-bake
    the canonical occurrence's Main ORIENTATION on top (``R_root = identity``) —
    otherwise it cancels the origin and the asset keeps its arbitrary Main
    orientation instead of the user's chosen local frame; the composed export
    likewise places the occurrence at ``W_occ`` (no ``R_root`` compensation), still
    reproducing Main. Generation AND compose both call this over the SAME inputs so
    their ``R_root`` can never disagree. A child origin (a path UNDER the root, not
    a root occurrence) doesn't affect ``R_root`` — it stays a live Xform inside.

    A declared origin lives in EITHER the ROOT model's origin map (a base-tree
    component) OR — when the asset root is a RESTRUCTURE FOLDER (a node created in
    Transform Source, with no base-tree identity) — the STRUCTURE map's
    ``NewAssembly.origin``, whose CUSTOM-origin final paths are recorded in the root
    bake stamp's ``folder_origin_frame_paths``. Pass those via
    ``folder_origin_paths`` so a folder-rooted asset is recognized too (else its
    custom origin is silently ignored and the asset never de-rotates)."""
    declared = set(origin_map_raw or {}) | set(folder_origin_paths or ())
    return any(p in declared for p in (occurrence_paths or ()))


def drop_asset_covered_keys(raw_map: Optional[dict], asset_paths) -> dict:
    """Return ``raw_map`` minus every key that lands on/under a marked-asset
    subtree path. Used to keep marked-asset geometry edits OUT of the root Main
    bake (they belong to the asset model). Empty/absent map or no asset paths
    → the map unchanged (possibly ``{}``)."""
    if not raw_map:
        return raw_map or {}
    if not asset_paths:
        return dict(raw_map)
    return {p: v for p, v in raw_map.items()
            if not path_under_any(p, asset_paths)}


def parse_model_arg(argv: List[str]) -> Tuple[str, List[str]]:
    """Strip an optional leading ``--model=<id>`` from CLI argv.

    Returns ``(model_id, remaining_argv)``; absent flag → the source model, so
    existing invocations keep working unchanged.
    """
    if argv and argv[0].startswith("--model="):
        return argv[0][len("--model="):], argv[1:]
    return MODEL_SOURCE, list(argv)


class NodeConfig(BaseModel):
    """Per-component settings, keyed by ``component_id``. Add fields over time."""

    hidden: bool = False       # hidden in the 3D view (gray marker)
    suppressed: bool = False   # excluded from export + not shown (red marker)
    color_override: Optional[List[float]] = None  # RGB 0..1; overrides display color
    is_asset: bool = False     # marked as an Asset (blue marker; source model only)

    def is_default(self) -> bool:
        return self == NodeConfig()


class ColorRemap(BaseModel):
    """A global per-color recolor rule: every part whose display color is ``from_rgb``
    is shown/exported as ``to_rgb`` (unless a component-level override wins). Colors
    are RGB 0..1; matching is by 8-bit quantized value (see ``_quantize``)."""

    from_rgb: List[float]  # source color (RGB 0..1)
    to_rgb: List[float]    # replacement color (RGB 0..1)


#: The old ``global_settings`` keys that are PER-MODEL since schema v3 (migrated
#: into ``model_settings`` on load).
_MODEL_SETTING_KEYS = ("up_direction", "z_rotation_deg",
                       "origin_offset_x", "origin_offset_y", "origin_offset_z",
                       "recolor")


class ModelSettings(BaseModel):
    """PER-MODEL settings (each of Source / Static / an Asset owns its own).

    These describe the model's data — its export frame, its export origin, its
    appearance rules — as opposed to :class:`GlobalConfig`'s file-wide workflow
    preferences. Generation SNAPSHOTS orientation from the source into a newly
    created section (origin offsets start at 0 for assets — they live in their
    own local frame — and copy from the source for Static, which shares the
    scene frame); colors are BAKED into the variant's sidecar instead of carried
    as rules, so ``recolor`` starts empty on generated models.
    """

    # Export orientation (config-driven, not hardcoded). The exported asset is
    # Z-up (Isaac); ``up_direction`` picks which SOURCE axis becomes world +Z, and
    # ``z_rotation_deg`` spins the other two axes about it.
    up_direction: str = "+Z"   # one of +X,-X,+Y,-Y,+Z,-Z (source axis → world up)
    z_rotation_deg: int = 0    # 0, 90, 180, 270 about the up axis
    # Export ORIGIN offset (this model's source units, mm) — export geometry is
    # shifted so this point is the origin. Only the up-axis component is
    # user-settable now ("Set Z-Origin"); the others are in the schema for later.
    origin_offset_x: float = 0.0
    origin_offset_y: float = 0.0
    origin_offset_z: float = 0.0
    # Per-color recolor rules (the "Recolor" dialog). Applied to any part whose
    # base color matches, EXCEPT where a component-level override takes over.
    recolor: List[ColorRemap] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    """FILE-WIDE settings shared by every model (workflow/view preferences)."""

    # Mesh-quality fields keep short Python attr names (used all over the code) but
    # SERIALIZE with the GUI terminology, and still LOAD the legacy short keys.
    model_config = ConfigDict(populate_by_name=True)

    deflection: float = Field(  # DISPLAY allowable LINEAR mesh error (mm) — chordal deflection
        25.0, serialization_alias="allowable_linear_mesh_error",
        validation_alias=AliasChoices("allowable_linear_mesh_error", "deflection"))
    angular_deg: float = Field(  # DISPLAY allowable ANGULAR mesh error (degrees)
        45.0, serialization_alias="allowable_angular_mesh_error",
        validation_alias=AliasChoices("allowable_angular_mesh_error", "angular_deg"))
    export_deflection: float = Field(  # EXPORT allowable LINEAR mesh error (mm)
        5.0, serialization_alias="export_allowable_linear_mesh_error",
        validation_alias=AliasChoices("export_allowable_linear_mesh_error", "export_deflection"))
    export_angular_deg: float = Field(  # EXPORT allowable ANGULAR mesh error (degrees)
        30.0, serialization_alias="export_allowable_angular_mesh_error",
        validation_alias=AliasChoices("export_allowable_angular_mesh_error", "export_angular_deg"))
    show_edges: bool = True    # B-Rep feature-edge overlay (auto-built on first load)
    show_tess_edges: bool = False  # all-triangle (tessellation) wireframe overlay
    show_bodies: bool = True   # shaded-surface (tessellation) actor visibility
    origin_indicator: bool = True  # show a triad at the selected node's origin
    perspective: bool = False  # viewport projection: False = orthographic (default)
    # USD export unit scale: source (mm) → USD units. Isaac reads magnitudes as
    # meters, so default mm→m = 0.001; tweak here if a workflow needs another unit.
    export_scale: float = 0.001


class SceneConfig(BaseModel):
    """The ACTIVE model's materialized config: shared globals + its own settings."""

    # pydantic v2 reserves the "model_" prefix; clear it so model_settings is legal.
    model_config = ConfigDict(protected_namespaces=())

    version: int = SCHEMA_VERSION
    global_settings: GlobalConfig = Field(default_factory=GlobalConfig)
    model_settings: ModelSettings = Field(default_factory=ModelSettings)
    nodes: Dict[str, NodeConfig] = Field(default_factory=dict)

    # --- per-node helpers (create-on-demand, prune defaults) ---

    def node(self, component_id: str) -> NodeConfig:
        """Return the node's config (a default if unset; not stored)."""
        return self.nodes.get(component_id) or NodeConfig()

    def update_node(self, component_id: str, **changes) -> None:
        """Apply field changes to a node, pruning it if it returns to defaults."""
        current = self.nodes.get(component_id) or NodeConfig()
        updated = current.model_copy(update=changes)
        if updated.is_default():
            self.nodes.pop(component_id, None)
        else:
            self.nodes[component_id] = updated

    def hidden_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.hidden}

    def suppressed_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.suppressed}

    def asset_ids(self) -> set[str]:
        return {cid for cid, n in self.nodes.items() if n.is_asset}


def resolve_color_overrides(config: "SceneConfig", assembly) -> Dict[str, tuple]:
    """Per shape-bearing leaf, the effective override RGB (nearest ancestor-or-self
    with ``color_override`` wins), or omitted. Shared by the GUI viewport and the
    export CLIs so exports match what's shown. Returns ``{component_id: (r,g,b)}``.
    """
    overrides = {cid: n.color_override for cid, n in config.nodes.items() if n.color_override}
    if not overrides:
        return {}
    result: Dict[str, tuple] = {}
    for c in assembly.components:
        if getattr(c, "shape", None) is None:
            continue
        cur = c.component_id
        while cur:
            if cur in overrides:
                ov = overrides[cur]
                result[c.component_id] = (float(ov[0]), float(ov[1]), float(ov[2]))
                break
            parent = assembly.get(cur)
            cur = parent.parent_id if parent else None
    return result


def _quantize(rgb) -> Tuple[int, int, int]:
    """Canonical 8-bit key for a 0..1 RGB triple (matching tolerant of float noise)."""
    return tuple(int(round(max(0.0, min(1.0, float(c))) * 255)) for c in rgb[:3])


def recolor_lookup(config: "SceneConfig") -> Dict[Tuple[int, int, int], tuple]:
    """The model's recolor rules as ``{quantized_from_rgb: to_rgb}`` — the form the
    Recolor dialog wants for preloading existing overrides."""
    return {_quantize(r.from_rgb): (float(r.to_rgb[0]), float(r.to_rgb[1]), float(r.to_rgb[2]))
            for r in config.model_settings.recolor}


def recolor_rules_8bit(config: "SceneConfig") -> List[Tuple[tuple, tuple]]:
    """Recolor rules as ``[(from_8bit, to_8bit)]`` for the viewport's per-cell remap."""
    return [(_quantize(r.from_rgb), _quantize(r.to_rgb)) for r in config.model_settings.recolor]


def resolve_global_recolor(config: "SceneConfig", assembly) -> Dict[str, tuple]:
    """Per shape-bearing leaf, the GLOBAL recolor replacement of its BASE color,
    keyed by ``component_id`` (base match only; no component-level override). Used by
    EXPORTS, which are one-color-per-component. The viewport applies recolor per-cell
    (see :func:`recolor_rules_8bit`) so per-face detail is preserved there.
    """
    table = recolor_lookup(config)
    if not table:
        return {}
    comp_overrides = resolve_color_overrides(config, assembly)
    result: Dict[str, tuple] = {}
    for c in assembly.components:
        if getattr(c, "shape", None) is None or c.color is None:
            continue
        if c.component_id in comp_overrides:
            continue  # component-level override wins over the global recolor
        to = table.get(_quantize(c.color))
        if to is not None:
            result[c.component_id] = to
    return result


def recolored_component_ids(config: "SceneConfig", assembly) -> set:
    """Components affected by the global recolor (for the tree indicator).

    Per-face aware: a component qualifies when its base color OR any of its per-face
    colors matches a rule, and it has no component-level override (which wins).
    """
    table = recolor_lookup(config)
    if not table:
        return set()
    comp_overrides = resolve_color_overrides(config, assembly)
    out: set = set()
    for c in assembly.components:
        if getattr(c, "shape", None) is None or c.component_id in comp_overrides:
            continue
        if c.color is not None and _quantize(c.color) in table:
            out.add(c.component_id)
            continue
        fc = getattr(c, "face_colors", None)
        if fc and any(_quantize(rgb) in table for rgb in fc.values()):
            out.add(c.component_id)
    return out


def resolve_effective_colors(config: "SceneConfig", assembly) -> Dict[str, tuple]:
    """Combined per-leaf color overrides for EXPORTS (one color per component): the
    global per-color recolor of the base color, with component-level overrides layered
    on top (they win). The viewport does NOT use this — it renders per-cell base colors
    plus a per-cell recolor — so exports remain single-color-per-part (see OPEN TODO).
    Returns ``{component_id: (r,g,b)}`` for every leaf whose color differs from base.
    """
    effective = dict(resolve_global_recolor(config, assembly))
    effective.update(resolve_color_overrides(config, assembly))
    return effective


def bake_effective_appearance(config: "SceneConfig", assembly) -> int:
    """Bake node color overrides + the global recolor INTO the in-memory
    assembly, per-face aware: an override wins (collapses the part to one
    constant color); otherwise base AND per-face colors get the recolor remap.
    Shared by the USD/STEP export CLIs, asset generation, and the composed
    exporter (the copies used to be inlined identically in each). Returns the
    number of parts whose base color changed.
    """
    node_over = resolve_color_overrides(config, assembly)
    recolor = recolor_lookup(config)
    if not node_over and not recolor:
        return 0
    baked = 0
    for comp in assembly.components:
        if getattr(comp, "shape", None) is None:
            continue
        if comp.component_id in node_over:
            comp.color = node_over[comp.component_id]
            comp.face_colors = None
            baked += 1
            continue
        if recolor:
            if comp.color is not None:
                to = recolor.get(_quantize(comp.color))
                if to is not None:
                    comp.color = to
                    baked += 1
            if comp.face_colors:
                comp.face_colors = {fi: recolor.get(_quantize(rgb), rgb)
                                    for fi, rgb in comp.face_colors.items()}
    return baked


def unique_colors(assembly) -> List[Tuple[float, float, float]]:
    """Distinct colors (RGB 0..1) across all shape-bearing leaves — base AND per-face
    — deduped by 8-bit value and sorted. The full palette for the Recolor dialog.
    """
    by_key: Dict[Tuple[int, int, int], Tuple[float, float, float]] = {}
    for c in assembly.components:
        if getattr(c, "shape", None) is None:
            continue
        if c.color is not None:
            by_key.setdefault(_quantize(c.color), (float(c.color[0]), float(c.color[1]), float(c.color[2])))
        fc = getattr(c, "face_colors", None)
        if fc:
            for rgb in fc.values():
                by_key.setdefault(_quantize(rgb), (float(rgb[0]), float(rgb[1]), float(rgb[2])))
    return [by_key[k] for k in sorted(by_key)]


def build_path_maps(assembly) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Bidirectional maps between ``component_id`` and a readable tree path.

    Paths are absolute from an IMPLIED root: they always start with ``/`` and omit
    the (version-specific) top-level assembly name, e.g. ``/Arm/Link1``. Duplicate
    siblings get a ``#n`` suffix so paths are unique and reversible. Component IDs
    remain the internal identity everywhere; paths are only the human-readable key
    used in the saved config file — and the stable matching key across STEP revisions.

    The implied root(s) map to ``/`` (never configured directly). Their children —
    and any childless top-level component — share the top-level ("") namespace so
    their segments dedupe against each other.
    """
    implied = assembly.implied_root_ids()
    cid_to_path: Dict[str, str] = {}
    used: Dict[str, Dict[str, int]] = {}  # prefix -> {segment_base: count}
    for c in assembly.components:  # walk order → parents precede children
        if c.component_id in implied:
            cid_to_path[c.component_id] = "/"
            continue
        pid = c.parent_id
        parent_path = cid_to_path.get(pid) if pid else None
        # Top-level when there is no in-assembly parent, or the parent is implied.
        prefix = "" if parent_path in (None, "/") else parent_path
        base = str(c.name or c.component_id).replace("/", "_").strip() or c.component_id
        counts = used.setdefault(prefix, {})
        counts[base] = counts.get(base, 0) + 1
        seg = base if counts[base] == 1 else f"{base}#{counts[base]}"
        cid_to_path[c.component_id] = f"{prefix}/{seg}"
    return cid_to_path, {p: cid for cid, p in cid_to_path.items()}


def config_path_for(source_path: str) -> str:
    """``foo.step`` / ``foo.xbf`` -> ``foo.cellsmith.json`` (strips known extensions)."""
    base = source_path
    for ext in (".xbf", ".step", ".stp", ".STEP", ".STP"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    else:
        base = os.path.splitext(source_path)[0]
    return base + CONFIG_SUFFIX


def _resolve_node_key(key: str, path_to_cid: Dict[str, str], assembly) -> Optional[str]:
    """Map a saved node key to a component_id in ``assembly``, or None if it can't.

    Handles the current ``/…`` path form, migrates the legacy ``Root/…`` form from
    the previous format, and still accepts a raw ``component_id`` (oldest configs).
    Returning None means the key has no counterpart in this file — a real difference
    from the STEP revision the config was authored against.
    """
    if key in path_to_cid:
        return path_to_cid[key]
    # Legacy format: paths used to be rooted at "Root" ("Root/Arm" -> "/Arm").
    if key.startswith("Root/"):
        alt = "/" + key[len("Root/"):]
        if alt in path_to_cid:
            return path_to_cid[alt]
    # Oldest format: keyed directly by component_id.
    if assembly.get(key) is not None:
        return key
    return None


def _describe_unmatched(key: str, node) -> str:
    """One-line description of an unmatched saved node (path + which settings)."""
    flags: List[str] = []
    if isinstance(node, dict):
        if node.get("hidden"):
            flags.append("hidden")
        if node.get("suppressed"):
            flags.append("suppressed")
        if node.get("color_override"):
            flags.append("color override")
        if node.get("is_asset"):
            flags.append("asset")
    return f"{key}  →  {', '.join(flags) if flags else 'custom settings'}"


def _translate_nodes_in(raw_nodes: dict, assembly) -> Tuple[Dict[str, dict], List[str]]:
    """Path-keyed raw ``nodes`` -> cid-keyed, plus descriptions of unmatched keys."""
    _, path_to_cid = build_path_maps(assembly)
    translated: Dict[str, dict] = {}
    unmatched: List[str] = []
    for key, node in raw_nodes.items():
        cid = _resolve_node_key(key, path_to_cid, assembly)
        if cid is not None:
            translated[cid] = node
        else:
            unmatched.append(_describe_unmatched(key, node))
    return translated, unmatched


def _translate_nodes_out(nodes: dict, assembly) -> Dict[str, dict]:
    """cid-keyed dumped ``nodes`` -> path-keyed (for the file)."""
    cid_to_path, _ = build_path_maps(assembly)
    return {cid_to_path.get(cid, cid): node for cid, node in nodes.items()}


def _coerce_model(model_cls, data):
    """Validate ``data`` into ``model_cls``, defaulting missing/invalid fields.

    Tolerant loading: a missing field falls back to its default (pydantic already
    does this), and a field with an INVALID value is dropped so the rest of the
    section survives instead of the whole model resetting to defaults. Offending
    top-level keys reported by pydantic are removed iteratively and validation is
    retried, so every field that IS valid is kept. Hand-edited configs (e.g. a
    section with ``model_settings`` deleted, or a stray bad value) load cleanly.
    """
    if not isinstance(data, dict):
        return model_cls()
    work = dict(data)
    for _ in range(len(work) + 1):
        try:
            return model_cls.model_validate(work)
        except ValidationError as exc:
            removed = False
            for err in exc.errors():
                loc = err.get("loc") or ()
                if loc and loc[0] in work:
                    work.pop(loc[0], None)
                    removed = True
            if not removed:
                break
        except Exception:  # noqa: BLE001 - unexpected shape → default
            break
    return model_cls()


class ModelConfigStore:
    """The ONE ``<base>.cellsmith.json`` holding every model's config.

    File shape: the top-level ``version``/``global_settings``/``model_settings``/
    ``nodes`` group is the SOURCE model (``global_settings`` is file-wide, stored
    ONCE at the top). Every OTHER model — Static and each asset — is an entry in
    ``assets["{Name}"]`` holding ``model_settings`` + ``nodes`` (+ ``slug`` and
    ``source_node``). Static uses the reserved key ``"Static"`` so it shares the
    exact same code path as any asset (it is NOT a unique top-level section).
    Every section's ``nodes`` are keyed by tree paths WITHIN that model's own tree.

    Exactly ONE section is materialized (path keys -> component_ids) at a time via
    :meth:`activate`; :meth:`save_active` splices it back, leaving every inactive
    section byte-untouched. cid-keyed data exists only inside the active
    ``SceneConfig``; everything at rest is path-keyed raw dicts — so no assembly is
    ever needed for a model that isn't loaded.
    """

    def __init__(self, source_path: str) -> None:
        self._source_path = source_path
        self._config_path = config_path_for(source_path)
        self._raw: dict = {}
        self.active_model: str = MODEL_SOURCE
        #: Set by :meth:`load` when the config file exists but couldn't be parsed
        #: (e.g. malformed JSON) — the GUI surfaces this so the user knows their
        #: settings were ignored rather than silently starting from defaults.
        self.load_error: Optional[str] = None

    # --- file IO ---

    def load(self) -> None:
        """Read the file into the raw dict ({} if missing/corrupt); migrate to v3.

        On a parse failure the error is recorded in :attr:`load_error` (and logged)
        so the caller can warn the user their existing settings were ignored,
        instead of silently proceeding from defaults and later overwriting the file.
        """
        self._raw = {}
        self.load_error = None
        if not os.path.isfile(self._config_path):
            return
        try:
            with open(self._config_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                self._raw = raw
            else:
                self.load_error = "Config file is not a JSON object."
        except Exception as exc:  # noqa: BLE001 - corrupt config shouldn't block load
            self.load_error = str(exc)
            log.warning("Ignoring unreadable scene config %s: %s", self._config_path, exc)
        self._migrate_raw()

    def _migrate_raw(self) -> None:
        """v1/v2 → v3: split the old all-in-one ``global_settings``.

        Per-model keys (orientation, origin offsets, recolor) move into a
        ``model_settings`` dict — at the top level for Source and inside each
        static/asset section. Sections' old ``global_settings`` copies are then
        DROPPED (globals are file-wide in v3; the top level wins). Idempotent.
        """
        if not self._raw:
            return

        def split(container: dict) -> None:
            gs = container.get("global_settings")
            if not isinstance(gs, dict):
                return
            ms = container.setdefault("model_settings", {})
            for k in _MODEL_SETTING_KEYS:
                if k in gs and k not in ms:
                    ms[k] = gs.pop(k)

        split(self._raw)  # source (top level keeps the slimmed global_settings)
        static = self._raw.get("static")
        if isinstance(static, dict):
            split(static)
            static.pop("global_settings", None)
        assets = self._raw.get("assets")
        if isinstance(assets, dict):
            for sect in assets.values():
                if isinstance(sect, dict):
                    split(sect)
                    sect.pop("global_settings", None)
        # Static moved from a top-level ``static`` section into ``assets`` under the
        # reserved key so it stops being a unique special case. Idempotent: after
        # the move there is no top-level ``static`` to migrate. An existing
        # ``assets["Static"]`` (already migrated) wins; the legacy copy is dropped.
        legacy_static = self._raw.pop("static", None)
        if isinstance(legacy_static, dict):
            assets = self._raw.setdefault("assets", {})
            if not isinstance(assets.get(STATIC_MODEL_NAME), dict):
                legacy_static.setdefault("slug", STATIC_VARIANT)
                legacy_static.setdefault("source_node", "")
                legacy_static.setdefault("model_settings", {})
                legacy_static.setdefault("nodes", {})
                assets[STATIC_MODEL_NAME] = legacy_static
        self._raw["version"] = SCHEMA_VERSION

    def _write(self) -> str:
        self._minimize_raw()
        with open(self._config_path, "w", encoding="utf-8") as fh:
            json.dump(self._raw, fh, indent=2)
        return self._config_path

    @staticmethod
    def _minimize_section(container: dict) -> None:
        """Trim one section dict IN PLACE: drop settings fields equal to their model
        default, and drop the whole ``global_settings``/``model_settings``/``nodes``
        sub-key when nothing non-default remains. So the file only ever carries
        MODIFIED values (defaults are re-supplied on load). Identity/bookkeeping keys
        (``slug``/``source_node``/``prototype``/``version``/``assets``) are untouched.
        """
        if "global_settings" in container:
            gs = _coerce_model(GlobalConfig, container["global_settings"]).model_dump(
                by_alias=True, exclude_defaults=True)
            if gs:
                container["global_settings"] = gs
            else:
                container.pop("global_settings", None)
        if "model_settings" in container:
            ms = _coerce_model(ModelSettings, container["model_settings"]).model_dump(
                exclude_defaults=True)
            if ms:
                container["model_settings"] = ms
            else:
                container.pop("model_settings", None)
        if "nodes" in container:
            trimmed: Dict[str, dict] = {}
            raw_nodes = container["nodes"]
            if isinstance(raw_nodes, dict):
                for key, nd in raw_nodes.items():
                    d = _coerce_model(NodeConfig, nd if isinstance(nd, dict) else {}
                                      ).model_dump(exclude_defaults=True)
                    if d:  # an all-default node carries no information — drop it
                        trimmed[key] = d
            if trimmed:
                container["nodes"] = trimmed
            else:
                container.pop("nodes", None)

    def _minimize_raw(self) -> None:
        """Minimize every section so the file contains only modified fields."""
        self._minimize_section(self._raw)  # Source (top level: globals + model + nodes)
        assets = self._raw.get("assets")
        if isinstance(assets, dict):
            for sect in assets.values():
                if isinstance(sect, dict):
                    self._minimize_section(sect)
            if not assets:  # no models left → drop the empty container
                self._raw.pop("assets", None)

    # --- asset bookkeeping (raw sections; no assembly needed) ---

    def asset_entries(self) -> Dict[str, dict]:
        """``{asset_name: section}`` raw asset sections (may lack files on disk).

        Excludes the reserved Static entry — Static is stored in ``assets`` to share
        the code path, but it's not a user asset (it has its own fixed Model Tree row).
        """
        assets = self._raw.get("assets")
        if not isinstance(assets, dict):
            return {}
        return {k: v for k, v in assets.items() if k != STATIC_MODEL_NAME}

    def asset_slug_for(self, name: str) -> str:
        """The stored slug for an asset (fallback: derive from the name)."""
        sect = self.asset_entries().get(name) or {}
        return sect.get("slug") or asset_slug(name)

    def variant_for_model(self, model: str) -> str:
        """Map a model id to its cache variant ("root"/"static"/"asset-{slug}").

        The variant names the model's cache DIRECTORY; which geometry STAGE to
        load (source vs main) is a separate axis — the GUI always displays a
        model's MAIN stage (always baked). Cache freshness is the caller's
        concern (``load_model`` fails loud on a stale stage rather than
        silently serving something else).
        """
        if model == MODEL_SOURCE:
            return ROOT_VARIANT
        if model == MODEL_STATIC:
            return "static"
        return "asset-" + self.asset_slug_for(asset_name_of(model))

    def source_to_main_inputs(self, model: str) -> dict:
        """The model's Source→Main BAKE INPUTS as a normalized dict — the exact
        payload compared against a variant's ``bake-stamp.json`` to decide
        "Main Rebuild Required". Root model = orientation + datum + the three
        edit maps; generated models = the edit maps only (no orientation).

        Root body/origin edits on a to-be-asset subtree BAKE INTO MAIN and flow
        into the asset by pruning (edit-at-Root-flows-down) — they are NOT
        filtered out here. The old double-edit crash (a Root split AND a
        separate asset-section split on the same path) is instead self-healed at
        generation time, which drops an asset recipe whose path no longer
        resolves in the pruned tree (see ``assets_build``)."""
        out: dict = {
            "structure": self.get_structure_map(model) or {},
            "splits": self.get_split_map(model) or {},
            "origins": self.get_origin_map(model) or {},
            "transforms": self.get_transform_map(model) or {},
        }
        if model == MODEL_SOURCE:
            ms = self.get_raw_model_settings(MODEL_SOURCE)
            out["up_direction"] = str(ms.get("up_direction", "+Z"))
            out["z_rotation_deg"] = int(ms.get("z_rotation_deg", 0))
            out["origin_offset"] = [
                float(ms.get("origin_offset_x", 0.0)),
                float(ms.get("origin_offset_y", 0.0)),
                float(ms.get("origin_offset_z", 0.0)),
            ]
        return out

    # --- restructure maps (Feature A) ---

    def get_structure_map(self, model: str) -> Optional[dict]:
        """The model's raw structure map dict, or ``None`` (never materialized —
        callers validate via ``restructure.load_structure_map``)."""
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        raw = sect.get("structure")
        return raw if isinstance(raw, dict) else None

    def set_structure_map(self, model: str, raw: Optional[dict]) -> None:
        """Store (or remove, when ``None``/empty) a model's structure map + save."""
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        if raw:
            sect["structure"] = raw
        else:
            sect.pop("structure", None)
        self._write()

    def has_structure(self, model: str) -> bool:
        """True when the model has a NON-EMPTY structure map stored."""
        raw = self.get_structure_map(model)
        return bool(raw) and bool(raw.get("assemblies") or raw.get("moves"))

    # --- split/origin maps (geometry edits — same raw-dict pattern) ---

    def _get_raw_map(self, model: str, key: str) -> Optional[dict]:
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        raw = sect.get(key)
        return raw if isinstance(raw, dict) else None

    def _set_raw_map(self, model: str, key: str, raw: Optional[dict]) -> None:
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        if raw:
            sect[key] = raw
        else:
            sect.pop(key, None)
        self._write()

    def get_split_map(self, model: str) -> Optional[dict]:
        """The model's raw split-bodies map (path → recipe), or ``None``
        (callers validate via ``geometry_edits.load_split_map``)."""
        return self._get_raw_map(model, "splits")

    def set_split_map(self, model: str, raw: Optional[dict]) -> None:
        self._set_raw_map(model, "splits", raw)

    def get_origin_map(self, model: str) -> Optional[dict]:
        """The model's raw custom-origin map (path → frame), or ``None``
        (callers validate via ``geometry_edits.load_origin_map``)."""
        return self._get_raw_map(model, "origins")

    def set_origin_map(self, model: str, raw: Optional[dict]) -> None:
        self._set_raw_map(model, "origins", raw)

    def get_joint_map(self, model: str) -> Optional[dict]:
        """The model's raw joint map (Body1 path → joint), or ``None`` (callers
        validate via ``geometry_edits.load_joint_map``). Joints are EXPORT metadata
        (USD ``UsdPhysics``), NOT a geometry bake input — deliberately excluded from
        ``has_geometry_edits`` so a joint change never triggers a model rebuild."""
        return self._get_raw_map(model, "joints")

    def set_joint_map(self, model: str, raw: Optional[dict]) -> None:
        self._set_raw_map(model, "joints", raw)

    def get_datum_map(self, model: str) -> Optional[dict]:
        """The model's raw Datums map (datum id → datum), or ``None`` (callers
        validate via ``geometry_edits.load_datum_map``). Datums are persistent
        REFERENCE geometry, NOT a bake input — deliberately excluded from
        ``source_to_main_inputs``/``has_geometry_edits`` (like joints) so adding a
        datum never triggers a model rebuild and STEP/``.xbf`` stays byte-neutral."""
        return self._get_raw_map(model, "datums")

    def set_datum_map(self, model: str, raw: Optional[dict]) -> None:
        self._set_raw_map(model, "datums", raw)

    def get_transform_map(self, model: str) -> Optional[dict]:
        """The model's raw component-transform map (path → transform), or
        ``None`` (callers validate via ``geometry_edits.load_transform_map``).
        A Transform rigidly MOVES a component/subtree's world placement and
        BAKES into the model — unlike joints it IS a geometry bake input (see
        ``source_to_main_inputs``/``has_geometry_edits``), so a change triggers a
        rebuild and removing it reverts the geometry (bakes start from pristine
        source)."""
        return self._get_raw_map(model, "transforms")

    def set_transform_map(self, model: str, raw: Optional[dict]) -> None:
        self._set_raw_map(model, "transforms", raw)

    def has_geometry_edits(self, model: str) -> bool:
        """True when the model stores any split recipe, origin frame, or
        component transform."""
        return (bool(self.get_split_map(model)) or bool(self.get_origin_map(model))
                or bool(self.get_transform_map(model)))

    def get_raw_model_settings(self, model: str) -> dict:
        """A COPY of the model's raw ``model_settings`` dict (minimized: absent
        keys mean defaults). Lets the GUI read the BASE model's orientation while
        a different model is active (asset restructure rebuilds)."""
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        ms = sect.get("model_settings")
        return copy.deepcopy(ms) if isinstance(ms, dict) else {}

    def get_raw_nodes(self, model: str) -> dict:
        """A COPY of the model's raw path-keyed node configs (Restructure re-keys
        them through a structure change)."""
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        nodes = sect.get("nodes")
        return copy.deepcopy(nodes) if isinstance(nodes, dict) else {}

    def set_raw_nodes(self, model: str, nodes: dict) -> None:
        """Replace the model's raw node configs (path-keyed) + save."""
        sect = self._raw if model == MODEL_SOURCE else self._section(model)
        if nodes:
            sect["nodes"] = nodes
        else:
            sect.pop("nodes", None)
        self._write()

    def source_asset_paths(self) -> set[str]:
        """Tree paths of the SOURCE nodes currently marked ``is_asset`` (raw read —
        works regardless of which model is active, no assembly needed)."""
        nodes = self._raw.get("nodes")
        if not isinstance(nodes, dict):
            return set()
        return {p for p, nd in nodes.items()
                if isinstance(nd, dict) and nd.get("is_asset")}

    def delete_model_section(self, model: str) -> bool:
        """Remove ONE non-source model's config section by MODEL ID — an asset
        (``asset:Name``) OR Static (``MODEL_STATIC``). Not its cache files. Returns
        True if removed. Does NOT unmark the source node — a later Generate re-seeds
        a fresh section for a still-marked asset.
        """
        assets = self._raw.get("assets")
        if not isinstance(assets, dict):
            return False
        if model == MODEL_STATIC:
            name = STATIC_MODEL_NAME
        elif is_asset_model(model):
            name = asset_name_of(model)
        else:
            return False  # Source (or an unknown id) has no deletable asset section
        if name not in assets:
            return False
        del assets[name]
        self._write()
        return True

    def model_section_names(self) -> List[str]:
        """Names of every non-source model section stored in ``assets`` — the user
        assets AND the reserved Static (used to count/confirm a bulk delete)."""
        assets = self._raw.get("assets")
        return list(assets) if isinstance(assets, dict) else []

    def delete_all_model_sections(self) -> int:
        """Remove EVERY non-source model config section — all assets AND Static.
        Returns the count removed. Cache files are untouched; source ``is_asset``
        marks remain (a later Generate re-seeds fresh sections)."""
        assets = self._raw.get("assets")
        if not isinstance(assets, dict) or not assets:
            return 0
        n = len(assets)
        self._raw.pop("assets", None)
        self._write()
        return n

    def ensure_asset_section(self, name: str, slug: str, source_node: str,
                             prototype: str = "",
                             seed_model_settings: Optional[dict] = None,
                             seed_nodes: Optional[dict] = None) -> bool:
        """Create/refresh an asset's section. Returns True if NEWLY created.

        The seeds (a snapshot of the source's orientation, and applicable node
        states remapped into the asset's tree) apply ONLY on creation — a
        regeneration never clobbers the asset's own customized settings.

        ``prototype`` is the marked node's STEP prototype (referred product/master)
        name, ``""`` when it has none. Refreshed every call (like ``slug``/
        ``source_node``); informational only — nothing consumes it yet.
        """
        assets = self._raw.setdefault("assets", {})
        sect = assets.get(name)
        created = not isinstance(sect, dict)
        if created:
            sect = {"model_settings": copy.deepcopy(seed_model_settings or {}),
                    "nodes": copy.deepcopy(seed_nodes or {})}
            assets[name] = sect
        sect["slug"] = slug
        sect["source_node"] = source_node
        sect["prototype"] = prototype
        return created

    def ensure_static_section(self, seed_model_settings: Optional[dict] = None,
                              seed_nodes: Optional[dict] = None) -> bool:
        """Create the Static section if absent. Returns True if NEWLY created.

        Static is just a reserved entry in ``assets`` — this delegates to
        :meth:`ensure_asset_section` so it uses the identical code path as any
        asset (same snapshot-on-create semantics for its node seeds).
        """
        return self.ensure_asset_section(
            STATIC_MODEL_NAME, STATIC_VARIANT, "",
            seed_model_settings=seed_model_settings, seed_nodes=seed_nodes)

    def bake_model_settings(self, model: str, updates: dict) -> None:
        """Overwrite specific ``model_settings`` fields in a section unconditionally.

        Used at generation to RE-BAKE the source's scene-frame settings (export
        orientation, and for Static the origin offset) into every generated model
        EACH time — Static shares the source frame and assets are Z-up from the
        same source, so these always inherit from the source rather than being
        snapshot-once like per-model node/color edits.
        """
        if not updates:
            return
        sect = self._section(model)
        ms = sect.setdefault("model_settings", {})
        ms.update(updates)

    # --- activation / save ---

    def _section(self, model: str) -> dict:
        """The raw section for a model id, seeding missing static/asset sections.

        A fresh section starts with default (empty) model_settings — generation
        seeds the intended snapshot explicitly via ``ensure_*_section``.
        """
        if model == MODEL_SOURCE:
            return self._raw
        # Static and every asset live under ``assets`` (Static under its reserved
        # key) — one unified path, no special top-level ``static`` section.
        name = STATIC_MODEL_NAME if model == MODEL_STATIC else asset_name_of(model)
        assets = self._raw.setdefault("assets", {})
        sect = assets.get(name)
        if not isinstance(sect, dict):
            sect = {"model_settings": {}, "nodes": {}}
            assets[name] = sect
        return sect

    def activate(self, model: str, assembly=None) -> Tuple[SceneConfig, List[str]]:
        """Materialize a model's config: the SHARED globals + ITS model settings.

        ``assembly`` must be the ACTIVE model's assembly (its tree defines the
        paths); without one, node keys stay as paths (headless/no-translate use).
        Returns ``(config, unmatched)`` like the old ``load_scene_config``.
        """
        self.active_model = model
        sect = self._section(model)
        # Validate each piece INDEPENDENTLY and tolerantly, so a missing section
        # (e.g. a hand-deleted ``model_settings``) or a single bad value defaults
        # only that piece instead of wiping the whole model's config.
        global_settings = _coerce_model(GlobalConfig, self._raw.get("global_settings"))
        model_settings = _coerce_model(ModelSettings, sect.get("model_settings"))
        raw_nodes = dict(sect.get("nodes") or {})
        unmatched: List[str] = []
        if assembly is not None and raw_nodes:
            raw_nodes, unmatched = _translate_nodes_in(raw_nodes, assembly)
        nodes: Dict[str, NodeConfig] = {}
        for key, nd in raw_nodes.items():  # one bad node can't drop the others
            nodes[key] = _coerce_model(NodeConfig, nd if isinstance(nd, dict) else {})
        version = self._raw.get("version", SCHEMA_VERSION)
        if not isinstance(version, int):
            version = SCHEMA_VERSION
        config = SceneConfig(version=version, global_settings=global_settings,
                             model_settings=model_settings, nodes=nodes)
        return config, unmatched

    def save_active(self, config: SceneConfig, assembly=None) -> str:
        """Serialize the ACTIVE model's config back into its section and write.

        ``global_settings`` always writes to the TOP level (file-wide — editing
        e.g. the display quality while an asset is active persists for every
        model); ``model_settings`` + ``nodes`` write into the active section.
        Inactive sections round-trip verbatim (never path-translated or pruned —
        a deleted asset's section is kept so remarking restores edits).
        """
        # by_alias so the mesh-quality fields serialize with the GUI terminology
        # (allowable_linear_mesh_error, …); other fields dump by their name.
        data = config.model_dump(by_alias=True)
        nodes = data.get("nodes", {})
        if assembly is not None:
            nodes = _translate_nodes_out(nodes, assembly)
        model = self.active_model
        self._raw["version"] = data["version"]
        self._raw["global_settings"] = data["global_settings"]
        if model == MODEL_SOURCE:
            self._raw["model_settings"] = data["model_settings"]
            self._raw["nodes"] = nodes
        else:
            sect = self._section(model)
            sect["model_settings"] = data["model_settings"]
            sect["nodes"] = nodes
        return self._write()


def load_scene_config(source_path: str, assembly=None) -> Tuple[SceneConfig, List[str]]:
    """Load the SOURCE model's config; return ``(config, unmatched)``.

    Thin wrapper over :class:`ModelConfigStore` kept for the existing call sites
    (export CLIs, tests). Keys that don't resolve to a component in THIS file are
    dropped and described in ``unmatched`` — the intended-tolerant behaviour for
    reusing a config across STEP revisions (see OPEN TODO on reconciliation).
    A missing/unreadable/invalid file yields a default config and no issues.
    """
    store = ModelConfigStore(source_path)
    store.load()
    return store.activate(MODEL_SOURCE, assembly)


def save_scene_config(config: SceneConfig, source_path: str, assembly=None) -> str:
    """Write the SOURCE config beside the source file (nodes keyed by tree path).

    Read-modify-write through :class:`ModelConfigStore`, so any ``static``/``assets``
    sections already in the file are preserved. Returns the path.
    """
    store = ModelConfigStore(source_path)
    store.load()
    return store.save_active(config, assembly)
