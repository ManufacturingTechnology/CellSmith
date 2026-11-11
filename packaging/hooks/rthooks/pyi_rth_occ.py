"""Runtime hook: point OCCT at its bundled resource files.

The dev conda env sets NONE of these — OCCT falls back to compiled-in
parameter defaults for STEP translation, which is fine. But OCAF/XCAF
document persistence (our .xbf geometry cache: TDocStd SaveAs/Open of
BinXCAF) HARD-FAILS without CSF_PluginDefaults/CSF_StandardDefaults
pointing at StdResource ("Plugin: could not find resource file"), and the
rest cost nothing to set. hook-OCC.py bundles the files under
opencascade/resources/. These env vars are inherited by the re-launched
worker executables, which is exactly what we want.
"""

import os
import sys

_res = os.path.join(sys._MEIPASS, "opencascade", "resources")

os.environ["CASROOT"] = os.path.join(sys._MEIPASS, "opencascade")
# STEP/IGES translator parameter files (silent code-default fallback if absent)
os.environ["CSF_STEPDefaults"] = os.path.join(_res, "XSTEPResource")
os.environ["CSF_IGESDefaults"] = os.path.join(_res, "XSTEPResource")
# translation / shape-healing message files (cosmetic fallback if absent)
os.environ["CSF_XSMessage"] = os.path.join(_res, "XSMessage")
os.environ["CSF_SHMessage"] = os.path.join(_res, "SHMessage")
# OCAF/XCAF document persistence — REQUIRED for the .xbf cache
os.environ["CSF_PluginDefaults"] = os.path.join(_res, "StdResource")
os.environ["CSF_StandardDefaults"] = os.path.join(_res, "StdResource")
os.environ["CSF_XCAFDefaults"] = os.path.join(_res, "StdResource")
os.environ["CSF_StandardLiteDefaults"] = os.path.join(_res, "StdResource")
os.environ["CSF_XmlOcafResource"] = os.path.join(_res, "XmlOcafResource")
# units data (these two point at FILES, not directories)
os.environ["CSF_UnitsLexicon"] = os.path.join(_res, "UnitsAPI", "Lexi_Expr.dat")
os.environ["CSF_UnitsDefinition"] = os.path.join(_res, "UnitsAPI", "Units.dat")
# OCC's own 3D viewer (unused — our viewport is pyvista — but harmless)
os.environ["CSF_ShadersDirectory"] = os.path.join(_res, "Shaders")
os.environ["CSF_MDTVTexturesDirectory"] = os.path.join(_res, "Textures")
