SYNTHESIS PASS

You are given the JSON outputs of Passes 0-4. You are NOT given the paper. Produce the final report in Markdown. Do not introduce new findings; only organise, deduplicate, and rank what the passes found. Every claim you make must trace to one of the pass outputs.

Some findings carry a `stability` field: `stable` means the finding appeared in every repeated run of that pass, `unstable` means it appeared in only some runs. Mark unstable findings as such in the table; they are candidates for rubric ambiguity rather than certain issues.

Structure the report exactly as:

# Review report

## 1. Verdict
One paragraph. Is the paper broadly sound, or are there problems serious enough to undermine its conclusions? Name the one or two most important findings.

## 2. Findings
A Markdown table of every finding, sorted critical -> major -> minor, with columns: Severity | Location | Description | Evidence. Evidence is the quotation or URL. Append "(unstable)" to the severity cell for unstable findings.

## 3. Reference audit
One line per bibliography entry, in index order: the index, a status icon, and the reference. Icons: verified, warning for metadata mismatch, cross for not found, recycle for retracted, question mark for could not verify. Give details for anything that is not verified.

## 4. Spelling and language
The count of confirmed typos, the list of inconsistencies (spelling variant, hyphenation, terminology), and whether the paper is in a consistent language variant.

## 5. Unverifiable items
Everything marked `could_not_verify` across all passes, with what a human should do to check it.

## 6. Pass coverage
Which passes ran, whether a search tool was available, and every `limitations` entry reported by the passes.

Output Markdown only. No JSON, no preamble.
