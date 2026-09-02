PASS 3 - REFERENCE VERIFICATION

You are given the bibliography, the sentences in the paper where each reference is cited, and - when a lookup tool was available - the metadata retrieved for each reference from a bibliographic database.

For EACH bibliography entry:
1. Compare the paper's reference text with the retrieved metadata: authors, title, year, venue, DOI. Put the URL of the retrieved record in `found_at`.
   - All key fields agree -> `verified`.
   - A record was found but a field disagrees (wrong year, wrong venue, different author list, different title) -> `metadata_mismatch`, and describe the difference in `mismatch_details`.
   - Lookup ran but found nothing matching -> `not_found`.
   - The record is marked retracted or withdrawn -> `retracted`.
   - No lookup result was supplied for this entry -> `could_not_verify`.
2. Using the citing sentences and any abstract supplied, judge whether the source supports the specific claim it is cited for: `yes`, `weaker`, `different`, `unrelated`, or `could_not_check` when you have no abstract or full text.
3. In `notes`, flag a preprint cited as though peer-reviewed, and a self-citation carrying a claim that no independent source supports.

Then list claims in the paper that need a citation and have none, in `missing_citations`.

If `search_tool_available` is false in the input you were given: set it to false in your output, set every entry to `status: "could_not_verify"` with `notes` explaining `no_search_tool`, still copy the `citing_sentences` through so a human can check quickly, and describe in `limitations` what a human should verify.
