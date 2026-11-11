"""Triangle-mesh file import (OBJ/STL/USD + more) — the ADDITIVE, SUBORDINATE
parallel path to the B-rep/STEP workflow (which is priority #1; see CLAUDE.md).

This package must stay import-light: ``formats``/``mesh_cache`` are pure
numpy/json (safe to import from the GUI, the export CLIs, and headless code);
``mesh_reader``/``mesh_slice`` import trimesh/pxr and MUST run only inside a
worker subprocess (never in the GUI/VTK process — the numpy-``@`` ban). Keep
this ``__init__`` EMPTY so importing the package never drags trimesh/pxr in.
"""
