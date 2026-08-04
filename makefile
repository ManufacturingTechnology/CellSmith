
CONDA_ENV := CellSmithEnv

# Every target is a command, not a file — without this, a target sharing a name
# with a directory (`dist`, `build`) would be skipped as "already up to date".
.PHONY: all run dev build deb test test-ci clean

all: build

run: dev
	conda run --no-capture-output -n $(CONDA_ENV) python -m src.main $(ARGS)

dev:
	conda env list | grep -q '^$(CONDA_ENV) ' || conda env create -f packaging/environment.yml

# Linux onedir distributable: dist/CellSmith/ + dist/CellSmith-v<ver>-linux-x86_64.tar.gz
# (PyInstaller cannot cross-compile — run this ON Linux, e.g. under WSL2.)
build: dev
	conda run --no-capture-output -n $(CONDA_ENV) python -m pip install --quiet "pyinstaller>=6.10"
	# Mesh-import deps (ADDITIVE path; manylinux wheels exist). manifold3d is
	# optional — fall back to the no-parallel source build if no wheel, non-fatal.
	conda run --no-capture-output -n $(CONDA_ENV) python -m pip install --quiet trimesh mapbox_earcut scipy shapely
	conda run --no-capture-output -n $(CONDA_ENV) python -m pip install --quiet manifold3d || \
		conda run --no-capture-output -n $(CONDA_ENV) python -m pip install --quiet manifold3d --config-settings=cmake.args="-DMANIFOLD_PAR=NONE" || true
	conda run --no-capture-output -n $(CONDA_ENV) python -m PyInstaller packaging/cellsmith.spec --clean --noconfirm
	VERSION=$$(conda run -n $(CONDA_ENV) python -c "ns={}; exec(open('src/__version__.py').read(), ns); print(ns['__version__'])") && \
		tar -czf dist/CellSmith-v$$VERSION-linux-x86_64.tar.gz -C dist CellSmith && \
		echo "Built dist/CellSmith-v$$VERSION-linux-x86_64.tar.gz"
	$(MAKE) deb

# Debian package from the onedir payload already in dist/CellSmith.
# Separate target so it can be rebuilt without re-freezing (~2 min saved), and so
# `make build` failing at the .deb still leaves the tarball. PYTHON points at the
# env interpreter because the icon extraction needs Pillow.
# Layout + the semver->Debian version mapping: packaging/debian/make_deb.sh.
deb:
	@test -x dist/CellSmith/CellSmith || \
		{ echo "dist/CellSmith/CellSmith missing - run 'make build' first"; exit 1; }
	PYTHON="$$(conda run -n $(CONDA_ENV) python -c 'import sys; print(sys.executable)')" \
		bash packaging/debian/make_deb.sh dist

# ---------------------------------------------------------------- tests
# Two tiers, and note the POLARITY: a test is CI-eligible BY DEFAULT and must be
# explicitly opted out with @pytest.mark.local_only. A test whose author forgets
# to mark it therefore still runs in CI (loud) instead of silently never running.
#
#   make test      - everything, including tests needing a real display/GPU driver
#   make test-ci   - only what runs in a Linux container: no display, no GPU
#
# QT_QPA_PLATFORM=offscreen is also set in tests/conftest.py, before Qt is
# imported; it is repeated here so a bare `pytest` invocation behaves the same.
test: dev
	conda run --no-capture-output -n $(CONDA_ENV) \
		env QT_QPA_PLATFORM=offscreen python -m pytest $(ARGS)

test-ci: dev
	conda run --no-capture-output -n $(CONDA_ENV) \
		env QT_QPA_PLATFORM=offscreen LIBGL_ALWAYS_SOFTWARE=1 \
		python -m pytest -m "not local_only" $(ARGS)

clean:
	conda env remove -n $(CONDA_ENV) -y
