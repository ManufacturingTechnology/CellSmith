"""GUI layer (PySide6 + pyvistaqt).

Deliberately EMPTY: importing this package must stay side-effect free so the
headless worker CLIs that live under it (``edges_build``) or import from it
(``assets_build``/``restructure_build`` → ``mesh_ops``) don't drag Qt/VTK into
a non-GUI process. Import ``MainWindow`` from ``src.gui.main_window`` directly.
"""
