"""Global per-color recolor dialog.

Presents every unique base color found in the model (one row) and lets the user
assign an optional replacement color per source color. The result is a set of
(from_rgb, to_rgb) rules saved globally in the scene config — a fast way to
recolor *all* parts of a given color at once (e.g. "make every grey part blue").

Pure Qt: no OCC/VTK. Colors are RGB 0..1 tuples throughout; the UI shows the
8-bit values and a swatch.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .color_picker import ColorPickerDialog

RGB = Tuple[float, float, float]

_NO_OVERRIDE_TEXT = "(click to set)"
_SWATCH = 18


def _q(rgb: RGB) -> Tuple[int, int, int]:
    return tuple(int(round(max(0.0, min(1.0, float(c))) * 255)) for c in rgb[:3])


def _label(rgb: RGB) -> str:
    r, g, b = _q(rgb)
    return f"RGB  {r}, {g}, {b}"


def _swatch_icon(rgb: RGB) -> QIcon:
    pm = QPixmap(_SWATCH, _SWATCH)
    pm.fill(QColor.fromRgbF(float(rgb[0]), float(rgb[1]), float(rgb[2])))
    return QIcon(pm)


class RecolorDialog(QDialog):
    """Grid of (source color → optional override) rows; returns the override rules."""

    def __init__(self, source_colors: List[RGB],
                 existing: Optional[Dict[Tuple[int, int, int], RGB]] = None,
                 parent=None, focus_rgb: Optional[RGB] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recolor Registry - Global Per-Color Overrides")
        self.resize(460, 560)

        self._sources: List[RGB] = list(source_colors)
        #: row -> replacement color (RGB 0..1). Absent = no override for that row.
        self._overrides: Dict[int, RGB] = {}
        #: quantized source color -> row, for focusing a specific color.
        self._row_of_key: Dict[Tuple[int, int, int], int] = {}
        existing = existing or {}

        layout = QVBoxLayout(self)

        self._table = QTableWidget(len(self._sources), 2, self)
        self._table.setHorizontalHeaderLabels(["Color found", "Override"])
        self._table.verticalHeader().setVisible(False)
        # Row selection is used to HIGHLIGHT a focused color (from the tree/eyedropper).
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        for row, rgb in enumerate(self._sources):
            src = QTableWidgetItem(_swatch_icon(rgb), _label(rgb))
            src.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, 0, src)
            self._table.setItem(row, 1, QTableWidgetItem())
            key = _q(rgb)
            self._row_of_key[key] = row
            if key in existing:
                self._overrides[row] = existing[key]
            self._refresh_override_cell(row)

        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._table)

        # Focus a specific color (scroll to + select its row) once the dialog is shown.
        self._focus_row = self._row_of_key.get(_q(focus_rgb)) if focus_rgb is not None else None

        buttons = QHBoxLayout()
        clear_all = QPushButton("Clear All", self)
        clear_all.setToolTip("Remove every override in this list")
        clear_all.clicked.connect(self._clear_all)
        buttons.addWidget(clear_all)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        accept = QPushButton("Accept", self)
        accept.setDefault(True)
        accept.clicked.connect(self.accept)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Scroll to + STRONGLY highlight the focused color now that geometry is realized.
        if self._focus_row is None:
            return
        r = self._focus_row
        self._focus_row = None  # only on first show
        # Theme-aware highlight tint so the target row is unmistakable regardless of
        # which widget has focus (a plain selection can render as a faint grey).
        hl = self.palette().color(QPalette.ColorRole.Highlight)
        hlt = self.palette().color(QPalette.ColorRole.HighlightedText)
        for col in (0, 1):
            it = self._table.item(r, col)
            if it is not None:
                it.setBackground(hl)
                it.setForeground(hlt)
        it0 = self._table.item(r, 0)
        if it0 is not None:
            f = it0.font()
            f.setBold(True)
            it0.setFont(f)
        self._table.setCurrentCell(r, 0)
        self._table.selectRow(r)
        self._table.scrollToItem(
            self._table.item(r, 0), QAbstractItemView.ScrollHint.PositionAtCenter)

    # --- cell rendering ---

    def _refresh_override_cell(self, row: int) -> None:
        item = self._table.item(row, 1)
        if item is None:
            return
        rgb = self._overrides.get(row)
        if rgb is None:
            item.setIcon(QIcon())
            item.setText(_NO_OVERRIDE_TEXT)
            item.setForeground(QColor(140, 140, 140))
        else:
            item.setIcon(_swatch_icon(rgb))
            item.setText(_label(rgb))
            item.setForeground(QColor(0, 0, 0))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)

    # --- interactions ---

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col != 1:
            return
        seed = self._overrides.get(row) or self._sources[row]
        chosen = ColorPickerDialog.get_color(
            QColor.fromRgbF(float(seed[0]), float(seed[1]), float(seed[2])),
            self, "Replacement color")
        if chosen is not None:
            # Recolor rules are RGB for now; alpha (if the user set it) is dropped
            # until alpha is wired through the color model (future TODO).
            self._overrides[row] = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._refresh_override_cell(row)

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid() or index.column() != 1:
            return
        row = index.row()
        if row not in self._overrides:
            return
        menu = QMenu(self)
        remove = menu.addAction("Remove override")
        if menu.exec(self._table.viewport().mapToGlobal(pos)) == remove:
            self._overrides.pop(row, None)
            self._refresh_override_cell(row)

    def _clear_all(self) -> None:
        self._overrides.clear()
        for row in range(self._table.rowCount()):
            self._refresh_override_cell(row)

    # --- result ---

    def result_remaps(self) -> List[Tuple[RGB, RGB]]:
        """The (source_color, replacement_color) pairs for rows with an override."""
        return [(self._sources[row], rgb) for row, rgb in sorted(self._overrides.items())]
