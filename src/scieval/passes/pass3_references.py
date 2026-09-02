"""Pass 3 - reference verification.

Metadata comes from a deterministic bibliographic lookup, never from the model:
the model only judges the comparison and whether the source supports the claim.
"""

from __future__ import annotations

from ..extract.bibliography import Reference
from ..extract.sections import sections_of_kind
from ..schemas import Pass3Output
from ..schemas.pass3 import CitingSentence, ReferenceCheck
from ..schemas.common import ReferenceStatus, SupportsClaim
from ..search.base import ReferenceLookup, ReferenceRecord
from .base import PaperContext, PassRunner, as_json, clip, load_prompt


def run(runner: PassRunner, paper: PaperContext, lookup: ReferenceLookup) -> Pass3Output:
    references = paper.references
    available = bool(getattr(lookup, "available", False)) and bool(references)
    output = Pass3Output(search_tool_available=available)

    if not references:
        output.limitations.append(
            "No bibliography could be extracted from the PDF; reference verification was skipped."
        )
        _add_missing_citations(runner, paper, output)
        return output

    if not available:
        output.references = [_unverified(ref) for ref in references]
        output.limitations.append(
            "No reference lookup tool was available (reason: no_search_tool). A human should "
            "search each entry's title and DOI, confirm authors, year and venue, and check "
            "Retraction Watch and the publisher page for retraction notices."
        )
        _add_missing_citations(runner, paper, output)
        return output

    records = {ref.index: _lookup_reference(lookup, ref) for ref in references}
    prompt = load_prompt(runner.config, "pass3_references")
    batch_size = max(1, runner.config.limits.pass3_batch_size)

    for start in range(0, len(references), batch_size):
        batch = references[start : start + batch_size]
        payload = _batch_payload(batch, records)
        result = runner.structured(
            pass_name="pass3",
            label=f"pass3:refs {batch[0].index}-{batch[-1].index}",
            task_prompt=prompt + "\n\nFor this call, fill `references` only. Leave "
            "`missing_citations` empty; it is collected in a separate call.",
            payload=payload,
            schema=Pass3Output,
        )
        if result is None:
            output.references.extend(_unverified(ref) for ref in batch)
            output.limitations.append(
                f"References {batch[0].index}-{batch[-1].index}: the model call failed; "
                "entries were marked could_not_verify."
            )
            continue
        output.references.extend(_reconcile(result.references, batch, records))
        output.limitations.extend(result.limitations)

    _add_missing_citations(runner, paper, output)
    output.references.sort(key=lambda r: r.index)
    return output


def _lookup_reference(lookup: ReferenceLookup, ref: Reference) -> ReferenceRecord:
    try:
        return lookup.lookup(raw=ref.raw, doi=ref.doi, title=ref.title, year=ref.year)
    except Exception:
        return ReferenceRecord(found=False, source=getattr(lookup, "name", "unknown"))


def _batch_payload(batch: list[Reference], records: dict[int, ReferenceRecord]) -> str:
    entries = []
    for ref in batch:
        record = records.get(ref.index)
        entries.append(
            {
                "index": ref.index,
                "raw": ref.raw,
                "parsed": {"title": ref.title, "year": ref.year, "authors": ref.authors, "doi": ref.doi},
                "citing_sentences": [
                    {"quote": c.quote, "location": c.location} for c in ref.citing_sentences
                ],
                "lookup_result": record.as_dict() if record else {"found": False},
            }
        )
    return (
        "=== BIBLIOGRAPHY ENTRIES WITH LOOKUP RESULTS ===\n"
        + as_json(entries, limit=60000)
        + "\n\nThe `lookup_result` block is what a bibliographic database returned for that entry. "
        "Compare it with `raw`. Use only the URL in `lookup_result.url`; never invent one. "
        "Return one object in `references` for every index listed above."
    )


def _reconcile(
    produced: list[ReferenceCheck], batch: list[Reference], records: dict[int, ReferenceRecord]
) -> list[ReferenceCheck]:
    """Keep the model's judgement but re-anchor facts to the extracted data."""
    by_index = {check.index: check for check in produced}
    reconciled: list[ReferenceCheck] = []
    for ref in batch:
        check = by_index.get(ref.index)
        record = records.get(ref.index)
        if check is None:
            reconciled.append(_unverified(ref, record))
            continue
        check.raw = ref.raw
        check.citing_sentences = [
            CitingSentence(quote=c.quote, location=c.location) for c in ref.citing_sentences
        ]
        if record is not None:
            # The URL and the retraction flag are facts from the database, not model output.
            check.found_at = record.url if record.found else ""
            if record.is_retracted:
                check.status = ReferenceStatus.retracted
                if record.retraction_notes:
                    check.notes = f"{check.notes} Retraction notice: {record.retraction_notes}".strip()
            elif not record.found and check.status in {
                ReferenceStatus.verified,
                ReferenceStatus.metadata_mismatch,
            }:
                # The model cannot verify an entry the lookup never found.
                check.status = ReferenceStatus.not_found
            if record.is_preprint and "preprint" not in check.notes.lower():
                check.notes = f"{check.notes} Indexed as a preprint.".strip()
        reconciled.append(check)
    return reconciled


def _unverified(ref: Reference, record: ReferenceRecord | None = None) -> ReferenceCheck:
    return ReferenceCheck(
        index=ref.index,
        raw=ref.raw,
        status=ReferenceStatus.could_not_verify,
        found_at=record.url if record and record.found else "",
        citing_sentences=[
            CitingSentence(quote=c.quote, location=c.location) for c in ref.citing_sentences
        ],
        supports_claim=SupportsClaim.could_not_check,
        notes="no_search_tool: no lookup result was available for this entry.",
    )


def _add_missing_citations(runner: PassRunner, paper: PaperContext, output: Pass3Output) -> None:
    """Claims in the paper that need a citation and have none. Needs no search tool."""
    sections = sections_of_kind(paper.sections, "introduction", "background", "methods", "discussion")
    if not sections:
        output.limitations.append(
            "Introduction/background sections were not identified, so missing citations "
            "were not checked."
        )
        return
    budget = runner.config.limits.pass1_section_max_chars
    body = "\n\n".join(
        f"=== {s.label} (pages {s.start_page}-{s.end_page}) ===\n{clip(s.text, budget)}"
        for s in sections
    )
    result = runner.structured(
        pass_name="pass3",
        label="pass3:missing_citations",
        task_prompt=(
            load_prompt(runner.config, "pass3_references")
            + "\n\nFor this call, list ONLY claims in the text below that assert a fact, a prior "
            "result, or a method taken from elsewhere and carry no citation. Fill "
            "`missing_citations`. Leave `references` empty and set `search_tool_available` to "
            "the value given in the input."
        ),
        payload=f"search_tool_available: {output.search_tool_available}\n\n{body}",
        schema=Pass3Output,
    )
    if result is None:
        output.limitations.append("The missing-citation check failed to produce valid output.")
        return
    output.missing_citations.extend(result.missing_citations)
    output.limitations.extend(result.limitations)
