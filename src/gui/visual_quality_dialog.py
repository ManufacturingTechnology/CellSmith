"""Modal dialog for the two VIEWING mesh-quality tolerances.

These used to be spinboxes on every viewport settings strip; they now live
behind an "Adjust Visual Quality" button (leftmost on the strip). Apply pushes
the values onto the shared :class:`~src.gui.view_settings.ViewSettingsBus`, so
every viewport re-syncs and MainWindow persists them (GlobalConfig) and
rebuilds the main viewport. These affect DISPLAY only — never exported
geometry (exports carry their own quality in the export dialog).
"""

from __future__ import annotations

from typing import Tuple

from PySide6.QtWidgets import (QDialogButtonBox, QDialog, QDoubleSpinBox,
                               QFormLayout, QLabel, QVBoxLayout)

_LINEAR_TIP = (
    "Allowable LINEAR mesh error (chordal deflection, mm) — VIEWING quality "
    "only, never the exported geometry (exports have their own quality "
    "settings in the export dialog).\n\n"
    "The max distance a display triangle may deviate from the true surface: "
    "LOWER = finer/higher quality (smoother, slower to mesh); HIGHER = "
    "coarser/lower quality (faster).")

_ANGULAR_TIP = (
    "Allowable ANGULAR mesh error (degrees) — VIEWING quality only, never the "
    "exported geometry (exports have their own quality settings in the export "
    "dialog).\n\n"
    "The max angle between adjacent display facets on a curved surface: LOWER "
    "= finer/higher quality (rounder holes and curves, more triangles); HIGHER "
    "= coarser/lower quality (visibly faceted curves, faster).")


class VisualQualityDialog(QDialog):
    """Two whole-number spinboxes (Linear mm / Angular deg) + Apply/Cancel.

    Constructed with the CURRENT values (read from the shared bus by the
    caller); :meth:`values` returns the chosen pair after an accepted exec.
    """

    def __init__(self, linear: float, angular: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Adjust Visual Quality")

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Display mesh quality only — this never changes exported geometry.\n"
            "Lower = finer/smoother (slower); higher = coarser (faster).", self)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self._linear = QDoubleSpinBox(self)
        self._linear.setDecimals(0)
        self._linear.setRange(1, 50)
        self._linear.setSingleStep(1)
        self._linear.setValue(round(linear))
        self._linear.setToolTip(_LINEAR_TIP)
        lin_lbl = QLabel("Allowable Linear Mesh Error [mm]:", self)
        lin_lbl.setToolTip(_LINEAR_TIP)
        form.addRow(lin_lbl, self._linear)

        self._angular = QDoubleSpinBox(self)
        self._angular.setDecimals(0)
        self._angular.setRange(1, 90)
        self._angular.setSingleStep(1)
        self._angular.setValue(round(angular))
        self._angular.setToolTip(_ANGULAR_TIP)
        ang_lbl = QLabel("Allowable Angular Mesh Error [deg]:", self)
        ang_lbl.setToolTip(_ANGULAR_TIP)
        form.addRow(ang_lbl, self._angular)
        layout.addLayout(form)

        buttons = QDialogButtonBox(self)
        buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> Tuple[float, float]:
        """(linear_mm, angular_deg) as chosen."""
        return float(self._linear.value()), float(self._angular.value())
