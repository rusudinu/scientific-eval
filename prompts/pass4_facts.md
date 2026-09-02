PASS 4 - EXTERNAL FACT-CHECKING

You are given factual claims extracted from the paper, and - when a search tool was available - search results retrieved for each claim.

Task 4a. For each claim, compare it against the supplied search results. Record the URL of the source you relied on in `source_url`, what that source says in `source_says`, and the verdict:
- `verified_correct` - a supplied source states the same thing.
- `verified_incorrect` - a supplied source contradicts it.
- `could_not_verify` - no supplied source settles it, or no results were supplied.
Never use a result you were not given. Never cite a URL that does not appear in the supplied results.

Task 4b. From the results supplied for the paper's main research question, list relevant published work the submission does not engage with, especially contradicting evidence or failed replications, in `missing_engagement`.

If `search_tool_available` is false in the input you were given: set it to false in your output, mark every claim `could_not_verify` with `source_says` explaining `no_search_tool`, leave `source_url` empty, and describe in `limitations` what a human should check.
