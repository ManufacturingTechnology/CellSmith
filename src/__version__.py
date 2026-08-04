"""Single source of truth for the application version.

Consumed by: `cellsmith.spec` (exec'd, not imported — keeps the build free of
package imports), `src.main --version`, and the build scripts' archive names.
"""

__version__ = "0.1.0-alpha.1"
