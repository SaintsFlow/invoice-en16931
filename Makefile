# Everything runs inside the container, so the host needs docker and nothing else.
# No python, no uv, no tesseract on the machine you work from.

COMPOSE := docker compose
RUN := $(COMPOSE) run --rm --no-deps api

.PHONY: check format fmt lint types test run build shell clean

## check: the gate, must pass before every PR
check: format lint types test

## format: is the formatting as ruff wants it
format:
	$(RUN) uv run ruff format --check .

## fmt: reformat the code in place
fmt:
	$(RUN) uv run ruff format .
	$(RUN) uv run ruff check --fix .

## lint: lint rules from pyproject
lint:
	$(RUN) uv run ruff check .

## types: mypy in strict mode
types:
	$(RUN) uv run mypy --strict src

## test: the test suite
test:
	$(RUN) uv run pytest -q

## run: start the API on http://localhost:8080
run:
	$(COMPOSE) up --build

## build: rebuild the image
build:
	$(COMPOSE) build

## shell: a shell inside the container, handy for digging around
shell:
	$(RUN) bash

## clean: drop containers and the local caches
clean:
	$(COMPOSE) down --remove-orphans
	rm -rf .pytest_cache .ruff_cache .mypy_cache
