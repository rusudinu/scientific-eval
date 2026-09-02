"""PDF text extraction with layout hints, via pymupdf."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass
class Line:
    """One visual line of text with the layout hints we use for heading detection."""

    text: str
    page: int
    size: float
    bold: bool
    x0: float
    y0: float

    @property
    def is_short(self) -> bool:
        return len(self.text) <= 120


class NoTextError(RuntimeError):
    """Raised for a PDF with no extractable text layer, e.g. a scan."""


@dataclass
class Document:
    path: Path
    lines: list[Line]
    page_count: int
    body_size: float
    metadata: dict[str, str]

    @property
    def text(self) -> str:
        return lines_to_text(self.lines)


# Below this, the PDF carries no usable text layer.
MIN_TEXT_CHARS = 200

_WS = re.compile(r"[ \t]+")
# Ligatures and typographic characters pymupdf hands back verbatim.
_REPLACEMENTS = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ", "−": "-",
}


def normalise(text: str) -> str:
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return _WS.sub(" ", text).strip()


def extract_document(path: Path) -> Document:
    """Read a PDF into lines carrying page, font size and bold flags."""
    import pymupdf

    doc = pymupdf.open(path)
    lines: list[Line] = []
    sizes: list[float] = []
    try:
        for page_index, page in enumerate(doc, start=1):
            data = page.get_text("dict")
            for block in data.get("blocks", []):
                if block.get("type") != 0:  # 0 = text
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = normalise("".join(span.get("text", "") for span in spans))
                    if not text:
                        continue
                    size = max((span.get("size", 0.0) for span in spans), default=0.0)
                    flags = max((span.get("flags", 0) for span in spans), default=0)
                    bbox = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
                    lines.append(
                        Line(
                            text=text,
                            page=page_index,
                            size=round(size, 2),
                            bold=bool(flags & 2 ** 4),
                            x0=round(bbox[0], 1),
                            y0=round(bbox[1], 1),
                        )
                    )
                    sizes.extend([round(size, 2)] * len(text))
        metadata = {k: str(v) for k, v in (doc.metadata or {}).items() if v}
        page_count = doc.page_count
    finally:
        doc.close()

    if sum(len(line.text) for line in lines) < MIN_TEXT_CHARS:
        raise NoTextError(
            f"{path.name} has almost no extractable text ({page_count} pages). It is probably a "
            f"scan; run OCR on it first (for example `ocrmypdf in.pdf out.pdf`) and review the "
            f"OCR'd file."
        )

    body_size = median(sizes) if sizes else 10.0
    return Document(
        path=path,
        lines=lines,
        page_count=page_count,
        body_size=body_size,
        metadata=metadata,
    )


def lines_to_text(lines: list[Line]) -> str:
    """Join lines into text, de-hyphenating words broken across lines."""
    out: list[str] = []
    for line in lines:
        text = line.text
        if out and out[-1].endswith("-") and re.search(r"[a-z]-$", out[-1]):
            out[-1] = out[-1][:-1] + text.lstrip()
        else:
            out.append(text)
    return "\n".join(out)
