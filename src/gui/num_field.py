"""A ``QDoubleSpinBox`` that does not ROUND the value it holds.

**Why this exists.** ``QDoubleSpinBox`` quantises to ``decimals()`` — both when the
user types and when code calls ``setValue`` — so a field built with
``setDecimals(2)`` silently turns 12.3456789 into 12.35. That is fine for a
tolerance knob and wrong for a geometry parameter: the Component Editor's Transform
pane round-trips its values through these fields (``_preload_transform`` writes the
stored ``BodyTransform`` in, ``_commit_transform`` reads it back out), so every
re-open of an existing transform used to DEGRADE it — a CGB-derived offset such as
``-2.7182818284`` came back as ``-2.72`` and the body moved.

The fix is to carry full precision internally (``decimals`` = 12, i.e. below any
meaningful geometric tolerance and past what a float64 mm value can resolve) while
DISPLAYING the shortest exact form, so the field still reads "90°" and not
"90.000000000000°". Qt appends ``prefix``/``suffix`` around ``textFromValue``, so
those keep working.

The widget's locale is forced to ``C`` so Qt's own text→value parse uses the same
``.`` decimal separator this class formats with (the default locale might use
``,`` and then a typed value would not round-trip).
"""

from __future__ import annotations

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QDoubleSpinBox

#: Enough to be lossless for any geometry value we author (1e-12 mm), while still
#: inside QDoubleSpinBox's supported range.
FULL_DECIMALS = 12


class PreciseDoubleSpinBox(QDoubleSpinBox):
    """A spin box that keeps what you type/set and shows the shortest exact form."""

    def __init__(self, parent=None, decimals: int = FULL_DECIMALS) -> None:
        super().__init__(parent)
        self.setLocale(QLocale.c())
        self.setDecimals(int(decimals))

    def textFromValue(self, value: float) -> str:  # noqa: N802 - Qt naming
        s = f"{float(value):.{self.decimals()}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"

    def valueFromText(self, text: str) -> float:  # noqa: N802 - Qt naming
        s = str(text)
        for fix in (self.prefix(), self.suffix()):
            if fix:
                s = s.replace(fix, "")
        s = s.strip()
        try:
            return float(s)
        except ValueError:
            return float(self.value())
