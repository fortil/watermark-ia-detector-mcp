PY ?= .venv/bin/python
T ?= tests

.PHONY: install test

install:
	uv venv --allow-existing --python 3.12 .venv
	uv pip install --python $(PY) -e '.[dev]'

test:
	$(PY) -m pytest -q $(T)
