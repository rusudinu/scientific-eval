"""Builds a small synthetic paper PDF with known defects, for tests and demos."""

from __future__ import annotations

from pathlib import Path

TITLE = "Latency Effects of Adaptive Caching in Distributed Key-Value Stores"

BODY: list[tuple[str, str, list[str]]] = [
    (
        "",
        "Abstract",
        [
            "We study adaptive caching in distributed key-value stores. We evaluate our",
            "policy on 240 workload traces and report a mean latency reduction of 31.4%",
            "over a least-recently-used baseline. Adaptive caching significantly",
            "outperforms every published alternative and is the state of the art.",
        ],
    ),
    (
        "1",
        "Introduction",
        [
            "Distributed key-value stores underpin most modern web infrastructure. It is",
            "well known that cache misses dominate tail latency in such systems. Prior",
            "work has shown that static cache sizing wastes up to 40% of memory [1].",
            "The first commercial key-value store was released in 1979.",
            "Our contribution is an adaptive policy that resizes the cache online.",
            "This approach was allready shown to be promising in early experiments.",
        ],
    ),
    (
        "2",
        "Related Work",
        [
            "Cache replacement has a long history. Belady's optimal algorithm is not",
            "realisable online [2]. Learned caching policies were proposed recently [3],",
            "and reinforcement learning approaches followed [4]. None of these works",
            "optimise for memory pressure, which our method addresses. We use the",
            "term data set here and dataset elsewhere in the paper.",
        ],
    ),
    (
        "3",
        "Method",
        [
            "Our policy tracks hit rate over a sliding window of W requests and resizes",
            "the cache by a factor alpha. We set W = 4096 and alpha = 1.2 in all",
            "experiments. The controller runs every 200 ms; earlier work reports",
            "controller intervals in msec. We evaluate on 240 traces collected from a",
            "production cluster. The traces were splitted into training and test sets.",
        ],
    ),
    (
        "4",
        "Results",
        [
            "Table 1 reports mean latency per policy. Our policy reduces mean latency",
            "from 8.10 ms to 5.90 ms, a reduction of 27.2%. The improvement is",
            "significant (t = 3.41, p = 0.048). Across the 200 traces used for the",
            "final evaluation, the effect was consistent. Adaptive caching therefore",
            "causes lower tail latency in production deployments.",
            "",
            "Table 1. Mean latency by policy over the evaluation traces.",
            "Policy            Mean latency (ms)     Std",
            "LRU               8.10                  1.40",
            "LFU               7.95                  1.55",
            "Adaptive (ours)   5.90                  1.20",
        ],
    ),
    (
        "5",
        "Discussion",
        [
            "The results confirm that adaptive sizing helps under memory pressure. We",
            "did not measure write-heavy workloads, and our evaluation used a single",
            "hardware configuration. The behaviour of the controller under bursty",
            "arrivals remains an open question.",
        ],
    ),
    (
        "6",
        "Conclusion",
        [
            "We presented an adaptive caching policy that reduces mean latency by 31.4%",
            "over an LRU baseline. The policy generalises to all distributed storage",
            "systems and should be adopted widely.",
        ],
    ),
    (
        "",
        "References",
        [
            "[1] Smith, J. and Larsen, K. Static cache sizing considered harmful.",
            "    Proceedings of the Symposium on Operating Systems, 2018.",
            "[2] Belady, L. A study of replacement algorithms for a virtual-storage",
            "    computer. IBM Systems Journal, 1966.",
            "[3] Chen, W., Gupta, R. and Oliveira, M. Learned cache replacement.",
            "    Journal of Systems Research, 2021. doi:10.1000/jsr.2021.0042",
            "[4] Nakamura, T. Reinforcement learning for cache admission. arXiv",
            "    preprint arXiv:2103.00001, 2021.",
        ],
    ),
]

FIGURE_CAPTION = "Figure 1. Hit rate over time for each policy on trace 17."


def build(path: Path) -> Path:
    """Write the synthetic paper to `path` and return it."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    cursor = 72.0
    page.insert_text((72, cursor), TITLE, fontsize=15, fontname="Helvetica-Bold")
    cursor += 22
    page.insert_text((72, cursor), "A. Researcher and B. Coauthor", fontsize=10)
    cursor += 28

    for number, title, lines in BODY:
        heading = f"{number} {title}".strip()
        if cursor > 700:
            page = doc.new_page()
            cursor = 72.0
        page.insert_text((72, cursor), heading, fontsize=12, fontname="Helvetica-Bold")
        cursor += 18
        for line in lines:
            if cursor > 740:
                page = doc.new_page()
                cursor = 72.0
            page.insert_text((72, cursor), line, fontsize=10)
            cursor += 13
        cursor += 10
        if title == "Results":
            if cursor > 700:
                page = doc.new_page()
                cursor = 72.0
            page.insert_text((72, cursor), FIGURE_CAPTION, fontsize=10)
            cursor += 20

    doc.save(path)
    doc.close()
    return path


if __name__ == "__main__":  # pragma: no cover
    import sys

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic-paper.pdf")
    build(target)
    print(f"wrote {target}")
