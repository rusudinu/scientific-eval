PASS 0 - INVENTORY

Build a structural inventory that later passes will use as ground truth. Do not evaluate anything yet. Do not report findings.

Guidance:
- `language`: one of "en-GB", "en-US", "mixed", "other", judged from spelling variants across the paper.
- `sections`: every top-level and second-level section heading, in document order, with its number if the paper numbers them and the page range if visible.
- `research_questions_or_hypotheses`: quote or closely paraphrase each research question, hypothesis, or stated objective.
- `figures` / `tables`: the identifier (e.g. "Figure 1"), the caption text, and whether the text refers to it anywhere.
- `key_numbers`: EVERY quantity that appears more than once (sample sizes, accuracies, percentages, p-values, totals, durations). For each, give the value as written, what it means, and every location where it appears. These are cross-checked in Pass 2, so be exhaustive rather than selective.
- `bibliography`: each reference entry with its index and its raw text.
- `limitations`: note here if the input is truncated, if a section is missing, or if the bibliography could not be read.
