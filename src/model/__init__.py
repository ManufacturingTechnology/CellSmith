"""Core data model — OCC/VTK-free, shared across all layers."""

from .assembly import Assembly
from .component import Component

__all__ = ["Assembly", "Component"]
