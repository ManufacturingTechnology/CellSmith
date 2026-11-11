# Extract the version from the __version__.py file
build_version = $(shell cat ../src/__version__.py | grep "__version__" | sed 's/^[^"]*//g' | sed 's/"//g')

all: dist/index.html

dist/index.html: venv/touchfile
	export SITE_NAME="CellSmith v$(build_version)" && \
	echo "SITE_NAME: $${SITE_NAME}" && \
	venv/bin/mkdocs build --site-dir dist/

test: dist/index.html
	python3 -m http.server -d dist 4000

dev: venv/touchfile
	export SITE_NAME="CellSmith v$(build_version)" && \
	echo "SITE_NAME: $${SITE_NAME}" && \
	venv/bin/mkdocs serve --livereload -a localhost:4000 -f mkdocs.dev.yml
#	DOCS_EXCLUDE=AI/ && echo "DE: $$DOCS_EXCLUDE" && venv/bin/mkdocs serve --livereload -a localhost:4000
#	venv/bin/mkdocs serve --livereload -a localhost:4000
#	venv/bin/mkdocs serve --livereload -a localhost:4000 -f mkdocs.claude.yml
	
clean:
	@rm -rf dist/
	@rm -rf venv/

# Update venv when requirements.txt changes
venv/touchfile: requirements.txt
# 	Create a virtual environment if it doesn't exist
	test -d venv || python3 -m venv venv
#	Install python dependencies from requirements.txt
	. venv/bin/activate; pip install -Ur requirements.txt
#	Signal that venv has been updated for due to requirements.txt change
	touch venv/touchfile
