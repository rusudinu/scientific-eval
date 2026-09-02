PASS 2 - INTERNAL CONSISTENCY

You are given the Pass 0 inventory, the abstract, the results and discussion sections, the tables, and the conclusions.

Task 2a - Numbers. For every entry in `key_numbers`, compare all locations; flag any mismatch, quoting both values. Recompute every derived value you can (percentages from counts, totals from components, means from listed data, differences between conditions). Show the arithmetic in `recomputation`. Use `verified_correct` only when you actually recomputed or compared the values; use `could_not_verify` when the underlying counts are not given.

Task 2b - Claims vs. evidence. For each sentence in the abstract and conclusions that makes a claim, identify the specific result (table, figure, or quoted sentence) that supports it. Flag: claims with no supporting result; causal language for correlational designs; generalisation beyond the studied population, dataset, or conditions; superlatives ("significantly outperforms", "state of the art") without a comparison in the paper.

Task 2c - Research question alignment. Compare `research_questions_or_hypotheses` from Pass 0 with what was actually measured. Flag any case where the paper answers a narrower, easier, or different question than the one it posed, or where a stated hypothesis is never tested.

Task 2d - Statistics. Check that test statistics, degrees of freedom, and p-values are mutually consistent; that sample sizes are consistent throughout (and exclusions are explained); that the test matches the design (paired vs. unpaired, parametric assumptions); that effect sizes or confidence intervals are reported. Note p-values clustered just below 0.05 and missing multiple-comparison corrections. For ML/engineering papers: check that train/test separation is stated, that baselines are run under the same conditions, and that reported variance (seeds, runs) exists.

Task 2e - Reproducibility. List every parameter, procedure, dataset version, hardware detail, or assumption that a reader would need and that is not stated. Report these as findings with category `reproducibility`.
