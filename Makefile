ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHON := $(ROOT)/backend/.venv/bin/python
RUFF := $(ROOT)/backend/.venv/bin/ruff
POSTGRES_IMAGE := postgres@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24

.PHONY: check check-unit check-db check-web check-browser install prepare-db

install:
	cd "$(ROOT)/backend" && uv sync --frozen --python 3.12
	pnpm --dir "$(ROOT)" install --frozen-lockfile

prepare-db:
	docker image inspect "$(POSTGRES_IMAGE)" >/dev/null 2>&1 || docker pull "$(POSTGRES_IMAGE)"

check: check-unit check-db check-web check-browser

check-unit:
	$(RUFF) check "$(ROOT)/backend"
	$(PYTHON) -m pytest -q "$(ROOT)/backend/tests/test_security.py"
	$(PYTHON) -m unittest discover -s "$(ROOT)/docs/plans/2026-10-01-full-rebuild" -p 'test_*.py'

check-db:
	$(PYTHON) -m pytest -q "$(ROOT)/backend/tests/test_run_store.py"

check-web:
	pnpm --dir "$(ROOT)" typecheck
	pnpm --dir "$(ROOT)" build

check-browser:
	$(PYTHON) -m pytest -q "$(ROOT)/backend/tests/test_browser.py"
