"""PyInstaller entry script.

`src.main` uses relative imports, so it can't be handed to PyInstaller as the
entry script itself; this shim gives Analysis an absolute-import root. Dev runs
keep using `python -m src.main` — this file is only for the frozen build.
"""

from src.main import main

if __name__ == "__main__":
    raise SystemExit(main())
