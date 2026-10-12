PYTHON ?= python3
DOCS_REVISION := $(shell $(PYTHON) -c "import json;print(json.load(open('upstream.lock.json'))['docs']['commit'])")
.PHONY: upstream test docs-check error-adoption check clean
upstream:
	$(PYTHON) tools/fetch_upstream.py
test:
	$(PYTHON) -m unittest discover -s tests -v
docs-check:
	$(PYTHON) build/upstream/docs/docs/standard/check.py --root . --standard-revision $(DOCS_REVISION) $(if $(BASE),--base $(BASE),)
check: test docs-check
clean:
	$(PYTHON) -c "import shutil; shutil.rmtree('build', ignore_errors=True)"
