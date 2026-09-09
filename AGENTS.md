# AGENTS.md

Operating manual for coding agents working in this repo. See `README.md` for the
user-facing overview of what the tool does.

## What this is

A Python CLI + local FastAPI web UI (`scieval`) that runs a multi-pass correctness
review of a scientific paper (PDF) against any OpenAI-compatible chat completion
endpoint (LM Studio locally, OpenRouter remotely). No source code here talks to a
database; state is files under `out/`.

## Stack

- Python 3.11+, packaged with `uv` / hatchling (`pyproject.toml`, `uv.lock`).
- CLI: `typer` (`src/scieval/cli.py`), console output via `rich`.
- Web UI: `fastapi` + `uvicorn`, one server-rendered page, SSE for progress
  (`src/scieval/web/app.py`, `src/scieval/web/jobs.py`).
- LLM calls via the `openai` SDK against `/v1` (structured output with a
  `json_schema` → `json_object` → plain-text fallback chain, see
  `src/scieval/llm/structured.py`).
- PDF parsing with `pymupdf` (`src/scieval/extract/`).
- Spellcheck via `pyspellchecker` or optional `hunspell` (extra `spylls`).
- Reference lookup via Crossref/OpenAlex (`src/scieval/search/`).

## Key commands

```bash
uv sync                      # install deps into .venv
uv run pytest -q             # test suite (offline, scripted fake LLM)
SCIEVAL_NETWORK_TESTS=1 uv run pytest tests/test_network.py -v   # real Crossref/OpenAlex calls
uv run ruff check src tests  # lint
uv run ruff format src tests # format
uv run scieval --help        # CLI entry point
make evaluate paper.pdf      # = uv run scieval review paper.pdf
make ui                      # = uv run scieval serve
```

`Makefile` targets are the preferred entry points for humans; agents can call
`uv run scieval ...` directly. `make help` lists targets.

## Layout

```
src/scieval/
  cli.py          typer commands: review, calibrate, models, extract, serve,
                   config-show, init-review
  web/            FastAPI app + one HTML page for the drop-a-PDF UI
  config.py       scieval.toml + env vars + CLI flags -> Config
  pipeline.py     orchestrates passes 0-4 + synthesis, writes run outputs
  extract/        pymupdf text, section splitting, bibliography, captions
  spellcheck/     candidate pre-filtering + pluggable backend
  llm/            OpenAI-compatible client, structured-output fallback, provenance
  search/         Crossref lookup, web search providers (tavily/brave/searxng)
  schemas/        pydantic models mirroring the JSON schemas the prompts request
  passes/         one module per pass (pass0_inventory.py ... pass4_facts.py, synthesis.py)
  report/         findings normalisation, run diffing, output file writers
  calibrate/      ground-truth loading, finding matching, agreement metrics
prompts/          the actual prompt text sent to the model, plus VERSION
tests/            pytest suite incl. fake_llm.py (scripted client) and paper_builder.py
                   (builds a synthetic PDF with known defects, used by demo/tests)
```

## Conventions / gotchas

- Config resolution order: `scieval.toml` (cwd, then project root) → env vars
  (`SCIEVAL_PROVIDER`, `SCIEVAL_MODEL`, `SCIEVAL_BASE_URL`) → explicit CLI flags,
  in that order of increasing precedence. See `load_config()` in `config.py`.
- `.env` is loaded manually (`cli.py: _load_dotenv`), not via `python-dotenv`; it
  only sets variables that aren't already in the environment.
- Ruff line-length is 100 but `src/scieval/cli.py` is exempted from `E501`
  (deliberately: one `Annotated` option per line). See `[tool.ruff.lint]` in
  `pyproject.toml` for the other deliberate ignores.
- The default test suite never calls a real model or network service — it uses
  `tests/fake_llm.py`, a scripted OpenAI-compatible client. Network tests
  (`test_network.py`) are opt-in via `SCIEVAL_NETWORK_TESTS=1` because they hit
  Crossref/OpenAlex for real; a mocked test can't catch a rejected query param.
- Everything checkable by code (reference metadata, retraction flags, URLs in
  fact-check output) is enforced in `report/` and `search/`, not trusted from the
  model — see the README's "What the tool decides and what the model decides"
  section before changing pass logic.
- Editing any file under `prompts/` changes its sha256 automatically recorded in
  `run.json` (see `prompt_hashes()` in `src/scieval/llm/provenance.py`), so a run
  before and after a prompt edit is never silently conflated. `prompts/VERSION`
  is a separate, manually-bumped human-readable label — bump it when a prompt
  change is deliberate and worth naming, not for every edit.
- Output write path: `out/<paper>/<run-id>/...` plus a single `out/runs.jsonl`
  index. Don't assume a flat `out/` directory.
