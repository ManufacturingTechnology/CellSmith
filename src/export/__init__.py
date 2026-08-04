"""USD export layer.

- ``usd_writer.write_subtree_usd`` authors a USD asset from a meshed subtree of an
  Assembly: a prim hierarchy mirroring the tree, one ``UsdGeom.Mesh`` per meshed
  leaf (triangles + per-part ``displayColor``), unit-converted (mm→m) and up-axis
  set from the scene config. Geometry + colors only — no physics yet.
- ``usd_cli`` runs that export in a subprocess (reloads the fast .xbf + color
  sidecar + mesh cache), invoked by the GUI's "Export subtree as USD".
- ``obj_writer.write_subtree_obj`` / ``obj_cli`` do the same for Wavefront ``.obj``
  (+ ``.mtl`` colors) — tessellated geometry with the same baked export transform.

Next milestone (rigging): consume the same Assembly + a link/joint config to author
link Xforms and ``UsdPhysics`` revolute/prismatic joints, runnable headless from
the configs alone. Only this layer imports ``pxr`` (kept out of the OCC/VTK layers).
"""
