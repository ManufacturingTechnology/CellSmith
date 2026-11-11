"""Datums panel — a persistent list of USER datums (reference geometry) for the
active model, wired: panel ↔ ``ModelConfigStore.get/set_datum_map`` ↔
``ViewportPanel.set_datum_records``.

Each row = a datum's name + kind, with a visibility checkbox. Buttons add (a new
datum is created by the host from a CGB construction), rename, and delete. The panel
holds NO geometry — it emits intent; the host persists + pushes records to the
viewport. Datums are references only (excluded from the bake — see
``scene_config`` / ``geometry_edits.DatumEntity``).

Qt-only (offscreen-constructable; logic is headless-testable).
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget)


class DatumsPanel(QWidget):
    """A list of the active model's user datums + add/rename/delete/visibility.

    Signals (the host persists + refreshes the viewport):
      addRequested()                     – user clicked "Add" (host runs a CGB pick)
      renameRequested(str id, str name)  – rename a datum
      deleteRequested(str id)            – delete a datum
      visibilityChanged(str id, bool)    – toggle a datum's viewport visibility
      pickRequested(str id)              – a row was CLICKED → feed that datum into
                                           the active construction/Measure command
    """

    addRequested = Signal()
    renameRequested = Signal(str, str)
    deleteRequested = Signal(str)
    visibilityChanged = Signal(str, bool)
    pickRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._records: List[dict] = []
        self._syncing = False
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        head = QLabel("Datums", self)
        f = head.font(); f.setBold(True); head.setFont(f)
        v.addWidget(head)
        self._list = QListWidget(self)
        self._list.itemChanged.connect(self._on_item_changed)
        # Clicking a row PICKS that datum into the active command — the same
        # affordance the fixed global-origin datum tree has in the viewport corner.
        # A click that merely toggled the checkbox must NOT pick (itemChanged fires
        # first, so it sets the guard) — same trick as `_datum_check_toggled`.
        self._check_toggled = False
        self._list.itemClicked.connect(self._on_item_clicked)
        v.addWidget(self._list, 1)
        row = QHBoxLayout()
        self._add_btn = QPushButton("Add…", self)
        self._add_btn.setToolTip("Create a datum from a Construction Geometry pick "
                                 "(point / axis / plane / basis).")
        self._add_btn.clicked.connect(lambda: self.addRequested.emit())
        self._rename_btn = QPushButton("Rename…", self)
        self._rename_btn.clicked.connect(self._on_rename)
        self._del_btn = QPushButton("Delete", self)
        self._del_btn.clicked.connect(self._on_delete)
        for b in (self._add_btn, self._rename_btn, self._del_btn):
            row.addWidget(b)
        v.addLayout(row)

    def set_records(self, records: List[dict]) -> None:
        """Populate the list from datum records (id/name/kind/visible)."""
        self._records = [dict(r) for r in (records or [])]
        self._syncing = True
        self._list.clear()
        for r in self._records:
            it = QListWidgetItem(f"{r.get('name', r.get('id'))}  [{r.get('kind')}]")
            it.setData(Qt.ItemDataRole.UserRole, r.get("id"))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if r.get("visible", True)
                             else Qt.CheckState.Unchecked)
            self._list.addItem(it)
        self._syncing = False

    def _selected_id(self):
        it = self._list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def _on_item_changed(self, it: QListWidgetItem) -> None:
        if self._syncing:
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if rid is not None:
            self._check_toggled = True       # suppress the paired itemClicked
            self.visibilityChanged.emit(
                str(rid), it.checkState() == Qt.CheckState.Checked)

    def _on_item_clicked(self, it: QListWidgetItem) -> None:
        """Row click → ``pickRequested`` (feed this datum to the active command).
        Skipped when the click was on the visibility checkbox."""
        if self._check_toggled:
            self._check_toggled = False
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if rid is not None:
            self.pickRequested.emit(str(rid))

    def _on_rename(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        cur = next((r for r in self._records if r.get("id") == rid), {})
        name, ok = QInputDialog.getText(self, "Rename Datum", "Name:",
                                        text=str(cur.get("name", "")))
        if ok and name.strip():
            self.renameRequested.emit(str(rid), name.strip())

    def _on_delete(self) -> None:
        rid = self._selected_id()
        if rid is not None:
            self.deleteRequested.emit(str(rid))
