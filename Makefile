# scientific-eval
#
# Usage:
#   make evaluate path/to/paper.pdf      review one paper
#   make evaluate paper.pdf MODEL=...    review with a specific model
#   make ui                              open the drop-a-PDF web UI
#
.DEFAULT_GOAL := help
.PHONY: help install evaluate extract calibrate ui serve models test test-network lint format clean

# Everything after the target name is treated as the path, so
# `make evaluate paper.pdf` works as well as `make evaluate PDF=paper.pdf`.
ARGS := $(filter-out $(firstword $(MAKECMDGOALS)),$(MAKECMDGOALS))
PDF ?= $(firstword $(ARGS))
FOLDER ?= $(firstword $(ARGS))
MODEL ?=
REPEATS ?= 1
OUT ?= out
PORT ?= 8000

MODEL_FLAG := $(if $(MODEL),--model $(MODEL),)

help:  ## Show this help
	@echo "scientific-eval"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  make evaluate paper.pdf              review a paper"
	@echo "  make evaluate paper.pdf MODEL=qwen/qwen3-4b-2507 REPEATS=2"
	@echo "  make calibrate reviewed-papers/"

install:  ## Install dependencies into .venv
	uv sync

evaluate:  ## Review a PDF: make evaluate paper.pdf
	@if [ -z "$(PDF)" ]; then \
		echo "usage: make evaluate path/to/paper.pdf  (or PDF=path/to/paper.pdf)"; exit 2; \
	fi
	uv run scieval review "$(PDF)" $(MODEL_FLAG) --repeats $(REPEATS) --out "$(OUT)"

extract:  ## Parse a PDF without calling any model: make extract paper.pdf
	@if [ -z "$(PDF)" ]; then \
		echo "usage: make extract path/to/paper.pdf"; exit 2; \
	fi
	uv run scieval extract "$(PDF)" --show sections

calibrate:  ## Score against human reviews: make calibrate reviewed-papers/
	@if [ -z "$(FOLDER)" ]; then \
		echo "usage: make calibrate path/to/folder  (X.pdf next to X.review.json)"; exit 2; \
	fi
	uv run scieval calibrate "$(FOLDER)" $(MODEL_FLAG) --out "$(OUT)"

ui serve:  ## Open the drop-a-PDF web UI
	uv run scieval serve --port $(PORT) --out "$(OUT)" $(MODEL_FLAG)

models:  ## List the models the configured endpoint reports
	uv run scieval models

test:  ## Run the test suite
	uv run pytest -q

test-network:  ## Also run the tests that call Crossref and OpenAlex for real
	SCIEVAL_NETWORK_TESTS=1 uv run pytest -q

lint:  ## Check formatting and lint rules
	uv run ruff check src tests
	uv run ruff format --check src tests

format:  ## Apply formatting and safe lint fixes
	uv run ruff check --fix src tests
	uv run ruff format src tests

demo:  ## Build the synthetic test paper with known defects
	uv run python tests/fixtures/paper_builder.py /tmp/synthetic-paper.pdf

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Swallow the path argument so make does not try to build it as a target.
%:
	@:
