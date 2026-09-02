PASS 1 - MECHANICAL QUALITY AND SPELLING

You are given ONE section of the paper, the Pass 0 inventory, and a candidate list produced by a deterministic spellchecker for that section. Report only problems located in this section.

Task 1a - Spellcheck triage. For each candidate flagged by the spellchecker, decide:
- `typo` - a genuine misspelling; give the correction.
- `domain_term` - a valid technical term, proper noun, acronym, or identifier; not an error.
- `inconsistent` - spelled correctly here but differently elsewhere in the paper (e.g. optimise/optimize, data set/dataset, Wi-Fi/WiFi).
Every candidate in the list must appear exactly once in `spellcheck_triage`. Do not add new typo findings that the spellchecker did not flag unless you are certain and can quote the exact misspelled token.

Task 1b - Language consistency. Check the section against `language` from Pass 0. Flag: mixing en-GB and en-US spellings; sentences or fragments left in another language; inconsistent hyphenation of the same compound; inconsistent capitalisation of the same term.

Task 1c - Grammar. Flag only clear errors (subject-verb agreement, wrong article, dangling modifiers, sentence fragments, wrong preposition). Do not flag style preferences.

Task 1d - Terminology and notation. Flag: the same concept named differently across the paper; a symbol used before it is defined or redefined with a different meaning; an acronym used before its expansion or expanded inconsistently; inconsistent unit formatting (e.g. ms vs msec, 5 % vs 5%).

Task 1e - Figures and tables, for figures and tables belonging to this section. Flag: figure/table not referenced in the text (use `referenced_in_text` from the inventory); non-sequential numbering; caption that does not match content; missing axis labels or units; values in a table that are visibly inconsistent with the caption.

Set `section` in the output to the section title you were given.
