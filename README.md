# scientific-eval

Multi-pass correctness review of scientific papers, run against any OpenAI-compatible
endpoint: LM Studio locally, OpenRouter remotely, or anything else that serves `/v1`.

It implements the pass set in [`prompts/paper-review-prompts.md`](prompts/paper-review-prompts.md):

| Pass | What it does | Needs a tool |
| --- | --- | --- |
| 0 | Structural inventory: sections, figures, tables, key numbers, bibliography | no |
| 1 | Mechanical quality: spelling triage, language, grammar, terminology, figures | no |
| 2 | Internal consistency: numbers, claims vs. evidence, statistics, reproducibility | no |
| 3 | Reference verification against a bibliographic database | Crossref |
| 4 | External fact-checking of established-knowledge claims | web search |
| S | Synthesis into a single ranked report | no |

The pipeline produces a first-pass review. The accept/reject decision stays with a human.

## Install

```bash
uv sync
```

Optional hunspell dictionaries (pure Python, no system binary):

```bash
uv sync --extra hunspell
```

## Quick start

Start a model in LM Studio, then:

```bash
uv run scieval models
```

```bash
uv run scieval review paper.pdf --model qwen/qwen3.5-9b
```

Output lands in `out/<paper>/<run-id>/`:

| File | Contents |
| --- | --- |
| `pass0.json` … `pass4.json` | Each pass's raw output, exactly as the schema defines it |
| `findings.csv` | Every finding, one row each, ready for a spreadsheet |
| `findings.json` | The same findings plus severity counts and stability |
| `synthesis.md` | The final ranked report |
| `run.json` | Model id, quantization, prompt version, seed, per-call token usage |
| `extraction.json` | What the PDF parser found, before any model call |

`out/runs.jsonl` gets one summary line per run, so runs can be compared later.

## Commands

```bash
uv run scieval extract paper.pdf --show sections
```

Extraction only. No model calls, so it works with the server offline. `--show` accepts
`sections`, `references`, `captions`, `candidates` and `text`; `--json FILE` writes everything.
Use it to check that section splitting and bibliography parsing worked before spending
tokens on a review.

```bash
uv run scieval review paper.pdf --repeats 2
```

Runs passes 1 and 2 twice and diffs them. A finding present in every run is marked `stable`;
one that appears in only some runs is marked `unstable`, which the prompt set treats as a
candidate for rubric ambiguity rather than a certain issue.

```bash
uv run scieval review paper.pdf --only pass0,pass1,pass2
```

Runs a subset of passes.

```bash
uv run scieval calibrate reviewed-papers/
```

Scores the pipeline against human reviews. See below.

## Providers and models

Providers live in `scieval.toml`. Two are configured out of the box:

```bash
uv run scieval review paper.pdf --provider lmstudio --model qwen/qwen3.5-9b
```

```bash
uv run scieval review paper.pdf --provider openrouter --model qwen/qwen3-235b-a22b
```

OpenRouter reads `OPENROUTER_API_KEY` from the environment or from a `.env` file
next to the project. Copy `.env.example` to `.env` to fill it in.

Different models per pass, for example a large model only where the reasoning is hardest:

```bash
uv run scieval review paper.pdf --model qwen/qwen3-4b-2507 --model-pass pass2=qwen/qwen3.8-27b
```

With no `--model` and no `[models].default`, the first chat model the server reports is used.
Embedding models are skipped.

## Structured output

Every pass asks for `response_format: json_schema` with a strict schema generated from the
pydantic models in `src/scieval/schemas/`. When a server or model rejects that, the call
falls back to `json_object` and then to plain text, parsing the JSON out of fences or
`<think>` blocks. A reply that fails validation gets one repair turn quoting the validation
error. If all of that fails, the pass is recorded as failed in `run.json` and the run
continues. Which route each call took is in `run.json` under `calls[].mode`.

## Choosing a local model

Reasoning models (the ones that emit a `<think>` block) work, and their think blocks are
stripped before parsing, but they are slow here: a review makes at least eleven calls, and
a 9B reasoning model can spend several minutes on each one. For routine runs prefer an
instruct model of similar size, and reserve a reasoning model for Pass 2, which is the pass
that actually has to do arithmetic:

```bash
uv run scieval review paper.pdf --model qwen/qwen3-4b-2507 --model-pass pass2=qwen/qwen3.5-9b
```

`request_timeout_s` in `scieval.toml` (default 900) caps each call. Raise it for a large
model on modest hardware.

## Determinism and provenance

Temperature defaults to 0 and a seed is sent with every call (`--seed`, default 42).
LM Studio honours the seed; OpenRouter treats it as best-effort.

