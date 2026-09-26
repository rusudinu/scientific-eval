# AGENTS.md

scieval is a Python CLI + local FastAPI web UI that runs a multi-pass correctness review of a scientific paper (PDF) against any OpenAI-compatible chat completion endpoint (LM Studio locally, OpenRouter remotely). No database; state is files under `out/`. See `README.md` for the user-facing overview.

## Commands

```bash
uv sync                      # install deps into .venv
uv run pytest -q             # test suite (offline, scripted fake LLM)
uv run ruff check src tests  # lint
uv run ruff format src tests # format
make evaluate paper.pdf      # = uv run scieval review paper.pdf
make ui                      # = uv run scieval serve
SCIEVAL_NETWORK_TESTS=1 uv run pytest tests/test_network.py -v   # real Crossref/OpenAlex calls
```

`make help` lists all targets; prefer them for humans, but agents can call `uv run scieval ...` directly.

## Layout

- `src/scieval/cli.py` — typer commands: review, calibrate, models, extract, serve, config-show, init-review
- `src/scieval/web/` — FastAPI app + one HTML page for the drop-a-PDF UI
- `src/scieval/pipeline.py` — orchestrates passes 0-4 + synthesis, writes run outputs
- `src/scieval/passes/` — one module per pass (`pass0_inventory.py` ... `pass4_facts.py`, `synthesis.py`)
- `src/scieval/llm/` — OpenAI-compatible client, structured-output fallback chain, provenance
- `src/scieval/extract/`, `search/`, `spellcheck/`, `report/`, `calibrate/` — PDF parsing, Crossref/OpenAlex lookup, spellcheck backends, output writers, ground-truth scoring
- `prompts/` — the actual prompt text sent to the model, plus `VERSION`
- `tests/` — pytest suite incl. `fake_llm.py` (scripted client) and `paper_builder.py` (synthetic PDF with known defects)

## Gotchas

- Config resolution order: `scieval.toml` → env vars (`SCIEVAL_PROVIDER`, `SCIEVAL_MODEL`, `SCIEVAL_BASE_URL`) → CLI flags, increasing precedence (`load_config()` in `config.py`).
- `.env` is loaded manually (`cli.py: _load_dotenv`), not via `python-dotenv`; it only sets vars not already in the environment.
- The default test suite never calls a real model or network service (`tests/fake_llm.py`). Network tests are opt-in via `SCIEVAL_NETWORK_TESTS=1` because they hit Crossref/OpenAlex for real.
- Everything checkable by code (reference metadata, retraction flags, URLs) is enforced in `report/`/`search/`, not trusted from the model — read the README's "What the tool decides and what the model decides" before changing pass logic.
- Editing any file under `prompts/` auto-changes its sha256 recorded in `run.json` (`prompt_hashes()` in `llm/provenance.py`); `prompts/VERSION` is a separate, manually-bumped label — bump it only for a deliberate, worth-naming prompt change.
- Output path is `out/<paper>/<run-id>/...` plus one `out/runs.jsonl` index — don't assume a flat `out/` directory.
- Ruff line-length is 100, but `src/scieval/cli.py` is exempted from `E501` (one `Annotated` option per line, deliberately).