`run.json` records the model id from `GET /v1/models`, the quantization (from LM Studio's
native API, or OpenRouter's endpoints API, or `--quantization`), the prompt version from
`prompts/VERSION` plus a hash of every prompt file, the seed, the temperature, and token
usage per call. Editing a prompt changes its hash, so two runs are always comparable.

## Spellcheck pipeline

The checker finds tokens; the model judges which are real errors. Before Pass 1 the tool:

1. splits the text per section,
2. runs `pyspellchecker` (or hunspell via `spylls`) with the dictionary matching the
   language Pass 0 reported,
3. drops the obvious false positives: bibliography author names, defined acronyms, all-caps
   tokens, tokens containing digits or underscores, LaTeX commands, URLs and DOIs, and
   hyphenated compounds whose parts are all known words,
4. hands the survivors to Pass 1 as `(token, sentence, location, occurrences)`.

Pass 1 classifies each candidate as `typo`, `domain_term` or `inconsistent`. Only typos and
inconsistencies become findings.

## References and fact-checking

Pass 3 does not ask the model to look anything up. A deterministic lookup queries Crossref
by DOI, then by bibliographic search, falling back to OpenAlex, and hands the retrieved
record to the model for comparison. The URL in the output and the retraction flag come from
the database, never from the model. An entry the lookup could not find cannot be reported
as `verified`.

Pass 4 works in three calls: the model extracts checkable claims and a search query for
each, the tool runs the searches, and the model judges only the results it was handed. Any
URL in the output that was not in the supplied results is stripped and the verdict is
downgraded to `could_not_verify`.

Web search is off by default. Enable a provider in `scieval.toml` under `[search]` or with
`--web-search`:

| Provider | Configuration |
| --- | --- |
| `tavily` | `TAVILY_API_KEY` |
| `brave` | `BRAVE_API_KEY` |
| `searxng` | `SEARXNG_URL`, with JSON format enabled in SearXNG |

With no provider, both passes follow rule 3 of the shared system prompt: every external
check is `could_not_verify` with reason `no_search_tool`, and the report says what a human
should check. Pass 3 still fills in the citing sentences for each reference so that check is
quick.

## Calibration

Put reviewed papers in a folder, each `X.pdf` next to an `X.review.json`:

```bash
uv run scieval init-review reviewed-papers/study.pdf
```

That writes a template. Fill it with the human findings:

```json
{
  "paper": "study.pdf",
  "notes": "Reviewed by A. Reviewer, 2026-08-14.",
  "findings": [
    {
      "severity": "critical",
      "category": "numbers",
      "location": "4 Results, p. 6",
      "quote": "accuracy of 94.2% on the held-out set",
      "description": "Abstract reports 94.2% but Table 3 reports 91.7% for the same run."
    }
  ]
}
```

Then:

```bash
uv run scieval calibrate reviewed-papers/
```

Each paper is reviewed and the findings are matched against the human review, one to one,
on quote similarity plus location and description. The report gives precision, recall and F1
overall and per severity, category and pass, plus severity agreement on matched findings,
the findings the model missed, and the findings it reported that the human review does not
have. It writes `calibration.md`, `calibration.csv` and `calibration.json`.

`--reuse` scores the latest stored run per paper instead of calling the model again, which
makes tuning the match threshold free. `--threshold` sets how similar two findings must be
to count as the same issue (default 70).

Read the spurious list before treating precision as an error rate. A human review is rarely
exhaustive, and the pipeline reports mechanical issues most reviewers never write down.

## Configuration

`scieval.toml` in the working directory overrides the one shipped with the project.
`uv run scieval config-show` prints what is actually in effect.

| Section | Key settings |
| --- | --- |
| top level | `provider`, `seed`, `temperature`, `output_dir` |
| `[providers.*]` | `base_url`, `api_key` or `api_key_env`, `native_api` |
| `[models]` | `default`, and `pass0` … `synthesis` overrides |
| `[spellcheck]` | `backend`, `min_token_length`, `max_candidates_per_section` |
| `[search]` | `reference_provider`, `web_provider`, `max_results_per_query` |
| `[limits]` | `pass0_max_chars`, `pass1_section_max_chars`, `pass3_batch_size` |

## How the passes are called

Passes 0, 2, 3 and 4 follow the prompt set's one-call-per-pass rule with two deliberate
exceptions, both because local models cannot drive tools mid-turn or hold a whole paper in
context reliably:

- Pass 1 runs one call per section, as the prompt set specifies.
- Pass 3 batches references (10 per call by default) and adds one call for missing citations.
- Pass 4 runs three calls: extract claims, search, verify.

Section splitting is heuristic first (numbered headings, font size, known heading names) and
is then re-anchored to the section list Pass 0 reports, which catches unnumbered and
two-column headings the layout pass misses. A re-split that anchors fewer sections than the
heuristics found is discarded.

## Development

```bash
uv run pytest
```

The tests build a synthetic paper with known defects (`tests/fixtures/paper_builder.py`) and
run the whole pipeline against a scripted model, so no server is needed.

```
src/scieval/
  cli.py          commands
  config.py       TOML + environment + flags
  pipeline.py     orchestration
  extract/        pymupdf text, sections, bibliography, captions
  spellcheck/     backends and candidate pre-filtering
  llm/            client, structured output, provenance
  search/         Crossref lookup, web search providers
  schemas/        pydantic models mirroring the prompt schemas
  passes/         one module per pass
  report/         findings normalisation, run diffing, output files
  calibrate/      ground truth, matching, agreement metrics
```
